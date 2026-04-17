from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel, Chat, InputPeerChannel, User

logger = logging.getLogger(__name__)


@dataclass
class SendAttemptMeta:
    retry_count: int = 0
    slowmode_wait_seconds: int = 0
    flood_wait_seconds: int = 0


class EntityCache:
    """LRU cache for resolved Telegram entities per account/client."""

    def __init__(self, max_size: int = 500) -> None:
        self.max_size = max_size
        self._data: OrderedDict[int, Any] = OrderedDict()

    def get(self, peer: int) -> Any | None:
        v = self._data.get(peer)
        if v is not None:
            self._data.move_to_end(peer)
        return v

    def set(self, peer: int, entity: Any) -> None:
        self._data[peer] = entity
        self._data.move_to_end(peer)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)


async def resolve_entity(client: TelegramClient, peer: int, cache: EntityCache) -> Any:
    cached = cache.get(peer)
    if cached is not None:
        return cached
    entity = await client.get_entity(peer)
    cache.set(peer, entity)
    return entity


def _can_use_typing(entity: Any) -> bool:
    # Channels/megagroups often reject typing action; skip to avoid ChatIdInvalidError.
    return isinstance(entity, (User, Chat))


def _entity_peer_id(entity: Any) -> int:
    return int(getattr(entity, "id", 0) or 0)


async def ensure_joined_entity(
    client: TelegramClient,
    entity: Any,
    joined_cache: set[int],
) -> None:
    """
    Best-effort join for channels. If already joined or join is not possible, do not crash sender.
    """
    peer_id = _entity_peer_id(entity)
    if not peer_id or peer_id in joined_cache:
        return
    try:
        if isinstance(entity, (Channel, InputPeerChannel)):
            await client(JoinChannelRequest(entity))
    except errors.UserAlreadyParticipantError:
        pass
    except (
        errors.ChannelPrivateError,
        errors.InviteHashExpiredError,
        errors.InviteHashInvalidError,
        errors.ChatAdminRequiredError,
    ):
        # Keep going; sender will fail at send stage and log proper reason.
        pass
    finally:
        joined_cache.add(peer_id)


async def safe_send_message(
    client: TelegramClient,
    entity: Any,
    text: str,
    *,
    account_lock: asyncio.Lock,
    chat_next_allowed_at: dict[int, float],
    typing_probability: float,
    pre_send_delay_seconds: float,
    slowmode_retries: int = 1,
    flood_retries: int = 2,
) -> SendAttemptMeta:
    """
    Send with Telegram-aware retries.
    - SlowMode: wait exact seconds, retry 1x
    - FloodWait: exponential wait (1x, 2x, 4x), retry limited times
    """
    meta = SendAttemptMeta()
    peer_id = _entity_peer_id(entity)
    retries_slow = 0
    retries_flood = 0
    generic_attempt = 0

    while True:
        wait_until = chat_next_allowed_at.get(peer_id, 0.0)
        now = time.monotonic()
        if wait_until > now:
            await asyncio.sleep(wait_until - now)

        async with account_lock:
            try:
                # Global message-level delay to smooth burst and reduce ban risk.
                await asyncio.sleep(pre_send_delay_seconds)
                if random.random() < typing_probability and _can_use_typing(entity):
                    async with client.action(entity, "typing"):
                        await asyncio.sleep(random.uniform(0.3, 1.1))
                await client.send_message(entity, text)
                return meta
            except errors.SlowModeWaitError as e:
                wait_seconds = max(int(e.seconds), 1)
                meta.slowmode_wait_seconds = wait_seconds
                if retries_slow >= slowmode_retries:
                    raise
                retries_slow += 1
                meta.retry_count += 1
                chat_next_allowed_at[peer_id] = time.monotonic() + wait_seconds
                logger.warning("slowmode_wait", extra={"peer_id": peer_id, "wait_seconds": wait_seconds})
                await asyncio.sleep(wait_seconds)
            except errors.FloodWaitError as e:
                wait_seconds = max(int(e.seconds), 1)
                meta.flood_wait_seconds = wait_seconds
                if retries_flood >= flood_retries:
                    raise
                retries_flood += 1
                meta.retry_count += 1
                multiplier = 2 ** (retries_flood - 1)
                backoff = wait_seconds * multiplier + random.uniform(0.2, 1.0)
                logger.warning(
                    "flood_wait",
                    extra={
                        "peer_id": peer_id,
                        "wait_seconds": wait_seconds,
                        "multiplier": multiplier,
                    },
                )
                await asyncio.sleep(backoff)
            except Exception:
                if generic_attempt >= 2:
                    raise
                generic_attempt += 1
                meta.retry_count += 1
                await asyncio.sleep((2 ** (generic_attempt - 1)) + random.uniform(0.1, 0.8))
