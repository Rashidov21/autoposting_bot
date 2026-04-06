from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from sqlalchemy import select

from app.analytics.stats import campaign_totals
from app.core.admin import is_admin
from app.db.models import Campaign, Schedule
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import users as user_service
from app.services.subscription import is_subscription_active
from app.services import system as system_service
from bot.keyboards import after_stop_inline_kb, main_menu
from bot.messages import (
    BTN_CAMPAIGN,
    BTN_HELP,
    BTN_STATUS,
    BTN_STOP,
    BTN_VIDEO,
    MSG_CAMPAIGN_PROMPT_TEXT,
    MSG_HELP,
    MSG_PAYMENT_NEED_PHONE_FIRST,
    MSG_PHOTO_IGNORE_SUBSCRIBED,
    MSG_PHOTO_NEED_TARIFF,
    MSG_STOP_DONE,
    MSG_STOP_NEXT_HINT,
    MSG_VIDEO_NONE,
    MSG_VIDEO_PRIVATE_ONLY,
    MSG_WELCOME,
)
from bot.states import CampaignStates, PaymentStates

router = Router(name="user")

_UZ_TZ = ZoneInfo("Asia/Tashkent")
_CARD_SEP = "━" * 20


def _campaign_status_uz(status: str) -> str:
    return {
        "running": "ishlamoqda",
        "draft": "qoralama",
        "paused": "to'xtatilgan",
    }.get(status, status)


def _status_emoji(status: str) -> str:
    return {"running": "🟢", "draft": "📝", "paused": "⏸"}.get(status, "❔")


def _format_next_run(sch: Schedule | None) -> str:
    if not sch or not sch.next_run_at:
        return "reja yo'q"
    dt = sch.next_run_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_UZ_TZ)
    return local.strftime("%d.%m.%Y soat %H:%M") + " (Oʻzbekiston)"


def _format_campaign_body(c: Campaign, sch: Schedule | None, st: dict) -> str:
    nra = _format_next_run(sch)
    iv = c.interval_minutes
    total = int(st.get("total", 0))
    success = int(st.get("success", 0))
    by = st.get("by_status") or {}
    fail = int(by.get("fail", 0))
    skipped = int(by.get("skipped", 0))
    se = _status_emoji(c.status)

    lines = [
        f"{se} Holat: {_campaign_status_uz(c.status)}",
        f"⏱ Interval: har {iv} daq",
        f"🕐 Keyingi yuborish: {nra}",
    ]
    if total == 0:
        lines.append("📭 Statistika: hali yuborilgan xabar yo'q")
    else:
        lines.append(
            f"📈 Statistika: {success} ok / {total} jami "
            f"(xato: {fail}, o'tkazilgan: {skipped})"
        )
    short_id = str(c.id).split("-")[0]
    lines.append(f"🆔 ID: {short_id}…")
    return "\n".join(lines)


async def send_tutorial_video_message(message: Message) -> None:
    """Qo'llanma videosi — faqat shaxsiy chat."""
    if message.chat.type != "private":
        await message.answer(MSG_VIDEO_PRIVATE_ONLY)
        return
    db = SessionLocal()
    try:
        fid = system_service.get_tutorial_video_file_id(db)
    finally:
        db.close()
    if not fid:
        await message.answer(MSG_VIDEO_NONE)
        return
    try:
        await message.answer_video(fid, caption="🎬 Qo'llanma")
    except Exception:
        await message.answer(MSG_VIDEO_NONE)


async def send_campaign_status(message: Message, telegram_id: int) -> None:
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, telegram_id)
        if not u:
            await message.answer("/start")
            return
        camps = campaign_service.list_user_campaigns(db, u.id)
        if not camps:
            await message.answer(
                f"Hozircha saqlangan xabar yo'q. «{BTN_CAMPAIGN}» orqali boshlang."
            )
            return
        header = f"📊 Xabarlar: {len(camps)} ta\n⏱ Vaqt: Oʻzbekiston\n"
        blocks: list[str] = []
        buttons: list[list[InlineKeyboardButton]] = []
        for i, c in enumerate(camps[:10], start=1):
            sch = db.execute(select(Schedule).where(Schedule.campaign_id == c.id)).scalar_one_or_none()
            st = campaign_totals(db, c.id)
            name = (c.name or "Xabar").strip() or "Xabar"
            body = _format_campaign_body(c, sch, st)
            block = f"{_CARD_SEP}\n📌 {i}) {name}\n{body}\n{_CARD_SEP}"
            blocks.append(block)
            cid = str(c.id)
            label = name[:18] + "…" if len(name) > 18 else name
            if c.status == "running":
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"⏹ Pauza · {label}",
                            callback_data=f"camp:pause:{cid}",
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"▶️ Ishga tushirish · {label}",
                            callback_data=f"camp:resume:{cid}",
                        )
                    ]
                )
        text = header + "\n\n".join(blocks)
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    finally:
        db.close()


@router.message(Command("admin"))
async def cmd_admin_slash(message: Message, state: FSMContext) -> None:
    from bot.handlers.admin import send_admin_home

    await state.clear()
    await send_admin_home(message)


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
    await message.answer(MSG_WELCOME, reply_markup=main_menu(message.from_user.id))


@router.message(F.text == BTN_HELP)
async def help_cmd(message: Message) -> None:
    await message.answer(MSG_HELP, reply_markup=main_menu(message.from_user.id))


@router.message(F.text == BTN_STATUS)
async def status_cmd(message: Message) -> None:
    await send_campaign_status(message, message.from_user.id)


async def execute_stop_answer(message: Message) -> None:
    """To'xtatish logikasi — boshqa handlerlardan chaqirish mumkin."""
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        camps = db.execute(
            select(Campaign).where(Campaign.user_id == u.id, Campaign.status == "running")
        ).scalars().all()
        for c in camps:
            campaign_service.stop_campaign(db, c)
        db.commit()
        n = len(camps)
        body = MSG_STOP_DONE.format(n=n)
        if n > 0:
            body += "\n\n" + MSG_STOP_NEXT_HINT
        await message.answer(
            body,
            reply_markup=after_stop_inline_kb() if n > 0 else main_menu(message.from_user.id),
        )
    finally:
        db.close()


@router.message(F.text == BTN_STOP)
async def stop_cmd(message: Message) -> None:
    await execute_stop_answer(message)


@router.callback_query(F.data == "nav:campaign")
async def nav_campaign(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CampaignStates.message_text)
    await callback.message.answer(
        MSG_CAMPAIGN_PROMPT_TEXT,
        reply_markup=main_menu(callback.from_user.id),
    )


@router.callback_query(F.data == "nav:status")
async def nav_status_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_campaign_status(callback.message, callback.from_user.id)


@router.message(F.text == BTN_VIDEO)
async def video_tutorial(message: Message) -> None:
    await send_tutorial_video_message(message)


@router.message(F.photo)
async def stray_photo(message: Message, state: FSMContext) -> None:
    st = await state.get_state()
    if st == PaymentStates.waiting_screenshot.state:
        return
    if st == PaymentStates.waiting_phone.state:
        await message.answer(MSG_PAYMENT_NEED_PHONE_FIRST)
        return
    if is_admin(message.from_user.id):
        return
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
    finally:
        db.close()
    if u and is_subscription_active(u):
        await message.answer(MSG_PHOTO_IGNORE_SUBSCRIBED)
        return
    await message.answer(MSG_PHOTO_NEED_TARIFF)
