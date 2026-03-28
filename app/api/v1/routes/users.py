from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import verify_internal_secret
from app.db.session import get_db
from app.services import users as user_service

router = APIRouter()


class UpsertUserBody(BaseModel):
    telegram_id: int
    username: str | None = None
    full_name: str | None = None


@router.post("/upsert", dependencies=[Depends(verify_internal_secret)])
def upsert_user(body: UpsertUserBody, db: Session = Depends(get_db)) -> dict:
    u = user_service.upsert_user(db, body.telegram_id, body.username, body.full_name)
    db.commit()
    return {"id": str(u.id), "telegram_id": u.telegram_id}


@router.get("/by-telegram/{telegram_id}", dependencies=[Depends(verify_internal_secret)])
def get_user(telegram_id: int, db: Session = Depends(get_db)) -> dict:
    u = user_service.get_by_telegram_id(db, telegram_id)
    if not u:
        raise HTTPException(status_code=404, detail="User topilmadi")
    if u.is_blocked:
        raise HTTPException(status_code=403, detail="Bloklangan")
    return {"id": str(u.id), "telegram_id": u.telegram_id, "username": u.username}
