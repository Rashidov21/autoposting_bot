from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Group

logger = logging.getLogger(__name__)


async def refresh_group_titles_from_bot(bot: Bot, db: Session, groups: list[Group]) -> bool:
    """Bo'sh `title` uchun Bot API `get_chat` orqali nomni to'ldiradi. Bot ushbu chatda a'zo bo'lishi kerak."""
    changed = False
    now = datetime.now(timezone.utc)
    for g in groups:
        if (g.title or "").strip():
            continue
        try:
            chat = await bot.get_chat(g.telegram_chat_id)
        except TelegramBadRequest as e:
            logger.debug("get_chat rad etildi peer=%s: %s", g.telegram_chat_id, e)
            continue
        except Exception as e:
            logger.debug("get_chat xato peer=%s: %s", g.telegram_chat_id, e)
            continue
        title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
        uname = getattr(chat, "username", None) or None
        if not title and uname:
            title = f"@{uname}"
        if not title:
            continue
        same_chat = list(
            db.execute(
                select(Group).where(
                    Group.telegram_chat_id == g.telegram_chat_id,
                    Group.account_id == g.account_id,
                )
            )
            .scalars()
            .all()
        )
        for x in same_chat:
            x.title = title[:512]
            if uname:
                x.username = uname[:255]
            x.last_checked_at = now
            db.add(x)
            changed = True
    return changed
