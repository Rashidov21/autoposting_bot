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
