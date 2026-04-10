from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from sqlalchemy import func, select

from app.analytics.stats import campaign_totals
from app.core.admin import is_admin
from app.core.config import get_settings
from app.db.models import Account, Campaign, Group, Schedule, SendLog
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import users as user_service
from app.services.subscription import is_subscription_active
from app.services import system as system_service
from bot.keyboards import after_stop_inline_kb, help_inline_kb, main_menu, reply_main_menu
from bot.messages import (
    BTN_CAMPAIGN,
    BTN_HELP,
    BTN_RESUME,
    BTN_STATUS,
    BTN_STOP,
    BTN_TARIFF,
    BTN_VIDEO,
    MSG_CAMPAIGN_OLD_PAUSED,
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
                f"Hozircha saqlangan xabar yo'q. «{BTN_CAMPAIGN}» orqali boshlang.",
                reply_markup=reply_main_menu(telegram_id),
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
        await message.answer("👇 Asosiy menyu:", reply_markup=main_menu(telegram_id, db))
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
    demo_h = get_settings().demo_hours
    await message.answer(
        f"{MSG_WELCOME}\n\n"
        f"⏱ Demo: {demo_h} soat bepul sinab ko'rish. Keyin «{BTN_TARIFF}» orqali obuna.",
        reply_markup=reply_main_menu(message.from_user.id),
    )


@router.message(F.text == BTN_HELP)
async def help_cmd(message: Message) -> None:
    await message.answer(
        MSG_HELP,
        reply_markup=reply_main_menu(message.from_user.id),
    )
    await message.answer("Quyidagidan birini tanlang:", reply_markup=help_inline_kb())


@router.callback_query(F.data == "help:account_status")
async def help_account_status(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, callback.from_user.id)
        if not u:
            await callback.message.answer("/start")
            await callback.answer()
            return

        accounts = list(
            db.execute(select(Account).where(Account.user_id == u.id).order_by(Account.updated_at.desc()))
            .scalars()
            .all()
        )
        total_accounts = len(accounts)
        active_accounts = sum(1 for a in accounts if a.status == "active")
        latest_login_like = accounts[0].updated_at if accounts else None
        login_text = "yo'q"
        if latest_login_like:
            dt = latest_login_like
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            login_text = dt.astimezone(_UZ_TZ).strftime("%d.%m.%Y %H:%M")

        groups_n = int(
            db.scalar(select(func.count()).select_from(Group).where(Group.user_id == u.id)) or 0
        )
        camps = campaign_service.list_user_campaigns(db, u.id)
        running_n = sum(1 for c in camps if c.status == "running")
        campaigns_n = len(camps)

        by_status = dict(
            db.execute(
                select(SendLog.status, func.count())
                .join(Campaign, Campaign.id == SendLog.campaign_id)
                .where(Campaign.user_id == u.id)
                .group_by(SendLog.status)
            ).all()
        )
        sent_total = int(sum(int(v) for v in by_status.values()))
        sent_ok = int(by_status.get("success", 0))
        sent_fail = int(by_status.get("fail", 0))
        sent_skipped = int(by_status.get("skipped", 0))

        pay_status = (u.payment_status or "none").strip()
        sub_text = "yo'q"
        if u.subscription_ends_at:
            se = u.subscription_ends_at
            if se.tzinfo is None:
                se = se.replace(tzinfo=timezone.utc)
            sub_text = se.astimezone(_UZ_TZ).strftime("%d.%m.%Y %H:%M")

        body = (
            "📌 Akkaunt ma'lumotlari\n\n"
            f"👤 Akkauntlar: {active_accounts}/{total_accounts} active\n"
            f"🕒 Oxirgi login vaqti: {login_text} (Oʻzbekiston)\n"
            f"👥 Guruhlar soni: {groups_n}\n"
            f"📢 Xabarlar: {campaigns_n} ta (running: {running_n})\n"
            f"📊 Statistika: {sent_ok} ok / {sent_total} jami (xato: {sent_fail}, o'tkazilgan: {sent_skipped})\n"
            f"💳 To'lov holati: {pay_status}\n"
            f"📅 Obuna: {sub_text}"
        )
        await callback.message.answer(body)
        await callback.answer()
    finally:
        db.close()


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
        await message.answer(body, reply_markup=main_menu(message.from_user.id, db))
        if n > 0:
            await message.answer("👇 Tez kirish:", reply_markup=after_stop_inline_kb())
    finally:
        db.close()


@router.message(F.text == BTN_STOP)
async def stop_cmd(message: Message) -> None:
    await execute_stop_answer(message)


async def execute_resume_answer(message: Message) -> None:
    """To'xtatilgan xabarlardan birini (eng oxirgi yangilangan) ishga tushirish."""
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        paused = list(
            db.execute(select(Campaign).where(Campaign.user_id == u.id, Campaign.status == "paused")).scalars().all()
        )
        if not paused:
            await message.answer(
                "To'xtatilgan xabar yo'q.",
                reply_markup=reply_main_menu(message.from_user.id),
            )
            return
        paused.sort(key=lambda c: c.updated_at, reverse=True)
        c = paused[0]
        try:
            s, paused_n = campaign_service.start_campaign(db, c)
            db.commit()
        except Exception as e:
            db.rollback()
            await message.answer(f"Xato: {e}", reply_markup=reply_main_menu(message.from_user.id))
            return
        extra = ""
        if paused_n > 0:
            extra = "\n\n" + MSG_CAMPAIGN_OLD_PAUSED
        nxt = ""
        if s and s.next_run_at:
            dt = s.next_run_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            nxt = "\n\nKeyingi: " + dt.astimezone(_UZ_TZ).strftime("%d.%m.%Y %H:%M") + " (Oʻzbekiston)"
        await message.answer(
            f"▶️ Ishga tushdi.{extra}{nxt}",
            reply_markup=reply_main_menu(message.from_user.id),
        )
    finally:
        db.close()


@router.message(F.text == BTN_RESUME)
async def resume_cmd(message: Message) -> None:
    await execute_resume_answer(message)


@router.callback_query(F.data == "nav:campaign")
async def nav_campaign(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CampaignStates.message_text)
    await callback.message.answer(
        MSG_CAMPAIGN_PROMPT_TEXT,
        reply_markup=reply_main_menu(callback.from_user.id),
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
