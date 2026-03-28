from __future__ import annotations

import uuid

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import verify_internal_secret
from app.db.models import User
from app.db.session import get_db
from app.services import system as system_service
from app.services import users as user_service

router = APIRouter()


@router.get("/users", dependencies=[Depends(verify_internal_secret)])
def list_users(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(User).order_by(User.created_at.desc()).limit(200)).scalars().all()
    return {
        "users": [
            {
                "id": str(u.id),
                "telegram_id": u.telegram_id,
                "username": u.username,
                "is_blocked": u.is_blocked,
            }
            for u in rows
        ]
    }


class BlockBody(BaseModel):
    user_id: str
    blocked: bool


@router.post("/users/block", dependencies=[Depends(verify_internal_secret)])
def block_user(body: BlockBody, db: Session = Depends(get_db)) -> dict:
    u = user_service.block_user(db, uuid.UUID(body.user_id), body.blocked)
    if not u:
        raise HTTPException(status_code=404)
    db.commit()
    return {"ok": True}


class BotToggleBody(BaseModel):
    enabled: bool


@router.post("/bot/toggle", dependencies=[Depends(verify_internal_secret)])
def bot_toggle(body: BotToggleBody, db: Session = Depends(get_db)) -> dict:
    system_service.set_bot_enabled(db, body.enabled)
    db.commit()
    return {"bot_enabled": body.enabled}


@router.get("/bot/status", dependencies=[Depends(verify_internal_secret)])
def bot_status(db: Session = Depends(get_db)) -> dict:
    return {"bot_enabled": system_service.get_bot_enabled(db)}
