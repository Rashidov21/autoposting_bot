from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from telethon import errors

from app.core.config import get_settings
from app.core.security import encrypt_text
from app.db.models import (
    Account,
    Campaign,
    CampaignAccount,
    CampaignGroup,
    Group,
    Proxy,
    SendLog,
)
from app.db.models import Schedule
from engine.anti_ban import maybe_skip_group, shuffle_order, vary_message_text, warm_up_multiplier
from engine.client_factory import build_client
from engine.redis_pool import get_redis
from engine.telegram_helpers import EntityCache, ensure_joined_entity, resolve_entity, safe_send_message

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _campaign_lock_key(campaign_id: uuid.UUID) -> str:
    return f"campaign:exec:{campaign_id}"


def _try_acquire_campaign_lock(r, campaign_id: uuid.UUID, ttl: int) -> bool:
    return bool(r.set(_campaign_lock_key(campaign_id), "1", nx=True, ex=ttl))


def _release_campaign_lock(r, campaign_id: uuid.UUID) -> None:
    r.delete(_campaign_lock_key(campaign_id))


@dataclass
class _BatchCommitter:
    db: Session
    batch: int
    _pending: int = 0

    def step(self) -> None:
        self._pending += 1
        if self._pending >= self.batch:
            self.db.commit()
            self._pending = 0

    def finalize(self) -> None:
        self.db.commit()
        self._pending = 0


@dataclass
class _SendOutcome:
    account_id: uuid.UUID
    group_id: uuid.UUID | None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    mark_group_invalid: bool = False
    account_banned: bool = False
    flood_wait_seconds: int = 0
    warmup_inc: int = 0
    retry_count: int = 0
    slowmode_wait_seconds: int = 0
    # When entity resolution succeeds, carry the freshly-resolved access_hash
    # back to run_campaign_round so it can be persisted to the DB.
    group_access_hash: int | None = None
    # Updated StringSession string after get_dialogs(); saved to DB so future
    # rounds benefit from the populated entity cache without calling get_dialogs again.
    session_update: str | None = None


def _mark_account_banned(db: Session, acc: Account, msg: str) -> None:
    acc.status = "banned"
    acc.last_error = msg
    db.add(acc)


def _mark_group_invalid(db: Session, g: Group, msg: str) -> None:
    g.is_valid = False
    g.last_error = msg
    g.last_checked_at = _utcnow()
    db.add(g)


def _plan_assignments(
    groups: list[Group],
    accounts: list[Account],
    campaign: Campaign,
    *,
    rotation: str,
) -> tuple[list[tuple[Group, Account]], list[SendLog]]:
    rr_idx = random.randint(0, len(accounts) - 1) if rotation == "random" else 0
    per_account_counts: dict[uuid.UUID, int] = {a.id: 0 for a in accounts}
    skipped_logs: list[SendLog] = []
    assignments: list[tuple[Group, Account]] = []

    def pick_account() -> Account:
        nonlocal rr_idx
        if rotation == "random":
            return random.choice(accounts)
        for _ in range(len(accounts) * 2):
            acc = accounts[rr_idx % len(accounts)]
            rr_idx += 1
            if per_account_counts[acc.id] < acc.max_groups_limit:
                return acc
        return random.choice(accounts)

    for g in groups:
        if not g.is_valid:
            continue
        if maybe_skip_group(campaign.skip_group_probability):
            skipped_logs.append(
                SendLog(
                    campaign_id=campaign.id,
                    group_id=g.id,
                    status="skipped",
                    meta={"reason": "random_skip"},
                )
            )
            continue
        acc = pick_account()
        if per_account_counts[acc.id] >= acc.max_groups_limit:
            acc = pick_account()
        per_account_counts[acc.id] += 1
        assignments.append((g, acc))

    return assignments, skipped_logs


def _group_queue_map(
    assignments: list[tuple[Group, Account]],
) -> dict[uuid.UUID, asyncio.Queue[Group]]:
    out: dict[uuid.UUID, asyncio.Queue[Group]] = {}
    for g, acc in assignments:
        q = out.setdefault(acc.id, asyncio.Queue())
        q.put_nowait(g)
    return out


async def _account_worker(
    campaign: Campaign,
    acc: Account,
    queue: asyncio.Queue[Group],
    proxy: Proxy | None,
    settings,
) -> list[_SendOutcome]:
    outcomes: list[_SendOutcome] = []
    sent_by_worker = 0
    pause_every = random.randint(settings.sender_burst_min_messages, settings.sender_burst_max_messages)
    account_lock = asyncio.Lock()
    chat_next_allowed_at: dict[int, float] = {}
    joined_cache: set[int] = set()
    entity_cache = EntityCache(max_size=settings.sender_entity_cache_size)
    warmup_sent = acc.warm_up_sent

    try:
        client = build_client(acc, proxy)
    except Exception as e:
        logger.exception("client_build_failed account=%s", acc.id)
        while not queue.empty():
            g = queue.get_nowait()
            outcomes.append(
                _SendOutcome(
                    account_id=acc.id,
                    group_id=g.id,
                    status="fail",
                    error_code="client_build",
                    error_message=str(e),
                )
            )
        return outcomes

    await client.connect()
    _new_session_str: str | None = None
    try:
        if not await client.is_user_authorized():
            logger.warning("account_unauthorized account=%s", acc.id)
            while not queue.empty():
                g = queue.get_nowait()
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="ACCOUNT_UNAUTHORIZED",
                        error_message="Session avtorizatsiya qilinmagan",
                    )
                )
            return outcomes

        # Populate Telethon's in-memory entity cache so PeerChannel lookups succeed
        # for all groups the account is a member of, even without stored access_hash.
        # The updated StringSession (which includes the entity table) is saved back to
        # DB afterwards, so subsequent rounds skip this call for already-known groups.
        try:
            await client.get_dialogs(limit=None)
            _new_session_str = client.session.save()
            logger.info(
                "get_dialogs_ok account=%s",
                acc.id,
                extra={"account_id": str(acc.id)},
            )
        except Exception as _dlg_exc:
            logger.warning(
                "get_dialogs_failed account=%s: %s",
                acc.id, _dlg_exc,
                extra={"account_id": str(acc.id)},
            )

        while not queue.empty():
            g = await queue.get()
            text = vary_message_text(campaign.message_text)
            wm = warm_up_multiplier(warmup_sent)
            pre_send_delay = random.uniform(
                settings.sender_message_delay_min_seconds,
                settings.sender_message_delay_max_seconds,
            ) * wm
            peer = int(g.telegram_chat_id)
            try:
                entity = await resolve_entity(
                    client,
                    peer,
                    entity_cache,
                    username=g.username or None,
                    access_hash=g.tg_access_hash or None,
                )
                # Persist any newly-resolved access_hash back to the DB via outcome.
                resolved_access_hash: int | None = getattr(entity, "access_hash", None)
                await ensure_joined_entity(client, entity, joined_cache)
                meta = await safe_send_message(
                    client,
                    entity,
                    text,
                    account_lock=account_lock,
                    chat_next_allowed_at=chat_next_allowed_at,
                    typing_probability=settings.typing_simulation_probability,
                    pre_send_delay_seconds=pre_send_delay,
                    slowmode_retries=settings.sender_retry_slowmode_retries,
                    flood_retries=settings.sender_retry_flood_retries,
                )
                warmup_sent += 1
                sent_by_worker += 1
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="success",
                        warmup_inc=1,
                        retry_count=meta.retry_count,
                        slowmode_wait_seconds=meta.slowmode_wait_seconds,
                        flood_wait_seconds=meta.flood_wait_seconds,
                        group_access_hash=resolved_access_hash,
                    )
                )
                logger.info(
                    "send_success",
                    extra={
                        "campaign_id": str(campaign.id),
                        "account_id": str(acc.id),
                        "group_id": str(g.id),
                        "retry_count": meta.retry_count,
                    },
                )
                if sent_by_worker >= pause_every:
                    long_pause = random.uniform(
                        settings.sender_burst_pause_min_seconds,
                        settings.sender_burst_pause_max_seconds,
                    )
                    await asyncio.sleep(long_pause)
                    sent_by_worker = 0
                    pause_every = random.randint(
                        settings.sender_burst_min_messages,
                        settings.sender_burst_max_messages,
                    )
            except errors.SlowModeWaitError as e:
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="SLOWMODE_WAIT",
                        error_message=str(e),
                        slowmode_wait_seconds=max(int(e.seconds), 1),
                    )
                )
            except errors.FloodWaitError as e:
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="FLOOD_WAIT",
                        error_message=str(e),
                        flood_wait_seconds=max(int(e.seconds), 1),
                    )
                )
                break
            except (errors.UserDeactivatedError, errors.UserDeactivatedBanError, errors.AuthKeyUnregisteredError) as e:
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="ACCOUNT_BANNED",
                        error_message=str(e),
                        account_banned=True,
                    )
                )
                break
            except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError, errors.ChatAdminRequiredError) as e:
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="GROUP_INVALID",
                        error_message=str(e),
                        mark_group_invalid=True,
                    )
                )
            except Exception as e:
                msg = str(e).lower()
                mark_invalid = "private" in msg or "kicked" in msg or "not part" in msg
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="UNKNOWN",
                        error_message=str(e),
                        mark_group_invalid=mark_invalid,
                    )
                )
                logger.exception("send_unknown account=%s group=%s", acc.id, g.id)
    finally:
        await client.disconnect()

    outcomes.append(
        _SendOutcome(
            account_id=acc.id,
            group_id=None,
            status="meta",
            warmup_inc=warmup_sent - acc.warm_up_sent if warmup_sent > acc.warm_up_sent else 0,
            session_update=_new_session_str,
        )
    )
    return outcomes


async def run_campaign_round(db: Session, campaign_id: uuid.UUID) -> None:
    campaign = db.execute(
        select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.schedule))
    ).scalar_one_or_none()
    if not campaign or campaign.status != "running":
        logger.info("Kampaniya topilmadi yoki ishlamayapti: %s", campaign_id)
        return

    sched = campaign.schedule
    if not sched:
        logger.warning("Schedule yo'q: %s", campaign_id)
        return

    gids = db.execute(select(CampaignGroup.group_id).where(CampaignGroup.campaign_id == campaign_id)).scalars().all()
    groups = list(db.execute(select(Group).where(Group.id.in_(gids))).scalars().all())
    settings = get_settings()
    committer = _BatchCommitter(db, settings.sender_log_commit_batch)

    def finish_schedule() -> None:
        jitter = random.uniform(0, 90)
        sched.last_run_at = _utcnow()
        sched.next_run_at = _utcnow() + timedelta(minutes=campaign.interval_minutes) + timedelta(seconds=jitter)
        db.add(sched)
        committer.finalize()

    if not groups:
        logger.warning("Guruhlar biriktirilmagan: %s", campaign_id)
        finish_schedule()
        return

    aids = db.execute(select(CampaignAccount.account_id).where(CampaignAccount.campaign_id == campaign_id)).scalars().all()
    if aids:
        accounts = list(db.execute(select(Account).where(Account.id.in_(aids))).scalars().all())
    else:
        accounts = list(
            db.execute(
                select(Account).where(Account.user_id == campaign.user_id, Account.status == "active")
            ).scalars().all()
        )

    accounts = [a for a in accounts if a.status == "active"]
    now = _utcnow()
    accounts = [a for a in accounts if not a.flood_wait_until or a.flood_wait_until <= now]
    if not accounts:
        logger.warning("Faol akkaunt yo'q: %s", campaign_id)
        finish_schedule()
        return

    rotation = campaign.rotation or "round_robin"
    groups_shuffled = shuffle_order([g for g in groups if g.is_valid])
    assignments, skip_logs = _plan_assignments(groups_shuffled, accounts, campaign, rotation=rotation)
    for sl in skip_logs:
        db.add(sl)
        committer.step()
    if not assignments:
        finish_schedule()
        return

    account_map: dict[uuid.UUID, Account] = {a.id: a for a in accounts}
    group_queues = _group_queue_map(assignments)
    used_accounts = [account_map[aid] for aid in group_queues.keys() if aid in account_map]
    proxy_ids = {a.proxy_id for a in used_accounts if a.proxy_id}
    proxies: dict[uuid.UUID, Proxy | None] = {}
    for pid in proxy_ids:
        proxies[pid] = db.get(Proxy, pid)

    worker_tasks: list[asyncio.Task[list[_SendOutcome]]] = []
    for acc_id in shuffle_order(list(group_queues.keys())):
        acc = account_map.get(acc_id)
        if not acc or acc.status != "active":
            continue
        worker_tasks.append(
            asyncio.create_task(
                _account_worker(
                    campaign,
                    acc,
                    group_queues[acc_id],
                    proxies.get(acc.proxy_id) if acc.proxy_id else None,
                    settings,
                )
            )
        )
    worker_results = await asyncio.gather(*worker_tasks, return_exceptions=True)

    group_map: dict[uuid.UUID, Group] = {g.id: g for g in groups}
    for idx, result in enumerate(worker_results):
        if isinstance(result, Exception):
            logger.exception("account_worker_failed idx=%s: %s", idx, result)
            continue
        for out in result:
            if out.status == "meta":
                acc = account_map.get(out.account_id)
                if acc:
                    if out.warmup_inc > 0:
                        acc.warm_up_sent += out.warmup_inc
                    if out.session_update:
                        # Persist the refreshed StringSession so next round's
                        # entity cache is pre-populated (avoids get_dialogs overhead).
                        acc.session_enc = encrypt_text(out.session_update)
                    if out.warmup_inc > 0 or out.session_update:
                        db.add(acc)
                continue
            if not out.group_id:
                continue
            if out.account_banned:
                acc = account_map.get(out.account_id)
                if acc:
                    _mark_account_banned(db, acc, out.error_message or "ACCOUNT_BANNED")
            if out.flood_wait_seconds > 0:
                acc = account_map.get(out.account_id)
                if acc:
                    acc.flood_wait_until = _utcnow() + timedelta(seconds=out.flood_wait_seconds + random.randint(1, 10))
                    db.add(acc)
            if out.mark_group_invalid:
                g = group_map.get(out.group_id)
                if g:
                    _mark_group_invalid(db, g, out.error_message or "GROUP_INVALID")
            # Persist freshly-resolved access_hash so future rounds skip entity lookup.
            if out.group_access_hash is not None:
                g = group_map.get(out.group_id)
                if g and g.tg_access_hash != out.group_access_hash:
                    g.tg_access_hash = out.group_access_hash
                    db.add(g)
            db.add(
                SendLog(
                    campaign_id=campaign.id,
                    account_id=out.account_id,
                    group_id=out.group_id,
                    status=out.status,
                    error_code=out.error_code,
                    error_message=out.error_message,
                    meta={
                        "retry_count": out.retry_count,
                        "slowmode_wait_seconds": out.slowmode_wait_seconds,
                        "flood_wait_seconds": out.flood_wait_seconds,
                    },
                )
            )
            committer.step()

    finish_schedule()


def run_campaign_round_sync(db: Session, campaign_id: uuid.UUID) -> None:
    settings = get_settings()
    r = get_redis()
    if not _try_acquire_campaign_lock(r, campaign_id, settings.campaign_lock_ttl_seconds):
        logger.info("Kampaniya bajarilmoqda, takroriy ishga tushirish o'tkazildi: %s", campaign_id)
        return
    try:
        asyncio.run(run_campaign_round(db, campaign_id))
    finally:
        _release_campaign_lock(r, campaign_id)
