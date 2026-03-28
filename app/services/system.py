from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemSetting


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
