from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Tashkent")


def format_local_datetime(dt: datetime) -> str:
    """Foydalanuvchiga UTC+5 (Toshkent) vaqtida ko'rsatish."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(DISPLAY_TZ)
    return local.strftime("%d.%m.%Y %H:%M:%S")
