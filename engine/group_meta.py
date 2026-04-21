from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from telethon import TelegramClient

from app.core.security import encrypt_text
from app.db.models import Account, Group, Proxy
from engine.client_factory import build_client
from engine.telegram_helpers import EntityCache, resolve_entity  # noqa: F401 (used in sync_groups_titles_for_ids)

logger = logging.getLogger(__name__)


async def sync_group_title(client: TelegramClient, g: Group, cache: "EntityCache | None" = None) -> None:
    from engine.telegram_helpers import EntityCache, resolve_entity

    peer = int(g.telegram_chat_id)
    _cache = cache if cache is not None else EntityCache(max_size=1)
    try:
        ent = await resolve_entity(
            client,
            peer,
            _cache,
            username=g.username or None,
            access_hash=g.tg_access_hash or None,
        )
        title = getattr(ent, "title", None) or getattr(ent, "first_name", None)
        uname = getattr(ent, "username", None)
        fresh_hash: int | None = getattr(ent, "access_hash", None)
        if title:
            g.title = title[:512]
        if uname:
            g.username = uname[:255]
        if fresh_hash is not None and g.tg_access_hash != fresh_hash:
            g.tg_access_hash = fresh_hash
        g.last_checked_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.info("Guruh nomi olinmadi peer=%s: %s", peer, e)


async def sync_groups_titles_for_ids(db: Session, group_ids: list[uuid.UUID]) -> None:
    if not group_ids:
        return
    groups = list(db.execute(select(Group).where(Group.id.in_(group_ids))).scalars().all())
    if not groups:
        return
    by_account: dict[uuid.UUID, list[Group]] = {}
    for g in groups:
        by_account.setdefault(g.account_id, []).append(g)

    for aid, glist in by_account.items():
        acc = db.get(Account, aid)
        if not acc or acc.status != "active":
            continue
        uid = acc.user_id
        proxy = db.get(Proxy, acc.proxy_id) if acc.proxy_id else None
        try:
            client = build_client(acc, proxy)
        except Exception as e:
            logger.warning("Client build sync titles user=%s: %s", uid, e)
            continue
        await client.connect()
        try:
            if not await client.is_user_authorized():
                continue

            # Populate session entity cache so PeerChannel lookups succeed
            # for groups the account is a member of.
            try:
                await client.get_dialogs(limit=None)
            except Exception as _dlg_exc:
                logger.warning("get_dialogs failed sync titles user=%s: %s", uid, _dlg_exc)

            cache = EntityCache(max_size=300)
            for g in glist:
                try:
                    ent = await resolve_entity(
                        client,
                        int(g.telegram_chat_id),
                        cache,
                        username=g.username or None,
                        access_hash=g.tg_access_hash or None,
                    )
                    title = getattr(ent, "title", None) or getattr(ent, "first_name", None)
                    uname = getattr(ent, "username", None)
                    fresh_hash: int | None = getattr(ent, "access_hash", None)
                    if title:
                        g.title = title[:512]
                    if uname:
                        g.username = uname[:255]
                    if fresh_hash is not None and g.tg_access_hash != fresh_hash:
                        g.tg_access_hash = fresh_hash
                    g.last_checked_at = datetime.now(timezone.utc)
                except Exception as e:
                    logger.info("Guruh nomi olinmadi peer=%s: %s", g.telegram_chat_id, e)
                db.add(g)
                if g.title:
                    # Bir xil chat_id shu akkaunt ostidagi boshqa yozuvlarga (kamdan-kam).
                    same_chat_groups = list(
                        db.execute(
                            select(Group).where(
                                Group.telegram_chat_id == g.telegram_chat_id,
                                Group.account_id == g.account_id,
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for x in same_chat_groups:
                        x.title = g.title
                        if g.username:
                            x.username = g.username
                        if g.tg_access_hash is not None:
                            x.tg_access_hash = g.tg_access_hash
                        x.last_checked_at = datetime.now(timezone.utc)
                        db.add(x)

            # Persist the refreshed session so entity cache survives across calls.
            try:
                acc.session_enc = encrypt_text(client.session.save())
                db.add(acc)
            except Exception as _ses_exc:
                logger.warning("session save failed sync titles user=%s: %s", uid, _ses_exc)
        finally:
            await client.disconnect()
