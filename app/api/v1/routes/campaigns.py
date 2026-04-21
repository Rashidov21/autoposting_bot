from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import verify_internal_secret
from app.db.models import Account, Campaign, Group
from app.db.session import get_db
from app.services import campaigns as campaign_service
from app.services import users as user_service

router = APIRouter()


class CreateCampaignBody(BaseModel):
    telegram_id: int
    account_id: str = Field(..., description="Telethon accounts.id (UUID)")
    name: str = "Kampaniya"
    message_text: str
    interval_minutes: int = Field(..., ge=6, le=10, description="6 dan 10 gacha daqiqa")
    group_ids: list[str]


@router.post("/create", dependencies=[Depends(verify_internal_secret)])
def create_campaign(body: CreateCampaignBody, db: Session = Depends(get_db)) -> dict:
    u = user_service.get_by_telegram_id(db, body.telegram_id)
    if not u or u.is_blocked:
        raise HTTPException(status_code=403, detail="Foydalanuvchi yo'q yoki bloklangan")
    aid = uuid.UUID(body.account_id)
    acc = db.get(Account, aid)
    if not acc or acc.user_id != u.id:
        raise HTTPException(status_code=400, detail="account_id nota'g'ri")
    gids = [uuid.UUID(x) for x in body.group_ids]
    c = campaign_service.create_campaign(
        db,
        u,
        aid,
        body.name,
        body.message_text,
        body.interval_minutes,
        gids,
    )
    db.commit()
    return {"id": str(c.id), "status": c.status}


class StartBody(BaseModel):
    telegram_id: int
    campaign_id: str


@router.post("/start", dependencies=[Depends(verify_internal_secret)])
def start_campaign(body: StartBody, db: Session = Depends(get_db)) -> dict:
    u = user_service.get_by_telegram_id(db, body.telegram_id)
    if not u:
        raise HTTPException(status_code=404)
    cid = uuid.UUID(body.campaign_id)
    c = db.get(Campaign, cid)
    if not c or c.user_id != u.id:
        raise HTTPException(status_code=404)
    s, _paused = campaign_service.start_campaign(db, c)
    db.commit()
    return {"campaign_id": str(c.id), "next_run_at": s.next_run_at.isoformat()}


class StopBody(BaseModel):
    telegram_id: int
    campaign_id: str


@router.post("/stop", dependencies=[Depends(verify_internal_secret)])
def stop_campaign(body: StopBody, db: Session = Depends(get_db)) -> dict:
    u = user_service.get_by_telegram_id(db, body.telegram_id)
    if not u:
        raise HTTPException(status_code=404)
    cid = uuid.UUID(body.campaign_id)
    c = db.get(Campaign, cid)
    if not c or c.user_id != u.id:
        raise HTTPException(status_code=404)
    campaign_service.stop_campaign(db, c)
    db.commit()
    return {"ok": True}


class AddGroupBody(BaseModel):
    telegram_id: int
    account_id: str = Field(..., description="Telethon accounts.id (UUID)")
    telegram_chat_id: int
    title: str | None = None
    username: str | None = None


@router.post("/groups/add", dependencies=[Depends(verify_internal_secret)])
def add_group(body: AddGroupBody, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select as sa_select

    u = user_service.get_by_telegram_id(db, body.telegram_id)
    if not u:
        raise HTTPException(status_code=404)
    aid = uuid.UUID(body.account_id)
    acc = db.get(Account, aid)
    if not acc or acc.user_id != u.id:
        raise HTTPException(status_code=400, detail="account_id nota'g'ri")
    existing = db.execute(
        sa_select(Group).where(
            Group.user_id == u.id,
            Group.account_id == aid,
            Group.telegram_chat_id == body.telegram_chat_id,
        )
    ).scalar_one_or_none()
    if existing:
        if body.title and not existing.title:
            existing.title = body.title
        if body.username and not existing.username:
            existing.username = body.username
        db.add(existing)
        db.commit()
        return {"id": str(existing.id)}
    g = Group(
        user_id=u.id,
        account_id=aid,
        telegram_chat_id=body.telegram_chat_id,
        title=body.title,
        username=body.username,
        is_valid=True,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": str(g.id)}
