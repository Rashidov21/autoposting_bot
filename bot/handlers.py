from __future__ import annotations

import re
import uuid

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.stats import campaign_totals
from app.db.models import Account, Campaign, Group, Schedule
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services.campaigns import ALLOWED_INTERVAL_MINUTES
from app.services.group_titles_bot import refresh_group_titles_from_bot
from app.services import users as user_service
from bot.formatting import format_local_datetime, group_display_label
from bot.keyboards import groups_pick_kb, intervals_kb, main_menu
from bot.messages import (
    BTN_ACCOUNT,
    BTN_CANCEL,
    BTN_CREATE_CAMPAIGN,
    BTN_STATUS,
    BTN_STOP,
)
from bot.states import CampaignStates, LoginStates

router = Router()


def _list_active_accounts(db: Session, user_id: uuid.UUID) -> list[Account]:
    return list(
        db.execute(
            select(Account)
            .where(Account.user_id == user_id, Account.status == "active")
            .order_by(Account.created_at)
        )
        .scalars()
        .all()
    )


def _parse_interval(text: str) -> int | None:
    m = re.match(r"^(\d+)\s*daqiqa", text.strip(), re.I)
    if not m:
        return None
    v = int(m.group(1))
    return v if v in ALLOWED_INTERVAL_MINUTES else None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    db = SessionLocal()
    try:
        user_service.upsert_user(
            db,
            message.from_user.id,
            message.from_user.username,
            f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip(),
        )
        db.commit()
    finally:
        db.close()
    await message.answer(
        "Assalomu alaykum. Avtopost boshqaruv paneli.\n"
        "MTProto userbot orqali guruhlarga xabar yuboriladi.\n"
        "Bir necha qadamda yangi xabar oqimini sozlang.",
        reply_markup=main_menu(message.from_user.id),
    )


@router.message(F.text == BTN_CREATE_CAMPAIGN)
async def start_campaign(message: Message, state: FSMContext) -> None:
    await state.clear()
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        accs = _list_active_accounts(db, u.id)
    finally:
        db.close()
    if not accs:
        await message.answer(
            "Avval «👤 Akkaunt ulash» orqali Telethon akkaunt ulang.",
            reply_markup=main_menu(message.from_user.id),
        )
        return
    if len(accs) > 1:
        await message.answer(
            "Bir nechta akkaunt: «📢 Xabar» bo'limidan akkaunt tanlang.",
            reply_markup=main_menu(message.from_user.id),
        )
        return
    await state.update_data(campaign_account_id=str(accs[0].id))
    await state.set_state(CampaignStates.message_text)
    await message.answer("Yuboriladigan xabar matnini yuboring:")


@router.message(CampaignStates.message_text, F.text)
async def campaign_message(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    data_pre = await state.get_data()
    raw_aid = data_pre.get("campaign_account_id")
    try:
        acc_uuid = uuid.UUID(str(raw_aid)) if raw_aid else None
    except ValueError:
        acc_uuid = None
    if not acc_uuid:
        await state.clear()
        await message.answer("«📢 Xabar»dan qayta kiring.", reply_markup=main_menu(message.from_user.id))
        return
    await state.update_data(message_text=message.text.strip())
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        groups = list(
            db.execute(
                select(Group)
                .where(Group.user_id == u.id, Group.account_id == acc_uuid)
                .order_by(Group.created_at)
            )
            .scalars()
            .all()
        )
    finally:
        db.close()

    if groups:
        await state.update_data(sel_groups=[])
        await state.set_state(CampaignStates.select_groups)
        await message.answer(
            "Yuborish uchun guruhlarni belgilang (✅), keyin «Davom etish».\n"
            "Nomlar bazadan olinadi; nom bo'lmasa chat ID ko'rinadi.",
            reply_markup=groups_pick_kb(groups, set()),
        )
    else:
        await state.set_state(CampaignStates.chat_ids)
        await message.answer(
            "Hozircha saqlangan guruh yo'q. Chat ID larni vergul bilan yuboring.\n"
            "Masalan: -1001234567890,-1009876543210\n"
            "(Guruhda userbot akkaunt bo'lishi kerak.)"
        )


@router.callback_query(CampaignStates.select_groups, F.data == "grp:invalid")
async def cb_group_invalid(query: CallbackQuery) -> None:
    await query.answer("Bu guruh faol emas (xatolik yuz bergan)", show_alert=True)


@router.callback_query(CampaignStates.select_groups, F.data.startswith("grp:t:"))
async def cb_group_toggle(query: CallbackQuery, state: FSMContext) -> None:
    if query.message is None:
        await query.answer()
        return
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        await query.answer()
        return
    gid = parts[2]
    data = await state.get_data()
    sel = set(data.get("sel_groups") or [])
    if gid in sel:
        sel.remove(gid)
    else:
        sel.add(gid)
    await state.update_data(sel_groups=list(sel))
    raw_aid = data.get("campaign_account_id")
    try:
        acc_uuid = uuid.UUID(str(raw_aid)) if raw_aid else None
    except ValueError:
        acc_uuid = None
    if not acc_uuid:
        await query.answer("Sessiya buzildi", show_alert=True)
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, query.from_user.id)
        if not u:
            await query.answer("Sessiya yo'q", show_alert=True)
            return
        groups = list(
            db.execute(
                select(Group)
                .where(Group.user_id == u.id, Group.account_id == acc_uuid)
                .order_by(Group.created_at)
            )
            .scalars()
            .all()
        )
    finally:
        db.close()
    await query.message.edit_reply_markup(reply_markup=groups_pick_kb(groups, sel))
    await query.answer()


@router.callback_query(CampaignStates.select_groups, F.data == "grp:manual")
async def cb_group_manual(query: CallbackQuery, state: FSMContext) -> None:
    if query.message is None:
        await query.answer()
        return
    await state.set_state(CampaignStates.chat_ids)
    await query.message.edit_text(
        "Guruhlar: har bir chat ID ni vergul bilan yuboring.\n"
        "Masalan: -1001234567890,-1009876543210\n"
        "(Guruhda userbot akkaunt bo'lishi kerak.)"
    )
    await query.answer()


@router.callback_query(CampaignStates.select_groups, F.data == "grp:go")
async def cb_group_go(query: CallbackQuery, state: FSMContext) -> None:
    if query.message is None:
        await query.answer()
        return
    data = await state.get_data()
    sel = data.get("sel_groups") or []
    if not sel:
        await query.answer("Kamida bitta guruhni tanlang", show_alert=True)
        return
    await state.update_data(group_ids=sel)
    await state.set_state(CampaignStates.interval)
    await query.message.edit_text("Guruhlar tanlandi.")
    await query.message.answer("Intervalni tanlang:", reply_markup=intervals_kb())
    await query.answer()


@router.message(CampaignStates.chat_ids, F.text)
async def campaign_chats(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    parts = [p.strip() for p in message.text.split(",") if p.strip()]
    chats: list[int] = []
    for p in parts:
        try:
            chats.append(int(p))
        except ValueError:
            await message.answer("Noto'g'ri format. Qayta yuboring.")
            return

    data_st = await state.get_data()
    raw_aid = data_st.get("campaign_account_id")
    try:
        acc_uuid = uuid.UUID(str(raw_aid)) if raw_aid else None
    except ValueError:
        acc_uuid = None
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        if not acc_uuid:
            await message.answer("Sessiya buzildi. Qaytadan «📢 Xabar».")
            return
        acc = db.get(Account, acc_uuid)
        if not acc or acc.user_id != u.id:
            await message.answer("Akkaunt topilmadi.")
            return
        gids = campaign_service.ensure_groups_for_account(db, u, acc, chats)
        db.commit()
    except Exception:
        db.rollback()
        await message.answer("Xato.")
        return
    finally:
        db.close()

    from worker.tasks import sync_group_titles_task

    sync_group_titles_task.delay([str(x) for x in gids])
    await state.update_data(group_ids=[str(x) for x in gids])
    await state.set_state(CampaignStates.interval)
    await message.answer("Intervalni tanlang:", reply_markup=intervals_kb())


@router.message(CampaignStates.interval, F.text)
async def campaign_interval(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    iv = _parse_interval(message.text or "")
    if iv is None:
        await message.answer("Tugmalardan birini tanlang.")
        return
    data = await state.get_data()
    raw_aid = data.get("campaign_account_id")
    try:
        acc_uuid = uuid.UUID(str(raw_aid)) if raw_aid else None
    except ValueError:
        acc_uuid = None
    await state.clear()

    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("Foydalanuvchi topilmadi. /start")
            return
        if not acc_uuid:
            await message.answer("Sessiya buzildi.", reply_markup=main_menu(message.from_user.id))
            return
        gids_raw = data.get("group_ids")
        if not gids_raw:
            await message.answer(
                f"Guruhlar tanlanmagan. Qaytadan «{BTN_CREATE_CAMPAIGN}».",
                reply_markup=main_menu(message.from_user.id),
            )
            return
        gids = [uuid.UUID(x) for x in gids_raw]
        campaign_service.delete_all_campaigns_for_account(db, u, acc_uuid)
        c = campaign_service.create_campaign(
            db,
            u,
            acc_uuid,
            "Xabar",
            data["message_text"],
            iv,
            gids,
        )
        s, _paused = campaign_service.start_campaign(db, c)
        groups_for = list(db.execute(select(Group).where(Group.id.in_(gids))).scalars().all())
        await refresh_group_titles_from_bot(message.bot, db, groups_for)
        labels = [group_display_label(g.telegram_chat_id, g.title) for g in groups_for]
        next_local = format_local_datetime(s.next_run_at)
        block = "\n".join(f"• {x}" for x in labels) if labels else "—"
        db.commit()
        await message.answer(
            "✅ Xabarlar avtomatik yuborish ishga tushdi.\n\n"
            f"👥 Guruhlar:\n{block}\n\n"
            f"⏱ Keyingi yuborish: {next_local} (Toshkent)",
            reply_markup=main_menu(message.from_user.id),
        )
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}", reply_markup=main_menu(message.from_user.id))
    finally:
        db.close()


@router.message(F.text == BTN_STATUS)
async def status_cmd(message: Message) -> None:
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        camps = campaign_service.list_user_campaigns(db, u.id)
        lines = [f"Xabarlar (faol yozuvlar): {len(camps)}"]
        for c in camps[:10]:
            sch = db.execute(select(Schedule).where(Schedule.campaign_id == c.id)).scalar_one_or_none()
            nra = format_local_datetime(sch.next_run_at) if sch else "-"
            st = campaign_totals(db, c.id)
            lines.append(
                f"- {str(c.id)[:8]}… holat={c.status} keyingi={nra} ok={st.get('success',0)}/{st.get('total',0)}"
            )
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(F.text == BTN_STOP)
async def stop_cmd(message: Message) -> None:
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        camps = db.execute(select(Campaign).where(Campaign.user_id == u.id, Campaign.status == "running")).scalars().all()
        for c in camps:
            campaign_service.stop_campaign(db, c)
        db.commit()
        await message.answer(
            f"{len(camps)} ta xabar oqimi to'xtatildi.",
            reply_markup=main_menu(message.from_user.id),
        )
    finally:
        db.close()


@router.message(F.text == BTN_ACCOUNT)
async def link_account(message: Message, state: FSMContext) -> None:
    await state.set_state(LoginStates.phone)
    await message.answer("Telefon raqamingizni xalqaro formatda yuboring: +998901234567")


@router.message(LoginStates.phone, F.text)
async def login_phone(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()
    if not phone.startswith("+"):
        await message.answer("+ bilan boshlang.")
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        acc = Account(user_id=u.id, status="pending_login", phone=phone)
        db.add(acc)
        db.flush()
        aid = str(acc.id)
        await state.update_data(account_id=aid, phone=phone)
        db.commit()
    except Exception:
        db.rollback()
        await message.answer("Xato.")
        return
    finally:
        db.close()

    from worker.tasks import send_login_code_task

    data = await state.get_data()
    send_login_code_task.delay(data["account_id"], phone)
    await state.set_state(LoginStates.code)
    await message.answer("Telegramdan kelgan kodni yuboring.")


@router.message(LoginStates.code, F.text)
async def login_code(message: Message, state: FSMContext) -> None:
    code = message.text.strip()
    data = await state.get_data()
    await state.clear()
    acc_id = data.get("account_id")
    phone = data.get("phone")
    if not acc_id or not phone:
        await message.answer(f"Sessiya buzildi. Qaytadan «{BTN_ACCOUNT}».")
        return

    from worker.tasks import complete_login_task

    complete_login_task.delay(acc_id, phone, code)
    await message.answer(
        "Kod qabul qilindi. Bir necha soniyadan keyin akkaunt faollashadi.",
        reply_markup=main_menu(message.from_user.id),
    )
