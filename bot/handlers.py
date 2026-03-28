from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from sqlalchemy import select

from app.analytics.stats import campaign_totals
from app.db.models import Account, Campaign, Schedule
from app.db.session import SessionLocal
from app.services import campaigns as campaign_service
from app.services import users as user_service
from bot.keyboards import intervals_kb, main_menu
from bot.states import CampaignStates, LoginStates

router = Router()


def _parse_interval(text: str) -> int | None:
    m = re.match(r"^(\d+)\s*daqiqa", text.strip(), re.I)
    if not m:
        return None
    v = int(m.group(1))
    return v if v in (3, 5, 10, 15) else None


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
        "3–4 qadamda kampaniya yarating.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "Kampaniya yaratish")
async def start_campaign(message: Message, state: FSMContext) -> None:
    await state.set_state(CampaignStates.message_text)
    await message.answer("Kampaniya xabar matnini yuboring:")


@router.message(CampaignStates.message_text, F.text)
async def campaign_message(message: Message, state: FSMContext) -> None:
    if message.text == "Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu())
        return
    await state.update_data(message_text=message.text.strip())
    await state.set_state(CampaignStates.chat_ids)
    await message.answer(
        "Guruhlar: har bir chat ID ni vergul bilan yuboring.\n"
        "Masalan: -1001234567890,-1009876543210\n"
        "(Guruhda userbot akkaunt bo'lishi kerak.)"
    )


@router.message(CampaignStates.chat_ids, F.text)
async def campaign_chats(message: Message, state: FSMContext) -> None:
    if message.text == "Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu())
        return
    parts = [p.strip() for p in message.text.split(",") if p.strip()]
    chats: list[int] = []
    for p in parts:
        try:
            chats.append(int(p))
        except ValueError:
            await message.answer("Noto'g'ri format. Qayta yuboring.")
            return
    await state.update_data(chat_ids=chats)
    await state.set_state(CampaignStates.interval)
    await message.answer("Intervalni tanlang:", reply_markup=intervals_kb())


@router.message(CampaignStates.interval, F.text)
async def campaign_interval(message: Message, state: FSMContext) -> None:
    if message.text == "Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu())
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
        c = campaign_service.create_campaign_from_chat_ids(
            db,
            u,
            "Kampaniya",
            data["message_text"],
            iv,
            data["chat_ids"],
        )
        s = campaign_service.start_campaign(db, c)
        db.commit()
        await message.answer(
            f"Kampaniya ishga tushdi.\nID: `{c.id}`\nKeyingi ish: {s.next_run_at.isoformat()}",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )
    except Exception as e:
        db.rollback()
        await message.answer(f"Xato: {e}", reply_markup=main_menu())
    finally:
        db.close()


@router.message(F.text == "Holat")
async def status_cmd(message: Message) -> None:
    db = SessionLocal()
    try:
        u = user_service.get_by_telegram_id(db, message.from_user.id)
        if not u:
            await message.answer("/start")
            return
        camps = campaign_service.list_user_campaigns(db, u.id)
        lines = [f"Kampaniyalar: {len(camps)}"]
        for c in camps[:10]:
            sch = db.execute(select(Schedule).where(Schedule.campaign_id == c.id)).scalar_one_or_none()
            nra = sch.next_run_at.isoformat() if sch else "-"
            st = campaign_totals(db, c.id)
            lines.append(
                f"- {str(c.id)[:8]}… status={c.status} next={nra} ok={st.get('success',0)}/{st.get('total',0)}"
            )
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(F.text == "To'xtatish")
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
        await message.answer(f"{len(camps)} ta kampaniya to'xtatildi.", reply_markup=main_menu())
    finally:
        db.close()


@router.message(F.text == "Akkaunt ulash")
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
    await message.answer("Kod qabul qilindi. Bir necha soniyadan keyin akkaunt faollashadi.", reply_markup=main_menu())
