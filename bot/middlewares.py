from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import TelegramObject

from sqlalchemy.orm import Session

from app.core.admin import is_admin
from app.db.session import SessionLocal
from app.services import system as system_service
from app.services import users as user_service
from app.services.subscription import is_subscription_active
from bot.messages import (
    MSG_ADMIN_ONLY,
    MSG_BLOCKED,
    MSG_BOT_DISABLED_GLOBAL,
    MSG_SUBSCRIPTION_REQUIRED,
    TEXT_ALLOWED_WITHOUT_SUBSCRIPTION,
)
from bot.states import PaymentStates


def _callback_allowed_without_subscription(data: str | None) -> bool:
    if not data:
        return False
    return data.startswith("tariff:") or data.startswith("cancel_tariff")


async def _payment_fsm_state(data: Dict[str, Any], event) -> str | None:
    try:
        bot = data["bot"]
        storage = data["fsm_storage"]
    except KeyError:
        return None
    if not event.from_user or not event.chat:
        return None
    key = StorageKey(bot_id=bot.id, chat_id=event.chat.id, user_id=event.from_user.id)
    return await storage.get_state(key=key)


class AccessMiddleware(BaseMiddleware):
    """Bot OFF, blok, obuna (admin va ruxsat berilgan callbacklar istisno)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        from aiogram.types import CallbackQuery, Message

        tg_user = None
        if isinstance(event, Message):
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user

        if tg_user is None:
            return await handler(event, data)

        db: Session = SessionLocal()
        try:
            if not system_service.get_bot_enabled(db):
                if isinstance(event, Message) and event.text and event.text.startswith("/"):
                    pass
                else:
                    if isinstance(event, Message):
                        await event.answer(MSG_BOT_DISABLED_GLOBAL)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(MSG_BOT_DISABLED_GLOBAL, show_alert=True)
                    return None

            u = user_service.get_by_telegram_id(db, tg_user.id)
            if u and u.is_blocked:
                if isinstance(event, Message):
                    await event.answer(MSG_BLOCKED)
                elif isinstance(event, CallbackQuery):
                    await event.answer(MSG_BLOCKED, show_alert=True)
                return None

            if isinstance(event, Message) and event.text and event.text.strip() == "/admin":
                if not is_admin(tg_user.id):
                    await event.answer(MSG_ADMIN_ONLY)
                    return None

            if isinstance(event, CallbackQuery) and event.data and event.data.startswith("admin:"):
                if not is_admin(tg_user.id):
                    await event.answer(MSG_ADMIN_ONLY, show_alert=True)
                    return None
                return await handler(event, data)

            if is_admin(tg_user.id):
                return await handler(event, data)

            if u and is_subscription_active(u):
                return await handler(event, data)

            if isinstance(event, Message):
                st = await _payment_fsm_state(data, event)
                if st in (PaymentStates.waiting_phone.state, PaymentStates.waiting_screenshot.state):
                    return await handler(event, data)

            if isinstance(event, CallbackQuery):
                if _callback_allowed_without_subscription(event.data):
                    return await handler(event, data)
                await event.answer(MSG_SUBSCRIPTION_REQUIRED, show_alert=True)
                return None

            if isinstance(event, Message):
                if event.photo:
                    return await handler(event, data)
                text = (event.text or "").strip()
                if text.startswith("/start") or text in TEXT_ALLOWED_WITHOUT_SUBSCRIPTION:
                    return await handler(event, data)
                await event.answer(MSG_SUBSCRIPTION_REQUIRED)
                return None
        finally:
            db.close()

        return await handler(event, data)
