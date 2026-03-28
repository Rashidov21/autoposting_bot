from __future__ import annotations

import asyncio
import logging
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from telethon import TelegramClient, errors

from app.core.config import get_settings
from app.db.models import (
    Account,
    Campaign,
    CampaignAccount,
    CampaignGroup,
    Group,
    Proxy,
    Schedule,
    SendLog,
)
from engine.anti_ban import (
    maybe_skip_group,
    random_delay,
    shuffle_order,
    vary_message_text,
    warm_up_multiplier,
)
from engine.client_factory import build_client

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _campaign_lock_key(campaign_id: uuid.UUID) -> str:
    return f"campaign:exec:{campaign_id}"


def _try_acquire_campaign_lock(r: redis.Redis, campaign_id: uuid.UUID, ttl: int) -> bool:
    return bool(r.set(_campaign_lock_key(campaign_id), "1", nx=True, ex=ttl))


def _release_campaign_lock(r: redis.Redis, campaign_id: uuid.UUID) -> None:
    r.delete(_campaign_lock_key(campaign_id))


@dataclass
class _BatchCommitter:
    """DB commit sonini kamaytirish (throughput), lekin flush() bilan yakuniy barqarorlik."""

    db: Session
    batch: int
    _pending: int = 0

    def step(self) -> None:
        self._pending += 1
        if self._pending >= self.batch:
            self.db.commit()
            self._pending = 0

    def finalize(self) -> None:
        """Har doim commit — oxirgi `sched` yangilanishi ham saqlansin."""
        self.db.commit()
        self._pending = 0


async def _send_one(
    client: TelegramClient,
    peer: int,
    text: str,
    min_d: float,
    max_d: float,
    warm_mult: float,
    *,
    typing_probability: float,
    pause_factor: float,
) -> None:
    lo = min_d * warm_mult
    hi = max_d * warm_mult
    delay = random_delay(lo, hi)
    if random.random() < typing_probability:
        async with client.action(peer, "typing"):
            await asyncio.sleep(delay)
    else:
        await asyncio.sleep(delay * pause_factor)
    await client.send_message(peer, text)


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
    """(guruh, akkaunt) juftliklari va skip loglari."""
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


async def _send_for_account(
    db: Session,
    campaign: Campaign,
    acc: Account,
    groups: list[Group],
    proxies: dict[uuid.UUID, Proxy | None],
    committer: _BatchCommitter,
) -> None:
    proxy = proxies.get(acc.proxy_id) if acc.proxy_id else None
    try:
        client = build_client(acc, proxy)
    except Exception as e:
        logger.exception("Client build account=%s", acc.id)
        for g in groups:
            db.add(
                SendLog(
                    campaign_id=campaign.id,
                    account_id=acc.id,
                    group_id=g.id,
                    status="fail",
                    error_code="client_build",
                    error_message=str(e),
                )
            )
            committer.step()
        return

    s = get_settings()
    typing_p = s.typing_simulation_probability
    pause_f = s.post_typing_pause_factor

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session avtorizatsiya qilinmagan")

        for g in groups:
            text = vary_message_text(campaign.message_text)
            wm = warm_up_multiplier(acc.warm_up_sent)
            peer = int(g.telegram_chat_id)
            try:
                await _send_one(
                    client,
                    peer,
                    text,
                    campaign.min_delay_seconds,
                    campaign.max_delay_seconds,
                    wm,
                    typing_probability=typing_p,
                    pause_factor=pause_f,
                )
                acc.warm_up_sent = acc.warm_up_sent + 1
                db.add(acc)
                db.add(
                    SendLog(
                        campaign_id=campaign.id,
                        account_id=acc.id,
                        group_id=g.id,
                        status="success",
                    )
                )
                committer.step()
            except errors.FloodWaitError as e:
                acc.flood_wait_until = _utcnow() + timedelta(seconds=int(e.seconds) + random.randint(1, 10))
                db.add(acc)
                db.add(
                    SendLog(
                        campaign_id=campaign.id,
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="FLOOD_WAIT",
                        error_message=str(e),
                    )
                )
                committer.step()
                logger.warning("FloodWait account=%s — qolgan guruhlar keyingi tsiklda", acc.id)
                break
            except (errors.UserDeactivatedError, errors.UserDeactivatedBanError, errors.AuthKeyUnregisteredError) as e:
                _mark_account_banned(db, acc, str(e))
                db.add(
                    SendLog(
                        campaign_id=campaign.id,
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="ACCOUNT_BANNED",
                        error_message=str(e),
                    )
                )
                committer.step()
                break
            except errors.ChatWriteForbiddenError as e:
                _mark_group_invalid(db, g, str(e))
                db.add(
                    SendLog(
                        campaign_id=campaign.id,
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="GROUP_INVALID",
                        error_message=str(e),
                    )
                )
                committer.step()
            except Exception as e:
                msg = str(e).lower()
                if "private" in msg or "kicked" in msg or "not part" in msg:
                    _mark_group_invalid(db, g, str(e))
                logger.exception("Yuborish account=%s peer=%s", acc.id, g.id)
                db.add(
                    SendLog(
                        campaign_id=campaign.id,
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="UNKNOWN",
                        error_message=str(e),
                    )
                )
                committer.step()
    finally:
        await client.disconnect()


async def run_campaign_round(db: Session, campaign_id: uuid.UUID) -> None:
    """
    Bitta aylanma: akkaunt bo'yicha bitta MTProto ulanish, guruhlar ketma-ketligi aralash.
    """
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

    by_account: dict[uuid.UUID, list[Group]] = defaultdict(list)
    account_map: dict[uuid.UUID, Account] = {a.id: a for a in accounts}
    for g, acc in assignments:
        by_account[acc.id].append(g)

    used_accounts = [account_map[aid] for aid in by_account.keys() if aid in account_map]
    proxy_ids = {a.proxy_id for a in used_accounts if a.proxy_id}
    proxies: dict[uuid.UUID, Proxy | None] = {}
    for pid in proxy_ids:
        proxies[pid] = db.get(Proxy, pid)

    for acc_id in shuffle_order(list(by_account.keys())):
        acc = account_map.get(acc_id)
        if not acc or acc.status != "active":
            continue
        await _send_for_account(
            db,
            campaign,
            acc,
            by_account[acc_id],
            proxies,
            committer,
        )

    finish_schedule()


def run_campaign_round_sync(db: Session, campaign_id: uuid.UUID) -> None:
    settings = get_settings()
    r = redis.from_url(settings.redis_url)
    if not _try_acquire_campaign_lock(r, campaign_id, settings.campaign_lock_ttl_seconds):
        logger.info("Kampaniya bajarilmoqda, takroriy ishga tushirish o'tkazildi: %s", campaign_id)
        return
    try:
        asyncio.run(run_campaign_round(db, campaign_id))
    finally:
        _release_campaign_lock(r, campaign_id)
