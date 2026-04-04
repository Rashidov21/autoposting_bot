from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import PaymentRequest, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_subscription_active(user: User) -> bool:
    if user.subscription_ends_at is None:
        return False
    return user.subscription_ends_at > _utcnow()


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
    if user.subscription_ends_at and user.subscription_ends_at > now:
        base = user.subscription_ends_at
    user.subscription_ends_at = base + timedelta(days=30 * pr.tariff_months)
    user.payment_status = "active"

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
