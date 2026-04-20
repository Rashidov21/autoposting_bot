from __future__ import annotations

import uuid
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.security import decrypt_text
from app.db.models import Account, Proxy
from engine.device_profile import device_params


def build_client(account: Account, proxy: Proxy | None) -> TelegramClient:
    settings = get_settings()
    api_id, api_hash = settings.telethon_api
    proxy_arg = None
    if proxy:
        from engine.telethon_proxy import proxy_tuple

        proxy_arg = proxy_tuple(proxy)

    kw = dict(
        proxy=proxy_arg,
        connection_retries=settings.telethon_connection_retries,
        retry_delay=settings.telethon_retry_delay,
        timeout=settings.telethon_timeout,
        flood_sleep_threshold=24,
        request_retries=3,
        # auto_reconnect=True: NAT/proxy timeout yoki tarmoq tebranishida
        # Telethon ichki reconnect mexanizmi ishlasin. Aks holda uzun roundda
        # bitta uzilish butun workerni o'ldiradi va keyingi guruhlar qoladi.
        auto_reconnect=True,
        **device_params(account.id),
    )

    if account.session_enc:
        session = StringSession(decrypt_text(account.session_enc))
        return TelegramClient(session, api_id, api_hash, **kw)

    if account.session_path:
        path = Path(account.session_path)
        return TelegramClient(str(path), api_id, api_hash, **kw)

    raise RuntimeError(f"Account {account.id} uchun session yo'q")


def session_file_path(account_id: uuid.UUID) -> Path:
    settings = get_settings()
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    return settings.sessions_dir / f"{account_id}.session"
