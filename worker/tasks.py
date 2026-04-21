from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.models import Campaign, Schedule, SendLog
from app.db.session import SessionLocal
from app.core.config import get_settings
from engine.sender import run_campaign_round_sync
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.tasks.schedule_due_campaigns")
def schedule_due_campaigns() -> None:
    """Navbatdagi kampaniyalarni topib, bajarish vazifasini yuboradi (task_id bilan dublikat oldini olish)."""
    now = datetime.now(timezone.utc)
    settings = get_settings()
    db = SessionLocal()
    try:
        schedules = db.execute(
            select(Schedule)
            .join(Campaign, Campaign.id == Schedule.campaign_id)
            .where(Campaign.status == "running")
            .where(Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at.asc())
            .limit(settings.schedule_due_campaigns_batch_limit)
        ).scalars().all()
        if not schedules:
            return
        queued = 0
        for s in schedules:
            tid = f"pc-{s.campaign_id}-{int(s.next_run_at.timestamp())}"
            try:
                process_campaign.apply_async(
                    args=[str(s.campaign_id)],
                    task_id=tid,
                    queue=settings.celery_campaign_queue,
                )
                queued += 1
            except Exception as e:
                logger.info("enqueue skip (dublikat yoki broker): %s", e)
        logger.info("schedule_due_campaigns due=%s queued=%s", len(schedules), queued)
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
        try:
            asyncio.run(send_login_code(acc, proxy, phone))
        except Exception as exc:
            err_msg = str(exc)[:512]
            acc.last_error = f"Kod yuborish xatosi: {err_msg}"
            db.add(acc)
            db.commit()
            logger.warning("send_login_code_task failed account=%s: %s", aid, exc)
            raise
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
        try:
            asyncio.run(complete_login(acc, proxy, phone, code.strip()))
            db.add(acc)
            from app.services import users as user_service

            created_gids = user_service.ensure_default_groups_for_account(db, acc)
            user_service.queue_group_title_sync(created_gids)
            db.commit()
        except Exception as exc:
            err_msg = str(exc)[:512]
            acc.last_error = f"Login xatosi: {err_msg}"
            db.add(acc)
            db.commit()
            logger.warning("complete_login_task failed account=%s: %s", aid, exc)
            raise
    finally:
        db.close()


@celery_app.task(name="worker.tasks.prune_send_logs_task")
def prune_send_logs_task(retain_days: int = 30) -> int:
    """send_logs jadvalidagi eski yozuvlarni o'chiradi (default: 30 kundan eski)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    db = SessionLocal()
    try:
        result = db.execute(
            delete(SendLog).where(SendLog.created_at < cutoff)
        )
        deleted = int(result.rowcount or 0)
        db.commit()
        if deleted:
            logger.info("prune_send_logs_task deleted=%s rows older than %s days", deleted, retain_days)
        return deleted
    except Exception:
        logger.exception("prune_send_logs_task")
        db.rollback()
        raise
    finally:
        db.close()
