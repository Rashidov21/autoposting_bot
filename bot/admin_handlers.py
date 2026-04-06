from __future__ import annotations

import math
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services import payments as payments_service
from app.services import users as user_service

router = Router()

PAGE_SIZE = 5


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in get_settings().admin_telegram_id_set


def _users_kb(rows: list[tuple[int, User]], page: int, total: int) -> InlineKeyboardMarkup:
    """rows: (tartib raqami, User) — tartib 1 dan boshlanadi."""
    btns: list[list[InlineKeyboardButton]] = []
    for num, u in rows:
        btns.append(
            [
                InlineKeyboardButton(
                    text=f"🔒 #{num} Bloklash",
                    callback_data=f"adm:blk:{u.id}",
                ),
                InlineKeyboardButton(
                    text=f"🗑 #{num} O'chirish",
                    callback_data=f"adm:del:{u.id}",
                ),
            ]
        )
    nav: list[InlineKeyboardButton] = []
    pages = max(1, math.ceil(total / PAGE_SIZE))
    if page > 0:
        nav.append(InlineKeyboardButton(text="« Oldingi", callback_data=f"adm:page:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi »", callback_data=f"adm:page:{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([InlineKeyboardButton(text="💳 Kutilayotgan to'lovlar", callback_data="adm:pay")])
    return InlineKeyboardMarkup(inline_keyboard=btns)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await _send_users_page(message, 0)


async def _send_users_page(message: Message, page: int) -> None:
    db = SessionLocal()
    try:
        offset = page * PAGE_SIZE
        users, total = user_service.list_users_paginated(db, offset, PAGE_SIZE)
    finally:
        db.close()
    lines = [f"👥 Foydalanuvchilar (jami {total}, sahifa {page + 1})"]
    numbered: list[tuple[int, User]] = []
    for i, u in enumerate(users):
        num = offset + i + 1
        un = f"@{u.username}" if u.username else "(username yo'q)"
        lines.append(f"{num}. tg_id={u.telegram_id} {un} blok={u.is_blocked}")
        numbered.append((num, u))
    text = "\n".join(lines)
    await message.answer(
        text,
        reply_markup=_users_kb(numbered, page, total) if total else None,
    )


@router.callback_query(F.data.startswith("adm:page:"))
async def cb_page(query: CallbackQuery) -> None:
    if not query.from_user or not _is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    page = int((query.data or "").split(":")[2])
    db = SessionLocal()
    try:
        offset = page * PAGE_SIZE
        users, total = user_service.list_users_paginated(db, offset, PAGE_SIZE)
    finally:
        db.close()
    lines = [f"👥 Foydalanuvchilar (jami {total}, sahifa {page + 1})"]
    numbered = []
    for i, u in enumerate(users):
        num = offset + i + 1
        un = f"@{u.username}" if u.username else "(username yo'q)"
        lines.append(f"{num}. tg_id={u.telegram_id} {un} blok={u.is_blocked}")
        numbered.append((num, u))
    text = "\n".join(lines)
    await query.message.edit_text(text, reply_markup=_users_kb(numbered, page, total))
    await query.answer()


@router.callback_query(F.data.startswith("adm:blk:"))
async def cb_block(query: CallbackQuery) -> None:
    if not query.from_user or not _is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    uid_s = (query.data or "").split(":")[2]
    try:
        uid = uuid.UUID(uid_s)
    except ValueError:
        await query.answer()
        return
    db = SessionLocal()
    try:
        u = user_service.block_user(db, uid, True)
        db.commit()
    finally:
        db.close()
    if u:
        await query.answer(f"Bloklandi: tg_id={u.telegram_id}")
    else:
        await query.answer("Topilmadi", show_alert=True)


@router.callback_query(F.data.startswith("adm:del:"))
async def cb_delete(query: CallbackQuery) -> None:
    if not query.from_user or not _is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    uid_s = (query.data or "").split(":")[2]
    try:
        uid = uuid.UUID(uid_s)
    except ValueError:
        await query.answer()
        return
    db = SessionLocal()
    try:
        ok = user_service.delete_user(db, uid)
        db.commit()
    finally:
        db.close()
    await query.answer("O'chirildi" if ok else "Topilmadi", show_alert=not ok)


@router.callback_query(F.data == "adm:pay")
async def cb_payments(query: CallbackQuery) -> None:
    if not query.from_user or not _is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    db = SessionLocal()
    try:
        pending = payments_service.list_pending_payment_requests(db)
    finally:
        db.close()
    if not pending:
        await query.message.answer("Kutilayotgan to'lovlar yo'q.")
        await query.answer()
        return
    lines = ["💳 Kutilayotgan to'lovlar:"]
    for p in pending:
        u = p.user
        lines.append(
            f"- {str(p.id)[:8]}… | oy={p.tariff_months} | tg={u.telegram_id} | tel={p.contact_phone or '-'}"
        )
    await query.message.answer("\n".join(lines))
    await query.answer()
