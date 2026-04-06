"""Celery / worker uchun oddiy Telegram xabarlari."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def _send_message_async(telegram_id: int, text: str) -> None:
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN yo'q — xabar yuborilmadi")
        return
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        logger.exception("telegram_notify %s", telegram_id)
    finally:
        await bot.session.close()


def send_telegram_text_sync(telegram_id: int, text: str) -> None:
    asyncio.run(_send_message_async(telegram_id, text))
