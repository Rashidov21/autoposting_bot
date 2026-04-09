from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Campaign, Group
from app.db.session import SessionLocal
from app.services import users as user_service
from bot.messages import (
    BTN_ACCOUNT,
    BTN_ADMIN,
    BTN_CANCEL,
    BTN_CAMPAIGN,
    BTN_HELP,
    BTN_RESUME,
    BTN_STATUS,
    BTN_STOP,
    BTN_TARIFF,
    BTN_VIDEO,
    INLINE_NAV_NEW_XABAR,
    INLINE_NAV_STATUS,
    INTERVAL_10,
    INTERVAL_15,
    INTERVAL_3,
    INTERVAL_5,
)


def main_menu(telegram_id: int | None = None, db: Session | None = None) -> ReplyKeyboardMarkup:
    """Ikkinchi qator: ishlayotgan xabar bo'lsa To'xtatish, aks holda pauzada xabar bo'lsa Ishga tushirish."""
    second = BTN_STOP
    if db is not None and telegram_id is not None:
        u = user_service.get_by_telegram_id(db, telegram_id)
        if u:
            camps = list(db.execute(select(Campaign).where(Campaign.user_id == u.id)).scalars().all())
            any_running = any(c.status == "running" for c in camps)
            any_paused = any(c.status == "paused" for c in camps)
            if not any_running and any_paused:
                second = BTN_RESUME
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_TARIFF), KeyboardButton(text=BTN_CAMPAIGN)],
        [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=second)],
        [KeyboardButton(text=BTN_VIDEO), KeyboardButton(text=BTN_ACCOUNT)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    if telegram_id is not None and telegram_id in get_settings().admin_telegram_id_set:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def reply_main_menu(telegram_id: int) -> ReplyKeyboardMarkup:
    """Qisqa DB ulanishi — main_menu uchun holatni aniqlash."""
    db = SessionLocal()
    try:
        return main_menu(telegram_id, db)
    finally:
        db.close()


def _group_button_label(g: Group) -> str:
    if g.title:
        return g.title[:55]
    return f"Guruh {g.telegram_chat_id}"


def groups_pick_kb(groups: list[Group], selected: set[str]) -> InlineKeyboardMarkup:
    """Eski callback sxema: grp:t:, grp:manual, grp:go."""
    rows: list[list[InlineKeyboardButton]] = []
    for g in groups:
        mark = "✅" if str(g.id) in selected else "☐"
        label = _group_button_label(g)
        rows.append(
            [InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"grp:t:{g.id}")]
        )
    rows.append([InlineKeyboardButton(text="📝 Qo'lda chat ID kiritish", callback_data="grp:manual")])
    rows.append([InlineKeyboardButton(text="Davom etish »", callback_data="grp:go")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_inline_kb(rows: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    """Kampaniya: grp:tog:, grp:del:, grp:add, grp:cancel, grp:done."""
    ib: list[list[InlineKeyboardButton]] = []
    for gid, label, selected in rows:
        mark = "✅" if selected else "☐"
        short_label = (label or "")[:60]
        ib.append(
            [
                InlineKeyboardButton(text=f"{mark} {short_label}", callback_data=f"grp:tog:{gid}"),
                InlineKeyboardButton(text="🗑", callback_data=f"grp:del:{gid}"),
            ]
        )
    ib.append([InlineKeyboardButton(text="➕ Guruh chat ID", callback_data="grp:add")])
    ib.append(
        [
            InlineKeyboardButton(text="Bekor qilish", callback_data="grp:cancel"),
            InlineKeyboardButton(text="Davom etish »", callback_data="grp:done"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=ib)


def intervals_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=INTERVAL_3), KeyboardButton(text=INTERVAL_5)],
            [KeyboardButton(text=INTERVAL_10), KeyboardButton(text=INTERVAL_15)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def tariff_inline_kb() -> InlineKeyboardMarkup:
    s = get_settings()
    def _p(n: int) -> str:
        return f"{n:,}".replace(",", " ")

    # Har bir qator alohida — kichik ekranda summa to'liq ko'rinsin
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"1 oy — {_p(s.tariff_1_month_uzs)} so'm",
                    callback_data="tariff:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"6 oy — {_p(s.tariff_6_month_uzs)} so'm",
                    callback_data="tariff:6",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"12 oy — {_p(s.tariff_12_month_uzs)} so'm",
                    callback_data="tariff:12",
                )
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_tariff")],
        ]
    )


def phone_share_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Kontaktni ulashish", request_contact=True)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def after_stop_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=INLINE_NAV_NEW_XABAR, callback_data="nav:campaign")],
            [InlineKeyboardButton(text=INLINE_NAV_STATUS, callback_data="nav:status")],
        ]
    )
