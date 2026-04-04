from __future__ import annotations

from app.core.config import get_settings


def is_admin(telegram_id: int) -> bool:
    return telegram_id in get_settings().admin_telegram_id_set
