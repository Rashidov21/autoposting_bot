from __future__ import annotations

import re
import uuid

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from sqlalchemy import select

from app.db.models import Campaign, Group
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import users as user_service
from bot.handlers.user import (
    execute_stop_answer,
    send_campaign_status,
    send_tutorial_video_message,
)
from bot.keyboards import groups_inline_kb, intervals_kb, main_menu
from bot.messages import (
    BTN_CAMPAIGN,
    BTN_CANCEL,
    BTN_HELP,
    BTN_STATUS,
    BTN_STOP,
    BTN_TARIFF,
    BTN_VIDEO,
    MAIN_MENU_TEXTS,
    MSG_CAMPAIGN_NAME_DEFAULT,
    MSG_CAMPAIGN_OLD_PAUSED,
    MSG_CAMPAIGN_PROMPT_TEXT,
    MSG_CAMPAIGN_STARTED,
    MSG_ENTER_GROUP_CHAT_ID,
    MSG_FSM_SWITCH_MENU,
    MSG_GROUP_ADDED,
    MSG_GROUPS_EMPTY,
    MSG_GROUPS_NONE_SELECTED,
    MSG_GROUPS_SELECT,
    MSG_INTERVAL_PROMPT,
    MSG_XABAR_EDIT_GROUPS_DONE,
    MSG_XABAR_EDIT_INTERVAL_DONE,
    MSG_XABAR_EDIT_TEXT_DONE,
    MSG_XABAR_EDIT_TEXT_PROMPT,
    MSG_XABAR_PANEL_CAPTION,
)
from bot.states import CampaignStates

router = Router(name="campaign")


def _status_uz(status: str) -> str:
    return {
        "running": "ishlamoqda",
        "draft": "qoralama",
        "paused": "to'xtatilgan",
    }.get(status, status)


def _xabar_panel_kb(cid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Matn", callback_data=f"xab:txt:{cid}"),
                InlineKeyboardButton(text="⏱ Interval", callback_data=f"xab:int:{cid}"),
            ],
            [InlineKeyboardButton(text="👥 Guruhlar", callback_data=f"xab:grp:{cid}")],
            [InlineKeyboardButton(text="🆕 Yangi xabar (eski o'chadi)", callback_data=f"xab:new:{cid}")],
            [InlineKeyboardButton(text="🏠 Bosh menyuga", callback_data="xab:home")],
        ]
    )


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


async def _fsm_main_menu_switch(message: Message, state: FSMContext) -> bool:
    """Agar foydalanuvchi bosh menyudan tugma bossa — FSM dan chiqish."""
    t = (message.text or "").strip()
    if t not in MAIN_MENU_TEXTS or t == BTN_CANCEL:
        return False
    await state.clear()
    if t == BTN_VIDEO:
        await send_tutorial_video_message(message)
        return True
    if t == BTN_HELP:
        from bot.messages import MSG_HELP

        await message.answer(MSG_HELP, reply_markup=main_menu(message.from_user.id))
        return True
    if t == BTN_STATUS:
        await send_campaign_status(message, message.from_user.id)
        return True
    if t == BTN_STOP:
        await execute_stop_answer(message)
        return True
    if t == BTN_CAMPAIGN:
        await message.answer(
            "📢 Xabar bo'limi: pastdagi tugmani qayta bosing yoki «Bekor qilish».",
            reply_markup=main_menu(message.from_user.id),
        )
        return True
    if t == BTN_TARIFF:
        await message.answer(
            "💳 Tarif: «Tarif va to'lov» tugmasini qayta bosing.",
            reply_markup=main_menu(message.from_user.id),
        )
        return True
    await message.answer(MSG_FSM_SWITCH_MENU, reply_markup=main_menu(message.from_user.id))
    return True


@router.message(F.text == BTN_CAMPAIGN)
async def xabar_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        camps = campaign_service.list_user_campaigns(db, u.id)
    finally:
        db.close()

    if not camps:
        await state.set_state(CampaignStates.message_text)
        await message.answer(
            MSG_CAMPAIGN_PROMPT_TEXT,
            reply_markup=main_menu(message.from_user.id),
        )
        return

    prim = next((x for x in camps if x.status == "running"), None) or camps[0]
    cid = str(prim.id)
    raw = (prim.message_text or "").strip()
    preview = raw[:400] + ("…" if len(raw) > 400 else "")
    extra = ""
    if len(camps) > 1:
        extra = f"\n\nℹ️ Jami {len(camps)} ta xabar. Boshqalari: «{BTN_STATUS}»."
    text = (
        f"{MSG_XABAR_PANEL_CAPTION}{extra}\n\n"
        f"📝 Matn (boshlanishi):\n{preview or '—'}\n\n"
        f"⏱ Interval: {prim.interval_minutes} daq · Holat: {_status_uz(prim.status)}"
    )
    await message.answer(text, reply_markup=_xabar_panel_kb(cid))


@router.callback_query(F.data.startswith("xab:txt:"))
async def xab_txt_start(callback: CallbackQuery, state: FSMContext) -> None:
    cid = _uuid_from_cb("xab:txt:", callback.data)
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
    finally:
        db.close()
    await state.set_state(CampaignStates.editing_text)
    await state.update_data(edit_campaign_id=str(cid))
    await callback.message.answer(
        MSG_XABAR_EDIT_TEXT_PROMPT,
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("xab:int:"))
async def xab_int_start(callback: CallbackQuery, state: FSMContext) -> None:
    cid = _uuid_from_cb("xab:int:", callback.data)
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
    finally:
        db.close()
    await state.set_state(CampaignStates.editing_interval)
    await state.update_data(edit_campaign_id=str(cid))
    await callback.message.answer(MSG_INTERVAL_PROMPT, reply_markup=intervals_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("xab:grp:"))
async def xab_grp_start(callback: CallbackQuery, state: FSMContext) -> None:
    cid = _uuid_from_cb("xab:grp:", callback.data)
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
        gids = campaign_service.list_campaign_group_ids(db, cid)
    finally:
        db.close()
    await state.set_state(CampaignStates.select_groups)
    await state.update_data(
        editing_campaign_id=str(cid),
        selected_group_ids=[str(x) for x in gids],
        message_text="",
    )
    await _send_groups_prompt(callback.message, state, u.id)
    await callback.answer()


@router.callback_query(F.data.startswith("xab:new:"))
async def xab_new_start(callback: CallbackQuery, state: FSMContext) -> None:
    cid = _uuid_from_cb("xab:new:", callback.data)
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
        campaign_service.delete_all_campaigns_for_user(db, u)
        db.commit()
    except Exception as e:
        db.rollback()
        await callback.answer(str(e)[:120], show_alert=True)
        return
    finally:
        db.close()
    await state.clear()
    await state.set_state(CampaignStates.message_text)
    await callback.message.answer(
        MSG_CAMPAIGN_PROMPT_TEXT,
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "xab:home")
async def xab_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "🏠 Bosh menyu.",
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@router.message(CampaignStates.editing_text, F.text)
async def save_edited_text(message: Message, state: FSMContext) -> None:
    if await _fsm_main_menu_switch(message, state):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    data = await state.get_data()
    raw = data.get("edit_campaign_id")
    if not raw:
        await state.clear()
        return
    try:
        cid = uuid.UUID(raw)
    except ValueError:
        await state.clear()
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            await state.clear()
            return
        c = db.get(Campaign, cid)
        if not c or c.user_id != u.id:
            await message.answer("Topilmadi.")
            await state.clear()
            return
        campaign_service.update_campaign_message_text(db, c, message.text.strip())
        db.commit()
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}")
        return
    finally:
        db.close()
    await state.clear()
    await message.answer(MSG_XABAR_EDIT_TEXT_DONE, reply_markup=main_menu(message.from_user.id))


@router.message(CampaignStates.editing_interval, F.text)
async def save_edited_interval(message: Message, state: FSMContext) -> None:
    if await _fsm_main_menu_switch(message, state):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    iv = _parse_interval(message.text or "")
    if iv is None:
        await message.answer("Tugmalardan birini tanlang.")
        return
    data = await state.get_data()
    raw = data.get("edit_campaign_id")
    if not raw:
        await state.clear()
        return
    try:
        cid = uuid.UUID(raw)
    except ValueError:
        await state.clear()
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            await state.clear()
            return
        c = db.get(Campaign, cid)
        if not c or c.user_id != u.id:
            await message.answer("Topilmadi.")
            await state.clear()
            return
        campaign_service.update_campaign_interval_minutes(db, c, iv)
        db.commit()
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}")
        return
    finally:
        db.close()
    await state.clear()
    await message.answer(MSG_XABAR_EDIT_INTERVAL_DONE, reply_markup=main_menu(message.from_user.id))


@router.message(CampaignStates.message_text, F.text)
async def campaign_message(message: Message, state: FSMContext) -> None:
    if await _fsm_main_menu_switch(message, state):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu(message.from_user.id))
        return
    await state.update_data(message_text=message.text.strip())
    await state.set_state(CampaignStates.select_groups)
    await state.update_data(selected_group_ids=[], editing_campaign_id=None)
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
    await callback.message.answer(MSG_ENTER_GROUP_CHAT_ID, reply_markup=main_menu(callback.from_user.id))
    await callback.answer()


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data == "grp:cancel")
async def grp_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("editing_campaign_id"):
        await callback.message.answer(
            "Guruhlar tahriri bekor qilindi.",
            reply_markup=main_menu(callback.from_user.id),
        )
    else:
        await callback.message.answer("Bekor qilindi.", reply_markup=main_menu(callback.from_user.id))
    await callback.answer()


@router.callback_query(StateFilter(CampaignStates.select_groups), F.data == "grp:done")
async def grp_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    sel = data.get("selected_group_ids") or []
    if not sel:
        await callback.answer(MSG_GROUPS_NONE_SELECTED, show_alert=True)
        return
    edit_id = data.get("editing_campaign_id")
    if edit_id:
        try:
            cid_u = uuid.UUID(edit_id)
        except ValueError:
            await callback.answer("Xato")
            return
        db = SessionLocal()
        try:
            u = user_service.get_by_telegram_id(db, callback.from_user.id)
            if not u:
                await callback.answer("/start")
                return
            c = db.get(Campaign, cid_u)
            if not c or c.user_id != u.id:
                await callback.answer("Topilmadi", show_alert=True)
                return
            gids = [uuid.UUID(x) for x in sel]
            campaign_service.replace_campaign_groups(db, c, gids)
            db.commit()
        except Exception as e:
            db.rollback()
            await callback.answer(str(e)[:120], show_alert=True)
            return
        finally:
            db.close()
        await state.clear()
        await callback.message.answer(
            MSG_XABAR_EDIT_GROUPS_DONE,
            reply_markup=main_menu(callback.from_user.id),
        )
        await callback.answer()
        return

    await state.set_state(CampaignStates.interval)
    await callback.message.answer(MSG_INTERVAL_PROMPT, reply_markup=intervals_kb())
    await callback.answer()


@router.message(CampaignStates.enter_group_chat_id, F.text)
async def grp_chat_id_enter(message: Message, state: FSMContext) -> None:
    if await _fsm_main_menu_switch(message, state):
        return
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
    if await _fsm_main_menu_switch(message, state):
        return
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
