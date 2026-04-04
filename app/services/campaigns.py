from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.db.models import Campaign, CampaignAccount, CampaignGroup, Group, Schedule, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pause_all_running_for_user(
    db: Session, user_id: uuid.UUID, except_campaign_id: uuid.UUID | None = None
) -> int:
    """Barcha running kampaniyalarni paused qiladi. except_campaign_id berilsa, uni o'tkazib yuboradi."""
    q = select(Campaign).where(Campaign.user_id == user_id, Campaign.status == "running")
    if except_campaign_id is not None:
        q = q.where(Campaign.id != except_campaign_id)
    rows = list(db.execute(q).scalars().all())
    for c in rows:
        c.status = "paused"
        db.add(c)
    return len(rows)


def get_running_campaign_for_user(db: Session, user_id: uuid.UUID) -> Campaign | None:
    return db.execute(
        select(Campaign).where(Campaign.user_id == user_id, Campaign.status == "running")
    ).scalar_one_or_none()


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


def start_campaign(db: Session, campaign: Campaign) -> tuple[Schedule, int]:
    if campaign.status == "running":
        s = db.execute(select(Schedule).where(Schedule.campaign_id == campaign.id)).scalar_one_or_none()
        if s:
            return s, 0

    paused_n = pause_all_running_for_user(db, campaign.user_id, except_campaign_id=campaign.id)

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


def list_user_campaigns(db: Session, user_id: uuid.UUID) -> list[Campaign]:
    return list(db.execute(select(Campaign).where(Campaign.user_id == user_id)).scalars().all())
