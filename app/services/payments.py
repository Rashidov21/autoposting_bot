from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PaymentRequest


def list_pending_payment_requests(db: Session, limit: int = 20) -> list[PaymentRequest]:
    return list(
        db.execute(
            select(PaymentRequest)
            .where(PaymentRequest.status == "pending")
            .options(selectinload(PaymentRequest.user))
            .order_by(PaymentRequest.created_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
