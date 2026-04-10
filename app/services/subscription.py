from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import PaymentRequest, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_subscription_active(user: User) -> bool:
    if user.subscription_ends_at is None:
        return False
    ends = user.subscription_ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    return ends > _utcnow()


def has_bot_access(user: User) -> bool:
    """Faqat faol obuna yoki demo davrida botdan to'liq foydalanish."""
    if is_subscription_active(user):
        return True
    if user.demo_expires_at is None:
        return True
    de = user.demo_expires_at
    if de.tzinfo is None:
        de = de.replace(tzinfo=timezone.utc)
    return _utcnow() < de


def create_payment_request(
    db: Session,
    user: User,
    tariff_months: int,
    screenshot_file_id: str,
    contact_phone: str,
) -> PaymentRequest:
    if tariff_months not in (1, 6, 12):
        raise ValueError("tariff_months 1, 6 yoki 12 bo'lishi kerak")
    phone = (contact_phone or "").strip()
    if len(phone) < 9:
        raise ValueError("Aloqa telefoni noto'g'ri")
    existing = db.execute(
        select(PaymentRequest).where(
            PaymentRequest.user_id == user.id,
            PaymentRequest.status == "pending",
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("Sizda ko'rib chiqilmagan to'lov arizasi bor. Iltimos, admin javobini kuting.")
    pr = PaymentRequest(
        user_id=user.id,
        tariff_months=tariff_months,
        status="pending",
        screenshot_file_id=screenshot_file_id,
        contact_phone=phone,
    )
    db.add(pr)
    user.payment_status = "pending"
    db.add(user)
    db.flush()
    return pr


def approve_payment(db: Session, request_id: uuid.UUID, admin_telegram_id: int) -> PaymentRequest | None:
    pr = db.get(PaymentRequest, request_id)
    if not pr or pr.status != "pending":
        return None
    user = db.get(User, pr.user_id)
    if not user:
        return None

    now = _utcnow()
    base = now
    if user.subscription_ends_at:
        se = user.subscription_ends_at
        if se.tzinfo is None:
            se = se.replace(tzinfo=timezone.utc)
        if se > now:
            base = se
    user.subscription_ends_at = base + timedelta(days=30 * pr.tariff_months)
    user.payment_status = "active"
    user.sub_reminder_3d_sent = False
    user.sub_reminder_1d_sent = False

    pr.status = "approved"
    pr.resolved_at = now
    pr.resolved_by_telegram_id = admin_telegram_id
    db.add(pr)
    db.add(user)
    return pr


def reject_payment(db: Session, request_id: uuid.UUID, admin_telegram_id: int) -> PaymentRequest | None:
    pr = db.get(PaymentRequest, request_id)
    if not pr or pr.status != "pending":
        return None
    user = db.get(User, pr.user_id)
    if not user:
        return None

    pr.status = "rejected"
    pr.resolved_at = _utcnow()
    pr.resolved_by_telegram_id = admin_telegram_id
    if user.payment_status == "pending":
        user.payment_status = "rejected"
    db.add(pr)
    db.add(user)
    return pr


def list_pending_payment_requests(db: Session, limit: int = 50) -> list[PaymentRequest]:
    q = (
        select(PaymentRequest)
        .options(joinedload(PaymentRequest.user))
        .where(PaymentRequest.status == "pending")
        .order_by(PaymentRequest.created_at.asc())
        .limit(limit)
    )
    return list(db.execute(q).scalars().unique().all())


def list_users_paginated(db: Session, offset: int, limit: int) -> tuple[list[User], int]:
    total = db.execute(select(func.count()).select_from(User)).scalar_one()
    rows = (
        db.execute(select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    )
    return list(rows), int(total)


def purge_expired_demo_users(db: Session) -> int:
    """Demo tugagan, obuna yo'q, to'lov kutilmaydigan foydalanuvchilarni o'chiradi."""
    now = _utcnow()
    q = select(User).where(User.demo_expires_at.isnot(None))
    users = list(db.execute(q).scalars().all())
    ids: list[uuid.UUID] = []
    for u in users:
        de = u.demo_expires_at
        if de is None:
            continue
        if de.tzinfo is None:
            de = de.replace(tzinfo=timezone.utc)
        if now < de:
            continue
        if is_subscription_active(u):
            continue
        if (u.payment_status or "") == "pending":
            continue
        ids.append(u.id)
    if not ids:
        return 0
    db.execute(delete(User).where(User.id.in_(ids)))
    db.flush()
    return len(ids)


def list_users_needing_subscription_reminders(db: Session) -> list[User]:
    """Obunasi tez orada tugaydigan foydalanuvchilar (UTC)."""
    now = _utcnow()
    rows = list(
        db.execute(
            select(User).where(
                User.subscription_ends_at.isnot(None),
                User.subscription_ends_at > now,
            )
        )
        .scalars()
        .all()
    )
    return rows
