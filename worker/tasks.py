from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import Campaign, Schedule
from app.db.session import SessionLocal
from engine.sender import run_campaign_round_sync
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.tasks.schedule_due_campaigns")
def schedule_due_campaigns() -> None:
    """Navbatdagi kampaniyalarni topib, bajarish vazifasini yuboradi (task_id bilan dublikat oldini olish)."""
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        schedules = db.execute(
            select(Schedule)
            .join(Campaign, Campaign.id == Schedule.campaign_id)
            .where(Campaign.status == "running")
            .where(Schedule.next_run_at <= now)
        ).scalars().all()
        for s in schedules:
            tid = f"pc-{s.campaign_id}-{int(s.next_run_at.timestamp())}"
            try:
                process_campaign.apply_async(args=[str(s.campaign_id)], task_id=tid)
                logger.info("Queued campaign %s task_id=%s", s.campaign_id, tid)
            except Exception as e:
                logger.info("enqueue skip (dublikat yoki broker): %s", e)
    finally:
        db.close()


@celery_app.task(name="worker.tasks.process_campaign")
def process_campaign(campaign_id: str) -> None:
    cid = uuid.UUID(campaign_id)
    db = SessionLocal()
    try:
        run_campaign_round_sync(db, cid)
    except Exception:
        logger.exception("process_campaign %s", campaign_id)
        raise
    finally:
        db.close()


@celery_app.task(name="worker.tasks.send_login_code_task")
def send_login_code_task(account_id: str, phone: str) -> None:
    import asyncio

    from app.db.models import Account, Proxy
    from engine.login import send_login_code

    aid = uuid.UUID(account_id)
    db = SessionLocal()
    try:
        acc = db.get(Account, aid)
        if not acc:
            return
        proxy = db.get(Proxy, acc.proxy_id) if acc.proxy_id else None
        asyncio.run(send_login_code(acc, proxy, phone))
    finally:
        db.close()


@celery_app.task(name="worker.tasks.purge_expired_demo_users_task")
def purge_expired_demo_users_task() -> int:
    """Demo tugagan, obuna yo'q foydalanuvchilarni DB dan olib tashlaydi."""
    from app.services import subscription as subscription_service

    db = SessionLocal()
    try:
        n = subscription_service.purge_expired_demo_users(db)
        db.commit()
        if n:
            logger.info("purge_expired_demo_users_task deleted=%s", n)
        return n
    except Exception:
        logger.exception("purge_expired_demo_users_task")
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="worker.tasks.subscription_reminder_task")
def subscription_reminder_task() -> None:
    """Obunasi 3 kun va 1 kun qoldiqda eslatma (kuniga bir marta)."""
    from app.services.telegram_notify import send_telegram_text_sync
    from app.services import subscription as subscription_service

    now = datetime.now(timezone.utc)
    today = now.date()
    db = SessionLocal()
    try:
        users = subscription_service.list_users_needing_subscription_reminders(db)
        for u in users:
            se = u.subscription_ends_at
            if not se:
                continue
            if se.tzinfo is None:
                se = se.replace(tzinfo=timezone.utc)
            d_left = (se.date() - today).days
            if d_left == 3 and not u.sub_reminder_3d_sent:
                send_telegram_text_sync(
                    u.telegram_id,
                    "📅 Obunangiz 3 kun ichida tugaydi. «💳 Tarif va to'lov» orqali uzaytiring.",
                )
                u.sub_reminder_3d_sent = True
                db.add(u)
            elif d_left == 1 and not u.sub_reminder_1d_sent:
                send_telegram_text_sync(
                    u.telegram_id,
                    "⚠️ Ertaga obuna tugaydi. «💳 Tarif va to'lov» orqali yangilang.",
                )
                u.sub_reminder_1d_sent = True
                db.add(u)
        db.commit()
    except Exception:
        logger.exception("subscription_reminder_task")
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="worker.tasks.sync_group_titles_task")
def sync_group_titles_task(group_ids: list[str]) -> None:
    """Guruh chat ID lariga Telethon orqali nom/username yozadi."""
    import asyncio

    from engine.group_meta import sync_groups_titles_for_ids

    gids = [uuid.UUID(x) for x in group_ids]
    db = SessionLocal()
    try:
        asyncio.run(sync_groups_titles_for_ids(db, gids))
        db.commit()
    except Exception:
        logger.exception("sync_group_titles_task")
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="worker.tasks.complete_login_task")
def complete_login_task(account_id: str, phone: str, code: str) -> None:
    import asyncio

    from app.db.models import Account, Proxy
    from engine.login import complete_login

    aid = uuid.UUID(account_id)
    db = SessionLocal()
    try:
        acc = db.get(Account, aid)
        if not acc:
            return
        proxy = db.get(Proxy, acc.proxy_id) if acc.proxy_id else None
        asyncio.run(complete_login(acc, proxy, phone, code.strip()))
        db.add(acc)
        db.commit()
    finally:
        db.close()
