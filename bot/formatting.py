from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Tashkent")


def group_display_label(telegram_chat_id: int, title: str | None, *, max_len: int = 58) -> str:
    """Guruh tugmasi / ro'yxat uchun matn; nom bo'lmasa chat ID ko'rsatiladi."""
    t = (title or "").strip()
    if t:
        return t[:max_len]
    return f"Guruh {telegram_chat_id}"


def format_local_datetime(dt: datetime) -> str:
    """Foydalanuvchiga UTC+5 (Toshkent) vaqtida ko'rsatish."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(DISPLAY_TZ)
    return local.strftime("%d.%m.%Y %H:%M:%S")
