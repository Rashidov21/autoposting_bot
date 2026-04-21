from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Account, Group, User

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_user(db: Session, telegram_id: int, username: str | None, full_name: str | None) -> User:
    q = select(User).where(User.telegram_id == telegram_id)
    u = db.execute(q).scalar_one_or_none()
    if u:
        u.username = username
        u.full_name = full_name
        return u
    settings = get_settings()
    demo_until = _utcnow() + timedelta(hours=settings.demo_hours)
    u = User(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        payment_status="none",
        demo_expires_at=demo_until,
    )
    db.add(u)
    db.flush()
    return u


def ensure_default_groups_for_account(db: Session, account: Account) -> list[uuid.UUID]:
    """Telethon akkaunt muvaffaqiyatli ulangach — default chat ID lar uchun ``groups`` yozuvlari."""
    created_ids: list[uuid.UUID] = []
    u = db.get(User, account.user_id)
    if not u:
        return created_ids
    default_ids = get_settings().default_group_chat_id_list
    if not default_ids:
        return created_ids
    for chat_id in default_ids:
        g = db.execute(
            select(Group).where(
                Group.user_id == u.id,
                Group.account_id == account.id,
                Group.telegram_chat_id == int(chat_id),
            )
        ).scalar_one_or_none()
        if g:
            continue
        ng = Group(
            user_id=u.id,
            account_id=account.id,
            telegram_chat_id=int(chat_id),
            is_valid=True,
        )
        db.add(ng)
        db.flush()
        created_ids.append(ng.id)
    return created_ids


def queue_group_title_sync(group_ids: list[uuid.UUID]) -> None:
    """Guruh nomlarini olish vazifasini queue ga qo'shadi."""
    if not group_ids:
        return
    try:
        from worker.tasks import sync_group_titles_task

        sync_group_titles_task.delay([str(x) for x in group_ids])
    except Exception as e:
        logger.info("sync_group_titles_task queue skip: %s", e)


def get_by_telegram_id(db: Session, telegram_id: int) -> User | None:
    return db.execute(select(User).where(User.telegram_id == telegram_id)).scalar_one_or_none()


def get_by_id(db: Session, uid: uuid.UUID) -> User | None:
    return db.get(User, uid)


def block_user(db: Session, uid: uuid.UUID, blocked: bool) -> User | None:
    u = db.get(User, uid)
    if not u:
        return None
    u.is_blocked = blocked
    return u


def delete_user(db: Session, uid: uuid.UUID) -> bool:
    u = db.get(User, uid)
    if not u:
        return False
    db.delete(u)
    return True


def list_users_paginated(db: Session, offset: int, limit: int) -> tuple[list[User], int]:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    rows = list(
        db.execute(select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    )
    return rows, int(total)
