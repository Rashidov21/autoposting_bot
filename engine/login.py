from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.security import encrypt_text
from app.db.models import Account, Proxy
from engine.client_factory import session_file_path
from engine.device_profile import device_params
from engine.redis_pool import get_redis
from engine.telethon_proxy import proxy_tuple

logger = logging.getLogger(__name__)


def _r():
    return get_redis()


def _key(account_id: uuid.UUID) -> str:
    return f"tglogin:{account_id}"


def normalize_login_code(raw: str) -> str:
    """Telegram login kodidan faqat raqamlarni ajratib oladi. Telethon sign_in() plain digits kutadi."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    return digits if digits else (raw or "").strip()


async def send_login_code(account: Account, proxy: Proxy | None, phone: str) -> None:
    settings = get_settings()
    api_id, api_hash = settings.telethon_api
    session = StringSession()
    proxy_arg = proxy_tuple(proxy) if proxy else None
    client = TelegramClient(
        session, api_id, api_hash,
        proxy=proxy_arg,
        **device_params(account.id),
    )
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        payload: dict[str, Any] = {
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "session": session.save(),
        }
        _r().setex(_key(account.id), 600, json.dumps(payload))
    finally:
        await client.disconnect()


async def complete_login(account: Account, proxy: Proxy | None, phone: str, code: str) -> None:
    settings = get_settings()
    api_id, api_hash = settings.telethon_api
    raw = _r().get(_key(account.id))
    if not raw:
        raise RuntimeError("Login sessiyasi topilmadi — kodni qayta so'rang")
    data = json.loads(raw)
    if data["phone"] != phone:
        raise RuntimeError("Telefon raqam mos emas")

    session = StringSession(data["session"])
    proxy_arg = proxy_tuple(proxy) if proxy else None
    client = TelegramClient(
        session, api_id, api_hash,
        proxy=proxy_arg,
        **device_params(account.id),
    )
    await client.connect()
    try:
        code_for_api = normalize_login_code(code)
        try:
            await client.sign_in(phone, code_for_api, phone_code_hash=data["phone_code_hash"])
        except errors.SessionPasswordNeededError as e:
            raise RuntimeError(
                "2FA parol talab qilinmoqda — hozircha bot orqali qo'llab-quvvatlanmaydi"
            ) from e
        account.session_enc = encrypt_text(session.save())
        account.phone = phone
        account.status = "active"
        account.session_path = None
        _r().delete(_key(account.id))
    finally:
        await client.disconnect()
