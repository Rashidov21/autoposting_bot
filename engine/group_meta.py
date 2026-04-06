from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from telethon import TelegramClient

from app.db.models import Account, Group, Proxy
from engine.client_factory import build_client

logger = logging.getLogger(__name__)


async def sync_group_title(client: TelegramClient, g: Group) -> None:
    peer = int(g.telegram_chat_id)
    try:
        ent = await client.get_entity(peer)
        title = getattr(ent, "title", None) or getattr(ent, "first_name", None)
        uname = getattr(ent, "username", None)
        if title:
            g.title = title[:512]
        if uname:
            g.username = uname[:255]
        g.last_checked_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.info("Guruh nomi olinmadi peer=%s: %s", peer, e)


async def sync_groups_titles_for_ids(db: Session, group_ids: list[uuid.UUID]) -> None:
    if not group_ids:
        return
    groups = list(db.execute(select(Group).where(Group.id.in_(group_ids))).scalars().all())
    if not groups:
        return
    by_user: dict[uuid.UUID, list[Group]] = {}
    for g in groups:
        by_user.setdefault(g.user_id, []).append(g)

    for uid, glist in by_user.items():
        acc = db.execute(
            select(Account).where(Account.user_id == uid, Account.status == "active")
        ).scalar_one_or_none()
        if not acc:
            continue
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
            for g in glist:
                await sync_group_title(client, g)
                db.add(g)
        finally:
            await client.disconnect()
