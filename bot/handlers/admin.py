from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db.models import Group, User
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import subscription as subscription_service
from app.services import system as system_service
from app.services import users as user_service
from bot.filters import admin_only_callback, admin_only_message
from bot.messages import (
    BTN_ADMIN,
    MSG_ADMIN_BOT_DISABLED,
    MSG_ADMIN_BOT_ENABLED,
    MSG_ADMIN_MENU,
    MSG_PAYMENT_ALREADY_RESOLVED,
    MSG_PAYMENT_APPROVE_OK,
    MSG_PAYMENT_APPROVED,
    MSG_PAYMENT_REJECT_OK,
    MSG_PAYMENT_REJECTED,
    MSG_VIDEO_SAVED,
)
from bot.states import AdminStates

router = Router(name="admin")
router.message.filter(admin_only_message)
router.callback_query.filter(admin_only_callback)

USERS_PAGE = 8
ADMIN_GROUPS_PAGE = 8


def _fmt_subscription_line(u: User) -> str:
    if u.subscription_ends_at is None:
        return "obuna yo'q"
    now = datetime.now(timezone.utc)
    ends = u.subscription_ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    if ends > now:
        return ends.strftime("%d.%m.%Y %H:%M") + " gacha"
    return "muddati tugagan"


def _admin_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin:users:0")],
            [InlineKeyboardButton(text="💰 Kutilayotgan to'lovlar", callback_data="admin:paylist")],
            [
                InlineKeyboardButton(text="⛔ Bot OFF", callback_data="admin:bot:off"),
                InlineKeyboardButton(text="✅ Bot ON", callback_data="admin:bot:on"),
            ],
            [InlineKeyboardButton(text="🎬 Video yangilash", callback_data="admin:video")],
        ]
    )


async def send_admin_home(message: Message) -> None:
    await message.answer(MSG_ADMIN_MENU, reply_markup=_admin_home_kb())


async def _edit_or_answer(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _render_users_page(callback: CallbackQuery, page: int) -> None:
    offset = page * USERS_PAGE
    db = SessionLocal()
    try:
        rows, total = subscription_service.list_users_paginated(db, offset, USERS_PAGE)
    finally:
        db.close()

    lines: list[str] = []
    buttons: list[list[InlineKeyboardButton]] = []
    for u in rows:
        un = html.escape(u.username or "—")
        fn = html.escape((u.full_name or "").strip() or "—")
        sub = html.escape(_fmt_subscription_line(u))
        ps = html.escape(u.payment_status or "none")
        lines.append(
            f"🆔 <code>{u.telegram_id}</code>\n"
            f"👤 @{un} · {fn}\n"
            f"📅 {sub} · 💳 {ps} · {'🚫' if u.is_blocked else '✅'}"
        )
        blk = "🔓 Blokdan chiqarish" if u.is_blocked else "🔒 Bloklash"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=blk,
                    callback_data=f"admin:blk:{u.id}:{page}",
                ),
                InlineKeyboardButton(
                    text="👥 Guruhlar (DB)",
                    callback_data=f"admin:ugrps:{u.id}:0",
                ),
            ]
        )

    head = f"<b>👥 Foydalanuvchilar</b> (jami {total}, sahifa {page + 1})\n\n"
    body = "\n\n".join(lines) if lines else "<i>Ro'yxat bo'sh</i>"
    text = head + body

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"admin:users:{page - 1}"))
    if offset + len(rows) < total:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"admin:users:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ Admin boshqaruv", callback_data="admin:home")])

    await _edit_or_answer(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


async def _render_user_groups_admin(
    callback: CallbackQuery,
    user_id: uuid.UUID,
    page: int,
) -> None:
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        groups = campaign_service.list_groups_for_user(db, user_id) if u else []
    finally:
        db.close()

    if not u:
        await _edit_or_answer(
            callback,
            "<b>Foydalanuvchi topilmadi.</b>",
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Foydalanuvchilar", callback_data="admin:users:0")]]
            ),
        )
        return

    total = len(groups)
    offset = page * ADMIN_GROUPS_PAGE
    chunk = groups[offset : offset + ADMIN_GROUPS_PAGE]

    lines: list[str] = []
    buttons: list[list[InlineKeyboardButton]] = []
    un = html.escape(u.username or "—")
    head = (
        f"<b>👥 Guruhlar (DB)</b>\n"
        f"🆔 TG: <code>{u.telegram_id}</code> · @{un}\n"
        f"Jami: {total}\n\n"
    )

    for g in chunk:
        tid = g.telegram_chat_id
        title = html.escape((g.title or "").strip() or "—")
        gid_short = str(g.id).split("-")[0]
        lines.append(
            f"📌 <code>{gid_short}…</code>\n"
            f"Chat ID: <code>{tid}</code>\n"
            f"Nom: {title} · {'✅' if g.is_valid else '⚠️'}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 O'chirish · {gid_short}…",
                    callback_data=f"admin:grpdel:{g.id}",
                )
            ]
        )

    body = "\n\n".join(lines) if lines else "<i>Guruh yo'q.</i>"
    text = head + body

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin:ugrps:{user_id}:{page - 1}"))
    if offset + len(chunk) < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin:ugrps:{user_id}:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ Foydalanuvchilar", callback_data="admin:users:0")])

    await _edit_or_answer(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(F.text == BTN_ADMIN)
async def cmd_admin_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_admin_home(message)


@router.callback_query(F.data == "admin:home")
async def admin_home_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_text(MSG_ADMIN_MENU, reply_markup=_admin_home_kb())
    except TelegramBadRequest:
        await callback.message.answer(MSG_ADMIN_MENU, reply_markup=_admin_home_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ugrps:"))
async def admin_user_groups_page(callback: CallbackQuery) -> None:
    raw = (callback.data or "").replace("admin:ugrps:", "", 1)
    try:
        uid_str, page_str = raw.rsplit(":", 1)
        uid = uuid.UUID(uid_str.strip())
        page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Xato")
        return
    await _render_user_groups_admin(callback, uid, page)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:grpdel:"))
async def admin_group_delete(callback: CallbackQuery) -> None:
    raw = (callback.data or "").replace("admin:grpdel:", "", 1).strip()
    try:
        gid = uuid.UUID(raw)
    except ValueError:
        await callback.answer("Xato")
        return
    db = SessionLocal()
    uid: uuid.UUID | None = None
    try:
        g = db.get(Group, gid)
        if not g:
            await callback.answer("Topilmadi", show_alert=True)
            return
        uid = g.user_id
        if not campaign_service.delete_group_by_id(db, gid):
            await callback.answer("Xato", show_alert=True)
            return
        db.commit()
    except Exception as e:
        db.rollback()
        await callback.answer(str(e)[:120], show_alert=True)
        return
    finally:
        db.close()
    await callback.answer("DB dan o'chirildi")
    if uid:
        await _render_user_groups_admin(callback, uid, 0)


@router.callback_query(F.data.startswith("admin:users:"))
async def admin_users_page(callback: CallbackQuery) -> None:
    raw = (callback.data or "").split(":")[-1]
    try:
        page = int(raw)
    except ValueError:
        page = 0
    await _render_users_page(callback, page)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:blk:"))
async def admin_block_toggle(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer("Xato")
        return
    try:
        uid = uuid.UUID(parts[2])
        page = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Xato")
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_id(db, uid)
        if not u:
            await callback.answer("Topilmadi", show_alert=True)
            return
        new_blocked = not u.is_blocked
        user_service.block_user(db, uid, new_blocked)
        db.commit()
    finally:
        db.close()
    await callback.answer("OK")
    await _render_users_page(callback, page)


@router.callback_query(F.data == "admin:paylist")
async def admin_paylist(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        pending = subscription_service.list_pending_payment_requests(db, limit=20)
    finally:
        db.close()

    if not pending:
        await _edit_or_answer(
            callback,
            "<b>💰 Kutilayotgan to'lovlar</b>\n\n<i>Hozircha yo'q.</i>",
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")]]
            ),
        )
        await callback.answer()
        return

    lines: list[str] = []
    buttons: list[list[InlineKeyboardButton]] = []
    for pr in pending:
        usr = pr.user
        un = html.escape(usr.username or "—") if usr else "—"
        fn = html.escape((usr.full_name or "").strip() or "—") if usr else "—"
        tg = usr.telegram_id if usr else "—"
        phone = html.escape((pr.contact_phone or "").strip() or "—")
        lines.append(
            f"🔖 <code>{pr.id}</code> · {pr.tariff_months} oy\n"
            f"🆔 TG: <code>{tg}</code> · 👤 @{un}\n"
            f"📝 {fn}\n"
            f"📞 {phone}"
        )
        pid = str(pr.id)
        buttons.append(
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin:pay:{pid}:ok"),
                InlineKeyboardButton(text="❌ Rad", callback_data=f"admin:pay:{pid}:no"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")])
    text = "<b>💰 Kutilayotgan to'lovlar</b>\n\n" + "\n\n".join(lines)
    await _edit_or_answer(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:pay:"))
async def admin_pay_resolve(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    try:
        pr_id = uuid.UUID(parts[2])
    except ValueError:
        await callback.answer("Xato")
        return
    action = parts[3]
    user = None
    db = SessionLocal()
    try:
        if action == "ok":
            pr = subscription_service.approve_payment(db, pr_id, callback.from_user.id)
        else:
            pr = subscription_service.reject_payment(db, pr_id, callback.from_user.id)
        if not pr:
            await callback.answer(MSG_PAYMENT_ALREADY_RESOLVED, show_alert=True)
            return
        user = user_service.get_by_id(db, pr.user_id)
        db.commit()
    except Exception as e:
        db.rollback()
        await callback.answer(str(e)[:200], show_alert=True)
        return
    finally:
        db.close()

    if user:
        try:
            if action == "ok":
                await callback.bot.send_message(user.telegram_id, MSG_PAYMENT_APPROVED)
            else:
                await callback.bot.send_message(user.telegram_id, MSG_PAYMENT_REJECTED)
        except Exception:
            pass

    await callback.answer(MSG_PAYMENT_APPROVE_OK if action == "ok" else MSG_PAYMENT_REJECT_OK)


@router.callback_query(F.data == "admin:bot:off")
async def admin_bot_off(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        system_service.set_bot_enabled(db, False)
        db.commit()
    finally:
        db.close()
    await callback.answer(MSG_ADMIN_BOT_DISABLED, show_alert=True)


@router.callback_query(F.data == "admin:bot:on")
async def admin_bot_on(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        system_service.set_bot_enabled(db, True)
        db.commit()
    finally:
        db.close()
    await callback.answer(MSG_ADMIN_BOT_ENABLED, show_alert=True)


@router.callback_query(F.data == "admin:video")
async def admin_video_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_video)
    await callback.message.answer("🎬 Video qo'llanmani yuboring (video yoki dokument).")
    await callback.answer()


@router.message(
    StateFilter(AdminStates.waiting_video),
    F.video | F.video_note | F.animation | F.document,
)
async def admin_video_save(message: Message, state: FSMContext) -> None:
    fid = None
    if message.video:
        fid = message.video.file_id
    elif message.video_note:
        fid = message.video_note.file_id
    elif message.animation:
        fid = message.animation.file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("video"):
        fid = message.document.file_id
    if not fid:
        await message.answer("Video yoki video hujjat yuboring (GIF ham bo'lishi mumkin).")
        return
    db = SessionLocal()
    try:
        system_service.set_tutorial_video_file_id(db, fid)
        db.commit()
    finally:
        db.close()
    await state.clear()
    await message.answer(
        f"{MSG_VIDEO_SAVED}\n\n✅ Video qabul qilindi va saqlandi. Foydalanuvchilar «Qo'llanma» orqali ko'radi.",
        reply_markup=_admin_home_kb(),
    )


@router.message(StateFilter(AdminStates.waiting_video), F.text)
async def admin_video_cancel(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().lower() in ("/cancel", "bekor"):
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=_admin_home_kb())
