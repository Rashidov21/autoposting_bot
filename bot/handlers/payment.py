from __future__ import annotations

import html
import re
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.payment_text import build_payment_instruction_html
from app.services import subscription as subscription_service
from app.services import users as user_service
from bot.keyboards import reply_main_menu, phone_share_kb, tariff_inline_kb
from bot.messages import (
    BTN_CANCEL,
    BTN_TARIFF,
    MSG_PAYMENT_NEED_PHONE_FIRST,
    MSG_PAYMENT_PHONE_INVALID,
    MSG_PAYMENT_PHONE_PROMPT,
    MSG_PAYMENT_SCREENSHOT_PROMPT,
    MSG_PAYMENT_SUBMITTED,
    MSG_TARIFF_MENU,
)
from bot.states import PaymentStates

router = Router(name="payment")


def _tariff_intro_text() -> str:
    s = get_settings()

    def p(n: int) -> str:
        return f"{n:,}".replace(",", " ")

    return (
        f"{MSG_TARIFF_MENU}\n\n"
        f"• 1 oy — {p(s.tariff_1_month_uzs)} so'm\n"
        f"• 6 oy — {p(s.tariff_6_month_uzs)} so'm\n"
        f"• 12 oy — {p(s.tariff_12_month_uzs)} so'm"
    )


def _valid_phone(raw: str) -> bool:
    s = re.sub(r"[\s\-]", "", (raw or "").strip())
    if len(s) < 9:
        return False
    return bool(re.match(r"^\+?\d{9,18}$", s))


async def _notify_admins_payment(
    bot,
    pr_id: uuid.UUID,
    months: int,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
    contact_phone: str,
    file_id: str,
) -> None:
    settings = get_settings()
    if not settings.admin_telegram_id_set:
        return
    pid = str(pr_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin:pay:{pid}:ok"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"admin:pay:{pid}:no"),
            ]
        ]
    )
    un = f"@{html.escape(username)}" if username else "—"
    fn = html.escape((full_name or "").strip() or "—")
    phone = html.escape(contact_phone)
    cap = (
        "<b>💰 Yangi to'lov arizasi</b>\n"
        f"🆔 TG ID: <code>{telegram_id}</code>\n"
        f"👤 Username: {un}\n"
        f"📝 Ism: {fn}\n"
        f"📞 Telefon: <code>{phone}</code>\n"
        f"📅 Tarif: {months} oy\n"
        f"🔖 Ariza ID: <code>{pid}</code>"
    )
    for aid in settings.admin_telegram_id_set:
        try:
            await bot.send_photo(aid, file_id, caption=cap[:1024], reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.message(F.text == BTN_TARIFF)
async def open_tariff(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_tariff_intro_text(), reply_markup=tariff_inline_kb())


@router.callback_query(F.data.startswith("tariff:"))
async def tariff_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").split(":", 1)[-1]
    try:
        months = int(raw)
    except ValueError:
        await callback.answer("Noto'g'ri tanlov")
        return
    if months not in (1, 6, 12):
        await callback.answer("Noto'g'ri tanlov")
        return
    await state.update_data(tariff_months=months)
    await state.set_state(PaymentStates.waiting_phone)
    settings = get_settings()
    pay_block = build_payment_instruction_html(settings, months)
    body = f"{pay_block}\n\n{html.escape(MSG_PAYMENT_PHONE_PROMPT)}"
    await callback.message.answer(
        body,
        parse_mode="HTML",
        reply_markup=phone_share_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_tariff")
async def cancel_tariff(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Bekor qilindi.", reply_markup=reply_main_menu(callback.from_user.id))
    await callback.answer()


@router.message(PaymentStates.waiting_phone, F.contact)
async def payment_phone_contact(message: Message, state: FSMContext) -> None:
    if not message.contact or not message.contact.phone_number:
        await message.answer(MSG_PAYMENT_PHONE_INVALID)
        return
    await state.update_data(contact_phone=message.contact.phone_number.strip())
    await state.set_state(PaymentStates.waiting_screenshot)
    await message.answer(
        MSG_PAYMENT_SCREENSHOT_PROMPT,
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(PaymentStates.waiting_phone, F.text)
async def payment_phone_text(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=reply_main_menu(message.from_user.id))
        return
    if not _valid_phone(message.text or ""):
        await message.answer(MSG_PAYMENT_PHONE_INVALID)
        return
    await state.update_data(contact_phone=(message.text or "").strip())
    await state.set_state(PaymentStates.waiting_screenshot)
    await message.answer(MSG_PAYMENT_SCREENSHOT_PROMPT, reply_markup=ReplyKeyboardRemove())


@router.message(PaymentStates.waiting_screenshot, F.photo)
async def payment_screenshot(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    months = int(data.get("tariff_months") or 0)
    phone = (data.get("contact_phone") or "").strip()
    if months not in (1, 6, 12) or not phone:
        await state.clear()
        await message.answer("Sessiya tugadi. Qaytadan «Tarif va to'lov»ni oching.")
        return
    file_id = message.photo[-1].file_id
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        pr = subscription_service.create_payment_request(db, u, months, file_id, phone)
        db.commit()
        pr_id = pr.id
        uname = u.username
        fname = u.full_name
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}")
        return
    finally:
        db.close()

    await state.clear()
    await message.answer(MSG_PAYMENT_SUBMITTED, reply_markup=reply_main_menu(message.from_user.id))
    await _notify_admins_payment(
        message.bot,
        pr_id,
        months,
        message.from_user.id,
        uname,
        fname,
        phone,
        file_id,
    )


@router.message(PaymentStates.waiting_screenshot, F.text)
async def payment_screenshot_expect_photo(message: Message, state: FSMContext) -> None:
    if message.text == BTN_CANCEL:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=reply_main_menu(message.from_user.id))
        return
    await message.answer("Iltimos, to'lov skrinshotini rasm sifatida yuboring.")

