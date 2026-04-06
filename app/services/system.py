from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemSetting

TUTORIAL_VIDEO_KEY = "tutorial_video_file_id"


def get_bot_enabled(db: Session) -> bool:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "bot_enabled")).scalar_one_or_none()
    if not row:
        return True
    v = row.value_json
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


def set_bot_enabled(db: Session, enabled: bool) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "bot_enabled")).scalar_one_or_none()
    if row:
        row.value_json = enabled
    else:
        db.add(SystemSetting(key="bot_enabled", value_json=enabled))


def get_tutorial_video_file_id(db: Session) -> str | None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == TUTORIAL_VIDEO_KEY)).scalar_one_or_none()
    if not row:
        return None
    v: Any = row.value_json
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, dict) and v.get("file_id"):
        return str(v["file_id"]).strip()
    return None


def set_tutorial_video_file_id(db: Session, file_id: str) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == TUTORIAL_VIDEO_KEY)).scalar_one_or_none()
    if row:
        row.value_json = file_id
    else:
        db.add(SystemSetting(key=TUTORIAL_VIDEO_KEY, value_json=file_id))
