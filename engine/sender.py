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
    AccountGroupBlocklist,
    Campaign,
    CampaignGroup,
    Group,
    Proxy,
    SendLog,
)
from app.db.models import Schedule
from engine.anti_ban import maybe_skip_group, shuffle_order, vary_message_text, warm_up_multiplier
from engine.campaign_signals import clear_revoke, get_text as signal_get_text, is_revoked
from engine.client_factory import build_client
from engine.redis_pool import get_redis
from engine.telegram_helpers import EntityCache, ensure_joined_entity, resolve_entity, safe_send_message

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _campaign_lock_key(campaign_id: uuid.UUID) -> str:
    """Back-compat: ``engine.distributed_lock`` ishlatadi."""
    return f"campaign:exec:{campaign_id}"


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
    # Endi global invalid emas; (account, group) blocklist yozuvi uchun ishlatamiz.
    mark_account_group_blocked: bool = False
    # Faqat guruh Telegramda umuman yo'q bo'lganda (ChatIdInvalid, PeerIdInvalid):
    mark_group_invalid: bool = False
    account_banned: bool = False
    account_reauth_required: bool = False
    flood_wait_seconds: int = 0
    warmup_inc: int = 0
    retry_count: int = 0
    slowmode_wait_seconds: int = 0
    # When entity resolution succeeds, carry the freshly-resolved access_hash
    # back to run_campaign_round so it can be persisted to the DB.
    group_access_hash: int | None = None
    # Updated StringSession string — faqat rost o'zgargan bo'lsa saqlaymiz.
    session_update: str | None = None


def _mark_account_banned(db: Session, acc: Account, msg: str) -> None:
    acc.status = "banned"
    acc.last_error = msg
    db.add(acc)


def _mark_account_reauth_required(db: Session, acc: Account, msg: str) -> None:
    """
    ``is_user_authorized()`` False qaytarsa yoki ``AuthKeyUnregistered`` kelsa
    akkauntni ``reauth_required`` ga o'tkazamiz. Shunda u keyingi roundlarda
    tanlanmaydi va foydalanuvchi bot UI orqali qayta login qila oladi.
    """
    acc.status = "reauth_required"
    acc.last_error = msg
    db.add(acc)


def _mark_group_invalid(db: Session, g: Group, msg: str) -> None:
    """Faqat guruh **butunlay** yo'q bo'lgan holat (ChatIdInvalid va h.k.)."""
    g.is_valid = False
    g.last_error = msg
    g.last_checked_at = _utcnow()
    db.add(g)


def _upsert_blocklist(db: Session, account_id: uuid.UUID, group_id: uuid.UUID, reason: str, msg: str) -> None:
    """
    (account, group) juftligini blocklistga qo'shadi. Agar allaqachon mavjud
    bo'lsa, reason/msg ni yangilaydi (idempotent).
    """
    existing = db.get(AccountGroupBlocklist, (account_id, group_id))
    if existing is None:
        db.add(
            AccountGroupBlocklist(
                account_id=account_id,
                group_id=group_id,
                reason=reason,
                error_message=(msg or "")[:2000],
            )
        )
    else:
        existing.reason = reason
        existing.error_message = (msg or "")[:2000]
        existing.updated_at = _utcnow()
        db.add(existing)


def _load_blocklist_pairs(db: Session, account_ids: list[uuid.UUID]) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """
    Shu kampaniyadagi akkauntlar uchun barcha bloklangan (account, group)
    juftliklarini bitta zapros bilan yuklaydi. Planning da O(1) lookup uchun
    set qaytaradi.
    """
    if not account_ids:
        return set()
    rows = db.execute(
        select(AccountGroupBlocklist.account_id, AccountGroupBlocklist.group_id).where(
            AccountGroupBlocklist.account_id.in_(account_ids)
        )
    ).all()
    now = _utcnow()
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for aid, gid in rows:
        # Kelajakda blocked_until asosida temporary filtering qo'shish mumkin;
        # hozir hammasi permanent deb hisoblanadi.
        _ = now  # reserved for future temporary-ban logic
        pairs.add((aid, gid))
    return pairs


def _plan_assignments(
    groups: list[Group],
    accounts: list[Account],
    campaign: Campaign,
    *,
    rotation: str,
    blocklist: set[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[list[tuple[Group, Account]], list[SendLog]]:
    """
    Round-robin / random bilan guruhni akkauntga biriktiradi. Bloklangan
    (account, group) juftliklarini o'tkazib yuboradi — boshqa akkauntga
    urinib ko'radi. Barcha akkauntlar shu guruh uchun bloklangan bo'lsa,
    guruh shu round uchun skip bo'ladi (keyingi round yana urinib ko'riladi).
    """
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

    def try_assign_non_blocked(g: Group) -> Account | None:
        # Maksimum ``len(accounts)`` ta akkauntni sinaymiz; bloklangani
        # yo'qligini tekshirib boramiz.
        tried: set[uuid.UUID] = set()
        while len(tried) < len(accounts):
            acc = pick_account()
            if acc.id in tried:
                # Cycle: barcha akkauntlar bloklangan.
                break
            tried.add(acc.id)
            if (acc.id, g.id) in blocklist:
                continue
            if per_account_counts[acc.id] >= acc.max_groups_limit:
                continue
            return acc
        return None

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
        acc = try_assign_non_blocked(g)
        if acc is None:
            # Barcha akkauntlar ushbu guruh uchun bloklangan. Skip qilamiz,
            # lekin guruhni global invalid deb belgilamaymiz.
            skipped_logs.append(
                SendLog(
                    campaign_id=campaign.id,
                    group_id=g.id,
                    status="skipped",
                    meta={"reason": "all_accounts_blocked"},
                )
            )
            continue
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
    redis_client = get_redis()
    # DB dagi matnni fallback sifatida ushlab turamiz; Redis ustuvor — bot
    # tahririda yangilanadi, workerga realtime yetadi.
    fallback_text = campaign.message_text
    # ``session.save()`` natijasini faqat sessiya haqiqatan o'zgargan (yangi
    # access_hash qo'shilgan) bo'lsa saqlaymiz. ``get_dialogs`` olib tashlangani
    # uchun session payload har roundda kichkina bo'ladi.
    _new_session_str: str | None = None

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
    try:
        if not await client.is_user_authorized():
            logger.warning("account_unauthorized account=%s", acc.id)
            # Akkauntni reauth_required ga o'tkazamiz (status yangilanishi
            # run_campaign_round da qilinadi). Shu orqali keyingi roundda
            # ushbu akkaunt filterlanadi.
            outcomes.append(
                _SendOutcome(
                    account_id=acc.id,
                    group_id=None,
                    status="meta",
                    account_reauth_required=True,
                    error_message="Session avtorizatsiya qilinmagan",
                )
            )
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

        # DIQQAT: ``get_dialogs(limit=None)`` bu yerdan olib tashlangan.
        # Har roundda barcha dialoglarni chaqirish Telegram flood sabab bo'lar
        # edi (2.A muammo). Entity resolution endi ``tg_access_hash`` (DB dan
        # saqlanadi) va ``username`` orqali ishlaydi. Yangi guruhlarda
        # ``sync_groups_titles_task`` bir marta cold-prime qiladi.

        while not queue.empty():
            # --- revoke signal: bot tahrirda/delete_all da yoqib qo'yadi. ---
            # Shu round ichidagi qolgan guruhlarga yuborish to'xtatiladi, outcome
            # yo'qolmaydi, ``finish_schedule`` da ``next_run_at`` tez qayta
            # ishga tushadi va yangi matn bilan round boshlanadi.
            if is_revoked(redis_client, campaign.id):
                logger.info(
                    "campaign_revoked_graceful_exit",
                    extra={"campaign_id": str(campaign.id), "account_id": str(acc.id)},
                )
                break

            g = await queue.get()

            # ``message_text`` ni har iteration Redisdan o'qiymiz -> bot tahriri
            # keyingi yuborishdayoq hisobga olinadi (1.A muammo).
            current_text = signal_get_text(redis_client, campaign.id) or fallback_text
            text = vary_message_text(current_text)

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
            except (errors.UserDeactivatedError, errors.UserDeactivatedBanError) as e:
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
            except errors.AuthKeyUnregisteredError as e:
                # Akkaunt Telegram tomonidan logout qilingan (boshqa qurilmadan,
                # sessiya cap, va h.k). "Banned" emas — qayta login yetarli.
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="AUTH_KEY_UNREGISTERED",
                        error_message=str(e),
                        account_reauth_required=True,
                    )
                )
                break
            except (errors.ChatWriteForbiddenError, errors.ChannelPrivateError, errors.ChatAdminRequiredError) as e:
                # DIQQAT: endi guruhni global invalid qilmaymiz. Faqat shu
                # (account, group) juftligi blocklistga qo'shiladi. Boshqa
                # akkauntlar shu guruhga yuborishda davom eta oladi.
                code = e.__class__.__name__.replace("Error", "").upper()
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code=code,
                        error_message=str(e),
                        mark_account_group_blocked=True,
                    )
                )
            except Exception as e:
                msg = str(e).lower()
                # Guruh Telegramdan umuman yo'qolgan / ID noto'g'ri: haqiqatan
                # ham global invalid deb belgilash mantiqli.
                mark_invalid = any(
                    k in msg
                    for k in (
                        "chat id is invalid",
                        "peer id invalid",
                        "channel invalid",
                        "chatidinvalid",
                        "peeridinvalid",
                    )
                )
                # "Not part of the chat" / "kicked" kabi - akkaunt-guruh darajasi:
                mark_blocked = any(k in msg for k in ("not part", "kicked", "banned in"))
                outcomes.append(
                    _SendOutcome(
                        account_id=acc.id,
                        group_id=g.id,
                        status="fail",
                        error_code="UNKNOWN",
                        error_message=str(e),
                        mark_group_invalid=mark_invalid,
                        mark_account_group_blocked=mark_blocked,
                    )
                )
                logger.exception("send_unknown account=%s group=%s", acc.id, g.id)

        # Round muvaffaqiyatli yakunlandi — sessiyani bir marta yozib qo'yamiz.
        # (Har send'dan keyin emas, chunki ``expire_on_commit=False`` + har
        # send - ortiqcha yuk.) Sessiyani faqat yangi access_hash topilgan
        # bo'lsa yangilanadi; aks holda bir xil bayt - DB ga yozmaslik.
        try:
            _new_session_str = client.session.save()
        except Exception as _ses_exc:
            logger.warning(
                "session_save_failed account=%s: %s",
                acc.id, _ses_exc,
            )
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

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

    # Revoke holatini round tugashi bilan tozalaymiz — keyingi round uchun
    # signal yangidan kerak bo'lsa bot o'zi qayta qo'yadi.
    revoke_was_set_on_entry = is_revoked(get_redis(), campaign_id)

    def finish_schedule(*, revoked: bool = False) -> None:
        """
        Odatda: ``next_run_at = now + interval + jitter``.
        Revoke bilan uzilgan bo'lsa: ``next_run_at = now + kichik kechikish``
        -> yangi matn darhol ketish uchun navbatdagi roundga yo'l ochiladi.
        """
        if revoked:
            sched.last_run_at = _utcnow()
            sched.next_run_at = _utcnow() + timedelta(seconds=random.uniform(5, 20))
        else:
            jitter = random.uniform(0, 90)
            sched.last_run_at = _utcnow()
            sched.next_run_at = _utcnow() + timedelta(minutes=campaign.interval_minutes) + timedelta(seconds=jitter)
        db.add(sched)
        committer.finalize()

    if not groups:
        logger.warning("Guruhlar biriktirilmagan: %s", campaign_id)
        finish_schedule()
        return

    primary = db.get(Account, campaign.account_id)
    if not primary or primary.user_id != campaign.user_id:
        logger.warning("Kampaniya account_id yaroqsiz: campaign=%s account=%s", campaign_id, campaign.account_id)
        finish_schedule()
        return
    accounts = [primary]
    accounts = [a for a in accounts if a.status == "active"]
    now = _utcnow()
    accounts = [a for a in accounts if not a.flood_wait_until or a.flood_wait_until <= now]
    if not accounts:
        logger.warning("Faol akkaunt yo'q: %s", campaign_id)
        finish_schedule()
        return

    # Per-(account, group) blocklist ni bir marta yuklaymiz.
    blocklist = _load_blocklist_pairs(db, [a.id for a in accounts])

    rotation = campaign.rotation or "round_robin"
    groups_shuffled = shuffle_order([g for g in groups if g.is_valid])
    assignments, skip_logs = _plan_assignments(
        groups_shuffled, accounts, campaign, rotation=rotation, blocklist=blocklist,
    )
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
        p = db.get(Proxy, pid)
        # Nosog'lom proxyni ishlatmaymiz — akkauntni proxysiz (direct) urinamiz
        # yoki proxy majburiyligi siyosatiga qarab bog'lamaymiz. Bu yerda
        # proxy-majburligi yo'q: None qaytadi, build_client direct ulanadi.
        proxies[pid] = p if (p and p.is_healthy) else None

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

    # Round davomida revoke signali qo'yilgan bo'lsa ham, outcomelar yo'qolmasin.
    revoked_mid_round = is_revoked(get_redis(), campaign_id)

    group_map: dict[uuid.UUID, Group] = {g.id: g for g in groups}
    for idx, result in enumerate(worker_results):
        if isinstance(result, Exception):
            logger.exception("account_worker_failed idx=%s: %s", idx, result)
            continue
        for out in result:
            if out.status == "meta":
                acc = account_map.get(out.account_id)
                if acc:
                    changed = False
                    if out.warmup_inc > 0:
                        acc.warm_up_sent += out.warmup_inc
                        changed = True
                    if out.session_update:
                        acc.session_enc = encrypt_text(out.session_update)
                        changed = True
                    if out.account_reauth_required and acc.status == "active":
                        _mark_account_reauth_required(db, acc, out.error_message or "reauth")
                        changed = True
                    if changed:
                        db.add(acc)
                continue
            if not out.group_id:
                continue
            if out.account_banned:
                acc = account_map.get(out.account_id)
                if acc:
                    _mark_account_banned(db, acc, out.error_message or "ACCOUNT_BANNED")
            if out.account_reauth_required:
                acc = account_map.get(out.account_id)
                if acc and acc.status == "active":
                    _mark_account_reauth_required(db, acc, out.error_message or "reauth")
            if out.flood_wait_seconds > 0:
                acc = account_map.get(out.account_id)
                if acc:
                    acc.flood_wait_until = _utcnow() + timedelta(seconds=out.flood_wait_seconds + random.randint(1, 10))
                    db.add(acc)
            if out.mark_group_invalid:
                g = group_map.get(out.group_id)
                if g:
                    _mark_group_invalid(db, g, out.error_message or "GROUP_INVALID")
            if out.mark_account_group_blocked:
                _upsert_blocklist(
                    db,
                    out.account_id,
                    out.group_id,
                    reason=out.error_code or "BLOCKED",
                    msg=out.error_message or "",
                )
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

    finish_schedule(revoked=revoked_mid_round or revoke_was_set_on_entry)

    # Round muvaffaqiyatli tugadi (yoki revoke bilan) — Redis'dagi signalni
    # tozalab qo'yamiz. Foydalanuvchi tahrir qilmasa keyingi round oddiy
    # rejimda ishlaydi.
    if revoked_mid_round or revoke_was_set_on_entry:
        clear_revoke(campaign_id)


def run_campaign_round_sync(db: Session, campaign_id: uuid.UUID) -> None:
    """
    Celery task entrypoint. Fencing-token + heartbeat bilan Redis lock olinadi.
    Crash bo'lsa lock ~60 soniya ichida avtomatik bo'shaydi; uzoq ishlaydigan
    roundlarda esa heartbeat TTL ni uzaytirib boradi.
    """
    from engine.distributed_lock import acquire, release

    settings = get_settings()
    r = get_redis()
    held = acquire(
        r,
        _campaign_lock_key(campaign_id),
        ttl_ms=60_000,
        heartbeat_interval_s=20.0,
    )
    if held is None:
        logger.info("Kampaniya bajarilmoqda, takroriy ishga tushirish o'tkazildi: %s", campaign_id)
        return
    try:
        asyncio.run(run_campaign_round(db, campaign_id))
    finally:
        release(r, held)
