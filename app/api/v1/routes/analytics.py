from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.stats import account_performance, campaign_totals
from app.api.deps import verify_internal_secret
from app.db.session import get_db

router = APIRouter()


@router.get("/campaign/{campaign_id}", dependencies=[Depends(verify_internal_secret)])
def campaign_stats(campaign_id: str, db: Session = Depends(get_db)) -> dict:
    return campaign_totals(db, uuid.UUID(campaign_id))


@router.get("/account/{account_id}", dependencies=[Depends(verify_internal_secret)])
def acc_stats(account_id: str, db: Session = Depends(get_db)) -> dict:
    return account_performance(db, uuid.UUID(account_id))
