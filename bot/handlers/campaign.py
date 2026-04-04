from __future__ import annotations

import re
import uuid

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from sqlalchemy import select

from app.db.models import Campaign, Group
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import users as user_service
from bot.keyboards import groups_inline_kb, intervals_kb, main_menu
from bot.messages import (
    BTN_CAMPAIGN,
    BTN_CANCEL,
    MSG_CAMPAIGN_NAME_DEFAULT,
    MSG_CAMPAIGN_OLD_PAUSED,
    MSG_CAMPAIGN_PROMPT_TEXT,
    MSG_CAMPAIGN_STARTED,
    MSG_ENTER_GROUP_CHAT_ID,
    MSG_GROUP_ADDED,
    MSG_GROUPS_EMPTY,
    MSG_GROUPS_NONE_SELECTED,
    MSG_GROUPS_SELECT,
    MSG_INTERVAL_PROMPT,
)
from bot.states import CampaignStates

router = Router(name="campaign")


def _parse_interval(text: str) -> int | None:
    m = re.search(r"(\d+)\s*daqiqa", text.strip(), re.I)
    if not m:
        return None
    v = int(m.group(1))
    return v if v in (3, 5, 10, 15) else None


def _group_rows(
    groups: list[Group],
    selected: set[str],
) -> list[tuple[str, str, bool]]:
    rows: list[tuple[str, str, bool]] = []
    for g in groups:
        gid = str(g.id)
        label = (g.title or str(g.telegram_chat_id))[:60]
        rows.append((gid, label, gid in selected))
    return rows


async def _send_groups_prompt(message: Message, state: FSMContext, user_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        groups = list(
            db.execute(
                select(Group).where(Group.user_id == user_id).order_by(Group.created_at.desc())
            )
            .scalars()
            .all()
        )
    finally:
        db.close()
    data = await state.get_data()
    sel = set(data.get("selected_group_ids") or [])
    rows = _group_rows(groups, sel)
    text = MSG_GROUPS_SELECT if groups else MSG_GROUPS_EMPTY
    await message.answer(text, reply_markup=groups_inline_kb(rows))


@router.message(F.text == BTN_CAMPAIGN)
async def start_campaign(message: Message, state: FSMContext) -> None:
    await state.set_state(CampaignStates.message_text)
    await message.answer(MSG_CAMPAIGN_PROMPT_TEXT)


@router.message(CampaignStates.message_text, F.text)
async def campaign_message(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    await state.update_data(message_text=message.text.strip())
    await state.set_state(CampaignStates.select_groups)
    await state.update_data(selected_group_ids=[])
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            await state.clear()
            return
        uid = u.id
    finally:
        db.close()
    await _send_groups_prompt(message, state, uid)


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data.startswith("grp:tog:"))
async def grp_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").replace("grp:tog:", "", 1)
    try:
        gid_str = raw
        uuid.UUID(gid_str)
    except ValueError:
        await callback.answer("Xato")
        return
    data = await state.get_data()
    sel = set(data.get("selected_group_ids") or [])
    if gid_str in sel:
        sel.discard(gid_str)
    else:
        sel.add(gid_str)
    await state.update_data(selected_group_ids=list(sel))

    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, callback.from_user.id)
        if not u:
            await callback.answer("/start")
            return
        groups = list(
            db.execute(
                select(Group).where(Group.user_id == u.id).order_by(Group.created_at.desc())
            )
            .scalars()
            .all()
        )
    finally:
        db.close()
    rows = _group_rows(groups, sel)
    text = MSG_GROUPS_SELECT if groups else MSG_GROUPS_EMPTY
    await callback.message.edit_text(text, reply_markup=groups_inline_kb(rows))
    await callback.answer()


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data == "grp:add")
async def grp_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CampaignStates.enter_group_chat_id)
    await callback.message.answer(MSG_ENTER_GROUP_CHAT_ID)
    await callback.answer()


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data == "grp:cancel")
async def grp_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Bekor qilindi.", reply_markup=main_menu(callback.from_user.id))
    await callback.answer()


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data == "grp:done")
async def grp_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    sel = data.get("selected_group_ids") or []
    if not sel:
        await callback.answer(MSG_GROUPS_NONE_SELECTED, show_alert=True)
        return
    await state.set_state(CampaignStates.interval)
    await callback.message.answer(MSG_INTERVAL_PROMPT, reply_markup=intervals_kb())
    await callback.answer()


@router.message(CampaignStates.enter_group_chat_id, F.text)
async def grp_chat_id_enter(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    try:
        cid = int(message.text.strip())
    except ValueError:
        await message.answer("Chat ID butun son bo'lishi kerak (masalan -100...).")
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            await state.clear()
            return
        gids = campaign_service.ensure_groups_for_user(db, u, [cid])
        db.commit()
        new_id = str(gids[0])
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}")
        return
    finally:
        db.close()

    data = await state.get_data()
    sel = set(data.get("selected_group_ids") or [])
    sel.add(new_id)
    await state.update_data(selected_group_ids=list(sel))
    await state.set_state(CampaignStates.select_groups)
    await message.answer(MSG_GROUP_ADDED)
    db2 = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db2, message.from_user.id)
        uid = u.id if u else None
    finally:
        db2.close()
    if uid:
        await _send_groups_prompt(message, state, uid)


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
    await state.clear()

    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("Foydalanuvchi topilmadi. /start")
            return
        gids = [uuid.UUID(x) for x in (data.get("selected_group_ids") or [])]
        if not gids:
            await message.answer("Guruh tanlanmagan.", reply_markup=main_menu(message.from_user.id))
            return
        c = campaign_service.create_campaign(
            db,
            u,
            MSG_CAMPAIGN_NAME_DEFAULT,
            data["message_text"],
            iv,
            gids,
        )
        s, paused_n = campaign_service.start_campaign(db, c)
        db.commit()
        extra = ""
        if paused_n > 0:
            extra = "\n\n" + MSG_CAMPAIGN_OLD_PAUSED
        await message.answer(
            f"{MSG_CAMPAIGN_STARTED}{extra}\n\n"
            f"ID: `{c.id}`\nKeyingi ish: {s.next_run_at.isoformat()}",
            parse_mode="Markdown",
            reply_markup=main_menu(message.from_user.id),
        )
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}", reply_markup=main_menu(message.from_user.id))
    finally:
        db.close()


def _uuid_from_cb(prefix: str, data: str | None) -> uuid.UUID | None:
    if not data or not data.startswith(prefix):
        return None
    raw = data[len(prefix) :].strip()
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


@router.callback_query(F.data.startswith("camp:pause:"))
async def camp_pause_cb(callback: CallbackQuery) -> None:
    cid = _uuid_from_cb("camp:pause:", callback.data)
    if not cid:
        await callback.answer("Xato")
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, callback.from_user.id)
        if not u:
            await callback.answer("/start")
            return
        c = db.get(Campaign, cid)
        if not c or c.user_id != u.id:
            await callback.answer("Topilmadi", show_alert=True)
            return
        campaign_service.stop_campaign(db, c)
        db.commit()
    finally:
        db.close()
    await callback.answer("⏹ Pauzaga olindi")


@router.callback_query(F.data.startswith("camp:resume:"))
async def camp_resume_cb(callback: CallbackQuery) -> None:
    cid = _uuid_from_cb("camp:resume:", callback.data)
    if not cid:
        await callback.answer("Xato")
        return
    paused_n = 0
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, callback.from_user.id)
        if not u:
            await callback.answer("/start")
            return
        c = db.get(Campaign, cid)
        if not c or c.user_id != u.id:
            await callback.answer("Topilmadi", show_alert=True)
            return
        _s, paused_n = campaign_service.start_campaign(db, c)
        db.commit()
    except Exception as e:
        db.rollback()
        await callback.answer(str(e)[:200], show_alert=True)
        return
    finally:
        db.close()
    extra = ""
    if paused_n > 0:
        extra = "\n" + MSG_CAMPAIGN_OLD_PAUSED
    await callback.answer(f"▶️ Ishga tushdi{extra}", show_alert=True)
