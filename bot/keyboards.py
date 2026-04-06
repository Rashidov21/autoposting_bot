from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.core.config import get_settings
from app.db.models import Group
from bot.messages import (
    BTN_ACCOUNT,
    BTN_ADMIN,
    BTN_CANCEL,
    BTN_CAMPAIGN,
    BTN_HELP,
    BTN_STATUS,
    BTN_STOP,
    BTN_TARIFF,
    BTN_VIDEO,
    INTERVAL_10,
    INTERVAL_15,
    INTERVAL_3,
    INTERVAL_5,
)


def main_menu(telegram_id: int | None = None) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_TARIFF), KeyboardButton(text=BTN_CAMPAIGN)],
        [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_STOP)],
        [KeyboardButton(text=BTN_VIDEO), KeyboardButton(text=BTN_ACCOUNT)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    if telegram_id is not None and telegram_id in get_settings().admin_telegram_id_set:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


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
    """Kampaniya: grp:tog:, grp:add, grp:cancel, grp:done."""
    ib: list[list[InlineKeyboardButton]] = []
    for gid, label, selected in rows:
        mark = "✅" if selected else "☐"
        short_label = (label or "")[:60]
        ib.append([InlineKeyboardButton(text=f"{mark} {short_label}", callback_data=f"grp:tog:{gid}")])
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 oy", callback_data="tariff:1"),
                InlineKeyboardButton(text="6 oy", callback_data="tariff:6"),
                InlineKeyboardButton(text="12 oy", callback_data="tariff:12"),
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
            [InlineKeyboardButton(text="📢 Yangi kampaniya", callback_data="nav:campaign")],
            [InlineKeyboardButton(text="📊 Holatni ko'rish", callback_data="nav:status")],
        ]
    )
