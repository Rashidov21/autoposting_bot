from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.services import system as system_service
from app.services import users as user_service


class AccessMiddleware(BaseMiddleware):
    """Bloklangan foydalanuvchi va bot OFF holatida to'xtatish."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from aiogram.types import Message, CallbackQuery

        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user is None:
            return await handler(event, data)

        db: Session = SessionLocal()
        try:
            if not system_service.get_bot_enabled(db):
                if isinstance(event, Message) and event.text and event.text.startswith("/"):
                    pass
                else:
                    if isinstance(event, Message):
                        await event.answer("Bot vaqtincha o'chirilgan.")
                    return None

            u = user_service.get_by_telegram_id(db, user.id)
            if u and u.is_blocked:
                if isinstance(event, Message):
                    await event.answer("Siz bloklangansiz.")
                return None
        finally:
            db.close()

        return await handler(event, data)
