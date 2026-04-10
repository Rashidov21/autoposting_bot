from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services import system as system_service
from app.services import users as user_service
from app.services.subscription import has_bot_access
from bot.messages import BTN_CANCEL, BTN_HELP, BTN_TARIFF, BTN_VIDEO


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

        if user.id in get_settings().admin_telegram_id_set:
            return await handler(event, data)

        db: Session = SessionLocal()
        try:
            if not system_service.get_bot_enabled(db):
                if isinstance(event, Message) and event.text and event.text.startswith("/"):
                    pass
                else:
                    if isinstance(event, Message):
                        await event.answer("Bot vaqtincha o'chirilgan.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("Bot vaqtincha o'chirilgan.", show_alert=True)
                    return None

            u = user_service.get_by_telegram_id(db, user.id)
            if u and u.is_blocked:
                if isinstance(event, Message):
                    await event.answer("Siz bloklangansiz.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Siz bloklangansiz.", show_alert=True)
                return None

            if u is not None and not has_bot_access(u):
                allow = False
                if isinstance(event, Message):
                    t = (event.text or "").strip()
                    if t.startswith("/start") or t in (BTN_TARIFF, BTN_HELP, BTN_CANCEL, BTN_VIDEO):
                        allow = True
                    if event.contact or event.photo:
                        allow = True
                elif isinstance(event, CallbackQuery):
                    d = event.data or ""
                    if d.startswith("tariff:") or d == "cancel_tariff":
                        allow = True
                if not allow:
                    txt = (
                        "⏳ Demo muddati tugadi yoki obuna yo'q.\n"
                        "«💳 Tarif va to'lov»dan tarif tanlang va to'lov qiling."
                    )
                    if isinstance(event, Message):
                        await event.answer(txt)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(txt, show_alert=True)
                    return None
        finally:
            db.close()

        return await handler(event, data)
