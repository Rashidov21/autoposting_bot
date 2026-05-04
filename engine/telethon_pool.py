from __future__ import annotations

import asyncio
import logging
import uuid
from telethon import TelegramClient

from app.db.models import Account, Proxy
from engine.client_factory import build_client

logger = logging.getLogger(__name__)


class TelethonClientPool:
    """
    Bir jarayon ichida akkaunt uchun Telethon klientni uzoq muddat ochiq ushlab turadi.
    ``session_enc`` o'zgarganda ``invalidate`` chaqiring.
    """

    def __init__(self) -> None:
        self._clients: dict[uuid.UUID, TelegramClient] = {}
        self._lock = asyncio.Lock()

    async def ensure_client(self, acc: Account, proxy: Proxy | None) -> TelegramClient | None:
        async with self._lock:
            existing = self._clients.get(acc.id)
            if existing is not None:
                if existing.is_connected():
                    return existing
                try:
                    await existing.disconnect()
                except Exception:
                    pass
                self._clients.pop(acc.id, None)

            client = build_client(acc, proxy)
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    logger.warning("pool_client_unauthorized account=%s", acc.id)
                    await client.disconnect()
                    return None
            except Exception:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                raise

            self._clients[acc.id] = client
            return client

    async def invalidate(self, account_id: uuid.UUID) -> None:
        async with self._lock:
            c = self._clients.pop(account_id, None)
        if c is None:
            return
        try:
            await c.disconnect()
        except Exception:
            pass

    async def disconnect_all(self) -> None:
        async with self._lock:
            items = list(self._clients.items())
            self._clients.clear()
        for _, c in items:
            try:
                await c.disconnect()
            except Exception:
                pass
