from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Campaign, CampaignAccount, CampaignGroup, Group, Schedule, User
from engine.campaign_signals import clear_text as _signal_clear_text
from engine.campaign_signals import set_revoke as _signal_set_revoke
from engine.campaign_signals import set_text as _signal_set_text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_groups_for_user(db: Session, user: User, telegram_chat_ids: list[int]) -> list[uuid.UUID]:
    """Foydalanuvchi uchun guruh yozuvlarini yaratadi yoki topadi."""
    out: list[uuid.UUID] = []
    for cid in telegram_chat_ids:
        g = db.execute(
            select(Group).where(Group.user_id == user.id, Group.telegram_chat_id == cid)
        ).scalar_one_or_none()
        if not g:
            g = Group(user_id=user.id, telegram_chat_id=int(cid), is_valid=True)
            db.add(g)
            db.flush()
        out.append(g.id)
    return out


def create_campaign(
    db: Session,
    user: User,
    name: str,
    message_text: str,
    interval_minutes: int,
    group_ids: list[uuid.UUID],
    rotation: str = "round_robin",
) -> Campaign:
    if interval_minutes not in (3, 5, 10, 15):
        raise ValueError("interval 3, 5, 10 yoki 15 bo'lishi kerak")

    c = Campaign(
        user_id=user.id,
        name=name,
        message_text=message_text,
        interval_minutes=interval_minutes,
        status="draft",
        rotation=rotation,
    )
    db.add(c)
    db.flush()

    for gid in group_ids:
        g = db.get(Group, gid)
        if not g or g.user_id != user.id:
            continue
        db.add(CampaignGroup(campaign_id=c.id, group_id=gid))

    return c


def create_campaign_from_chat_ids(
    db: Session,
    user: User,
    name: str,
    message_text: str,
    interval_minutes: int,
    telegram_chat_ids: list[int],
    rotation: str = "round_robin",
) -> Campaign:
    gids = ensure_groups_for_user(db, user, telegram_chat_ids)
    if not gids:
        raise ValueError("Hech qanday guruh biriktirilmadi")
    return create_campaign(db, user, name, message_text, interval_minutes, gids, rotation=rotation)


def set_campaign_accounts(db: Session, campaign: Campaign, account_ids: list[uuid.UUID]) -> None:
    db.execute(delete(CampaignAccount).where(CampaignAccount.campaign_id == campaign.id))
    for aid in account_ids:
        db.add(CampaignAccount(campaign_id=campaign.id, account_id=aid))


def _reschedule_running_cap(db: Session, campaign: Campaign) -> None:
    """
    Faqat ``next_run_at`` hozirgi kelajakda juda uzoq bo'lsa, uni
    ``now + interval`` ga qisqartiradi. Mavjud yaqinroq vaqtga tegmaydi.

    Sabab: foydalanuvchi tahrir qilganda keyingi yuborish vaqti **oldinga
    itarilmasin**. Aks holda har tahrir + interval daqiqa jazo bo'ladi.
    """
    if campaign.status != "running":
        return
    s = db.execute(select(Schedule).where(Schedule.campaign_id == campaign.id)).scalar_one_or_none()
    if not s:
        return
    jitter = random.uniform(0, 90)
    cap = _utcnow() + timedelta(minutes=campaign.interval_minutes) + timedelta(seconds=jitter)
    # Faqat mavjud next_run_at cap dan kattaroq bo'lsa (ya'ni foydalanuvchi
    # intervalni kamaytirgan bo'lsa yoki cap o'tmishda qolgan bo'lsa) qisqartiramiz.
    if s.next_run_at is None or s.next_run_at > cap:
        s.next_run_at = cap
        db.add(s)


def update_campaign_message_text(db: Session, campaign: Campaign, message_text: str) -> None:
    """
    Matnni DB va Redis ga yozadi. Ishlayotgan workerga revoke signali yuboradi
    -> u joriy roundni grace tugatadi va keyingi roundda yangi matn ketadi.

    DIQQAT: ``next_run_at`` ga tegilmaydi. Kaller explicit tez-yuborish
    kerak bo'lsa, ``trigger_immediate_round`` chaqirsin (hozirda avtomatik
    revoke + qisqa ``next_run_at`` sender ichida qo'yiladi).
    """
    campaign.message_text = message_text
    db.add(campaign)
    # Redis ga yozamiz -> in-flight worker keyingi yuborishdayoq o'qiydi.
    _signal_set_text(campaign.id, message_text)
    # Revoke signali: in-flight round grace tugasin va yangi matn bilan
    # qayta ishga tushsin.
    _signal_set_revoke(campaign.id, reason="text_edit")


def update_campaign_interval_minutes(db: Session, campaign: Campaign, interval_minutes: int) -> None:
    if interval_minutes not in (3, 5, 10, 15):
        raise ValueError("interval 3, 5, 10 yoki 15 bo'lishi kerak")
    campaign.interval_minutes = interval_minutes
    db.add(campaign)
    # Kichraytirilgan intervalda esa cap bilan yaqinlashtirish mantiqli
    # (masalan 15 daq -> 3 daq qilinganda).
    _reschedule_running_cap(db, campaign)


def replace_campaign_groups(db: Session, campaign: Campaign, group_ids: list[uuid.UUID]) -> None:
    db.execute(delete(CampaignGroup).where(CampaignGroup.campaign_id == campaign.id))
    for gid in group_ids:
        g = db.get(Group, gid)
        if not g or g.user_id != campaign.user_id:
            continue
        db.add(CampaignGroup(campaign_id=campaign.id, group_id=gid))
    db.add(campaign)
    # Guruhlar o'zgarganda - in-flight round'ga revoke yuborib, yangi to'plam
    # bilan keyingi roundni boshlash to'g'ri.
    _signal_set_revoke(campaign.id, reason="groups_edit")


def list_campaign_group_ids(db: Session, campaign_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.execute(
        select(CampaignGroup.group_id).where(CampaignGroup.campaign_id == campaign_id)
    ).scalars().all()
    return list(rows)


def start_campaign(db: Session, campaign: Campaign) -> tuple[Schedule, int]:
    """Kampaniyani ishga tushiradi; boshqa ishlayotgan kampaniyalarni pauzaga qo'yadi. (schedule, pauzalar soni)."""
    if campaign.status == "running":
        s = db.execute(select(Schedule).where(Schedule.campaign_id == campaign.id)).scalar_one_or_none()
        if s:
            return s, 0

    paused_n = 0
    others = list(
        db.execute(
            select(Campaign).where(
                Campaign.user_id == campaign.user_id,
                Campaign.status == "running",
                Campaign.id != campaign.id,
            )
        ).scalars().all()
    )
    for oc in others:
        stop_campaign(db, oc)
        paused_n += 1

    campaign.status = "running"
    jitter = random.uniform(0, 90)
    nra = _utcnow() + timedelta(minutes=campaign.interval_minutes) + timedelta(seconds=jitter)

    s = db.execute(select(Schedule).where(Schedule.campaign_id == campaign.id)).scalar_one_or_none()
    if s:
        s.next_run_at = nra
        db.add(s)
    else:
        s = Schedule(campaign_id=campaign.id, next_run_at=nra)
        db.add(s)
    db.add(campaign)
    db.flush()
    return s, paused_n


def stop_campaign(db: Session, campaign: Campaign) -> None:
    campaign.status = "paused"
    db.add(campaign)
    # In-flight round bo'lsa, grace bilan tugatsin.
    _signal_set_revoke(campaign.id, reason="stop")


def delete_user_group(db: Session, user: User, group_id: uuid.UUID) -> bool:
    """Foydalanuvchining guruh yozuvini o'chiradi; campaign_groups jadvalidagi bog'lanishlar CASCADE bilan yo'qoladi."""
    g = db.get(Group, group_id)
    if not g or g.user_id != user.id:
        return False
    db.delete(g)
    db.flush()
    return True


def list_groups_for_user(db: Session, user_id: uuid.UUID) -> list[Group]:
    """Foydalanuvchining barcha guruhlari (`groups` jadvali)."""
    return list(
        db.execute(select(Group).where(Group.user_id == user_id).order_by(Group.created_at.desc()))
        .scalars()
        .all()
    )


def delete_group_by_id(db: Session, group_id: uuid.UUID) -> bool:
    """Admin: `groups` jadvalidan ID bo'yicha yozuvni o'chiradi (campaign_groups CASCADE)."""
    g = db.get(Group, group_id)
    if not g:
        return False
    db.delete(g)
    db.flush()
    return True


def list_user_campaigns(db: Session, user_id: uuid.UUID) -> list[Campaign]:
    return list(db.execute(select(Campaign).where(Campaign.user_id == user_id)).scalars().all())


def revoke_in_flight_campaigns_for_user(db: Session, user: User) -> list[uuid.UUID]:
    """
    Foydalanuvchining barcha kampaniyalariga revoke signali yuboradi.
    Ishlayotgan worker grace exit qilib outcomelarini yozib ulguradi.

    Bu funksiya **tez** — Redis ga bir nechta kichik SET. Aiogram handlerdan
    chaqirish bexavf.

    Kaller keyin ~2 soniya (``await asyncio.sleep(2)``) kutib, so'ng
    ``delete_all_campaigns_for_user`` chaqirishi tavsiya etiladi — shu orqali
    ``send_logs`` FK violation oldi olinadi.
    """
    cids = list(
        db.execute(select(Campaign.id).where(Campaign.user_id == user.id)).scalars().all()
    )
    for cid in cids:
        _signal_set_revoke(cid, reason="delete_all")
        _signal_clear_text(cid)
    return cids


def delete_all_campaigns_for_user(db: Session, user: User) -> int:
    """
    Bitta foydalanuvchi uchun barcha xabar (kampaniya) yozuvlarini o'chiradi.

    Ishonchli flow:
      1) Kaller oldin ``revoke_in_flight_campaigns_for_user`` chaqiradi va
         ~2 soniya kutadi (async handler: ``await asyncio.sleep(2)``).
      2) Shundan so'ng shu funksiya DB delete ni bajaradi.

    Bu funksiya o'zi ham revoke+clear text yuboradi (idempotent) — agar kaller
    unutsa ham minimum himoya bor.
    """
    cids = list(
        db.execute(select(Campaign.id).where(Campaign.user_id == user.id)).scalars().all()
    )
    for cid in cids:
        _signal_set_revoke(cid, reason="delete_all")
        _signal_clear_text(cid)

    r = db.execute(delete(Campaign).where(Campaign.user_id == user.id))
    db.flush()
    return int(r.rowcount or 0)
