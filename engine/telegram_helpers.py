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
from telethon.tl.types import Channel, Chat, InputPeerChannel, PeerChannel, PeerChat, User

from app.core.config import get_settings

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


def _extract_channel_id(peer: int) -> int | None:
    """
    Extract the real Telegram channel_id from a negative peer integer.

    Telegram clients use two overlapping conventions for channel/supergroup IDs:
      - Bot API format : -(100_000_000_000 + channel_id)  -> string starts with "-100"
      - MTProto format : -(1_000_000_000_000 + channel_id) -> string also starts with "-100"
        for channel IDs >= 1_000_000_000 (10-digit IDs)

    For both cases, stripping the leading "100" characters from abs(peer) gives the
    correct channel_id.  Examples:
      -100219813130  -> 219813130    (Bot API, 9-digit channel_id)
      -1000219813130 -> 219813130    (MTProto equivalent)
      -1002190403415 -> 2190403415   (both formats coincide for 10-digit channel_ids)

    Returns None if peer is not a recognisable channel/supergroup negative ID.
    """
    if peer >= 0:
        return None
    s = str(abs(peer))
    if not s.startswith("100") or len(s) < 4:
        return None
    channel_id = int(s[3:])
    return channel_id if channel_id > 0 else None


async def resolve_entity(
    client: TelegramClient,
    peer: int,
    cache: EntityCache,
    *,
    username: str | None = None,
    access_hash: int | None = None,
) -> Any:
    """
    Resolve a Telegram entity with four ordered fallback strategies.

    Why raw ``get_entity(-100...)`` fails
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Telegram's MTProto API requires an ``access_hash`` to look up channels and
    supergroups.  Telethon's session stores (channel_id, access_hash) pairs from
    previous interactions.  If the pair is absent from the session (fresh worker
    process, new account, account never joined the group) Telethon raises
    ``ChatIdInvalidError`` or ``ValueError`` when given a bare integer.

    Resolution order
    ~~~~~~~~~~~~~~~~~
    1. **LRU cache** – free, no network round-trip.
    2. **InputPeerChannel(channel_id, access_hash)** – most reliable; works even
       when the account is not a member.  Requires ``access_hash`` from the DB.
    3. **Username** – works for public channels without ``access_hash``.
    4. **PeerChannel(channel_id)** – works only when Telethon's session cache
       already contains the ``(channel_id, access_hash)`` pair (i.e. the account
       previously interacted with this chat in the *same session file*).
    5. **PeerChat(abs_id)** – fallback for basic groups (non-supergroup).
    6. **Raw integer** – last resort; raises on failure.
    """
    cached = cache.get(peer)
    if cached is not None:
        return cached

    entity: Any = None
    channel_id = _extract_channel_id(peer)

    # --- Strategy 1: InputPeerChannel with stored access_hash ---
    if channel_id is not None and access_hash is not None:
        try:
            entity = await client.get_entity(InputPeerChannel(channel_id, access_hash))
        except Exception as exc:
            logger.debug(
                "resolve_entity: InputPeerChannel failed peer=%s: %s",
                peer, exc,
            )
            entity = None

    # --- Strategy 2: Username (public channels, no access_hash needed) ---
    if entity is None and username:
        try:
            entity = await client.get_entity(username.lstrip("@"))
        except Exception as exc:
            logger.debug(
                "resolve_entity: username failed peer=%s username=%s: %s",
                peer, username, exc,
            )
            entity = None

    # --- Strategy 3: PeerChannel (session cache must have access_hash) ---
    if entity is None and channel_id is not None:
        try:
            entity = await client.get_entity(PeerChannel(channel_id))
        except Exception as exc:
            logger.debug(
                "resolve_entity: PeerChannel failed peer=%s: %s",
                peer, exc,
            )
            entity = None

    # --- Strategy 4: PeerChat (basic groups, not supergroups) ---
    if entity is None and peer < 0 and channel_id is None:
        try:
            entity = await client.get_entity(PeerChat(abs(peer)))
        except Exception as exc:
            logger.debug(
                "resolve_entity: PeerChat failed peer=%s: %s",
                peer, exc,
            )
            entity = None

    # --- Strategy 5: Raw integer – raises on failure (intentional) ---
    if entity is None:
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
    ChatWriteForbiddenError on JoinChannelRequest means broadcast channel — account is already a
    member but cannot post; swallow it here so the send stage can give the real error.
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
        errors.ChatWriteForbiddenError,
        errors.UserBannedInChannelError,
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
    - Non-retryable errors (ChatWriteForbidden, ChannelPrivate, etc.) re-raised immediately.
    """
    settings = get_settings()
    typing_pause = max(0.3, settings.post_typing_pause_factor * 2.0)

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
                        await asyncio.sleep(typing_pause + random.uniform(0.0, 0.5))
                await client.send_message(entity, text)
                return meta
            except (
                errors.ChatWriteForbiddenError,
                errors.ChannelPrivateError,
                errors.ChatAdminRequiredError,
                errors.UserBannedInChannelError,
                errors.UserDeactivatedError,
                errors.UserDeactivatedBanError,
                errors.AuthKeyUnregisteredError,
            ):
                # These errors will never self-resolve — re-raise immediately without retry.
                raise
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
