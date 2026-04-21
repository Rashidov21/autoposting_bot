from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.core.config import get_settings
from bot.admin_handlers import router as admin_router
from bot.handlers import router
from bot.middlewares import AccessMiddleware

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN sozlanmagan")
    bot = Bot(settings.bot_token)
    fsm_url = (settings.fsm_redis_url or "").strip()
    storage = RedisStorage.from_url(fsm_url) if fsm_url else MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())
    dp.include_router(admin_router)
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
