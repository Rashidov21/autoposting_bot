from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.db.models import Account
from app.db.session import SessionLocal
from app.services import users as user_service
from bot.keyboards import main_menu
from bot.messages import BTN_ACCOUNT
from bot.states import LoginStates

router = Router(name="login")


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
        await message.answer("Sessiya buzildi. Qaytadan 'Akkaunt ulash'.")
        return

    from worker.tasks import complete_login_task

    complete_login_task.delay(acc_id, phone, code)
    await message.answer(
        "Kod qabul qilindi. Bir necha soniyadan keyin akkaunt faollashadi.",
        reply_markup=main_menu(message.from_user.id),
    )
