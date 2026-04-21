"""Telethon akkauntlari: bitta foydalanuvchi uchun bitta ``active`` siyosati."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, User
from app.services import campaigns as campaign_service


def deactivate_other_active_accounts(db: Session, keep: Account) -> int:
    """
    ``keep`` dan tashqari, shu foydalanuvchining barcha ``active`` akkauntlarini
    ``replaced`` holatiga o'tkazadi va ularning ``running`` kampaniyalarini pauzaga qo'yadi.
    """
    user = db.get(User, keep.user_id)
    if not user:
        return 0
    others = list(
        db.execute(
            select(Account).where(
                Account.user_id == keep.user_id,
                Account.id != keep.id,
                Account.status == "active",
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for o in others:
        campaign_service.stop_all_running_campaigns_for_account(db, user, o.id)
        o.status = "replaced"
        o.last_error = "Boshqa akkaunt faollashtirildi."
        db.add(o)
        n += 1
    return n


def get_active_account_for_user(db: Session, user_id: uuid.UUID) -> Account | None:
    """
    Foydalanuvchining yagona (yoki eng so'nggi) ``active`` akkauntini qaytaradi.
    Agar DBda bir vaqtning o'zida bir nechta ``active`` qolgan bo'lsa — bittasini
    qoldirib, qolganlarini ``replaced`` qiladi (migratsiya / eski holat).
    """
    rows = list(
        db.execute(
            select(Account)
            .where(Account.user_id == user_id, Account.status == "active")
            .order_by(Account.updated_at.desc())
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    user = db.get(User, user_id)
    if not user:
        return rows[0]
    keep = rows[0]
    for o in rows[1:]:
        campaign_service.stop_all_running_campaigns_for_account(db, user, o.id)
        o.status = "replaced"
        o.last_error = "Bir vaqtning o'zida faqat bitta faol akkaunt — avtomatik tuzatildi."
        db.add(o)
    db.flush()
    return keep
