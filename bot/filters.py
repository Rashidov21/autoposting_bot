from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.core.admin import is_admin


async def admin_only_message(message: Message) -> bool:
    return message.from_user is not None and is_admin(message.from_user.id)


async def admin_only_callback(callback: CallbackQuery) -> bool:
    return callback.from_user is not None and is_admin(callback.from_user.id)
