from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import SendLog


def campaign_totals(db: Session, campaign_id: uuid.UUID) -> dict:
    q = (
        select(SendLog.status, func.count())
        .where(SendLog.campaign_id == campaign_id)
        .group_by(SendLog.status)
    )
    rows = db.execute(q).all()
    out = {status: int(n) for status, n in rows}
    total = sum(out.values())
    success = out.get("success", 0)
    rate = (success / total) if total else 0.0
    return {"total": total, "success": success, "success_rate": rate, "by_status": out}


def account_performance(db: Session, account_id: uuid.UUID) -> dict:
    q = (
        select(SendLog.status, func.count())
        .where(SendLog.account_id == account_id)
        .group_by(SendLog.status)
    )
    rows = db.execute(q).all()
    out = {status: int(n) for status, n in rows}
    total = sum(out.values())
    success = out.get("success", 0)
    rate = (success / total) if total else 0.0
    return {"total": total, "success": success, "success_rate": rate, "by_status": out}
