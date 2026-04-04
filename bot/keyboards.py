from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.core.admin import is_admin
from app.core.config import get_settings
from bot.messages import (
    BTN_ACCOUNT,
    BTN_ADMIN,
    BTN_CAMPAIGN,
    BTN_CANCEL,
    BTN_HELP,
    BTN_STATUS,
    BTN_STOP,
    BTN_TARIFF,
    BTN_VIDEO,
)


def main_menu(telegram_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_TARIFF), KeyboardButton(text=BTN_CAMPAIGN)],
        [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_STOP)],
        [KeyboardButton(text=BTN_VIDEO), KeyboardButton(text=BTN_ACCOUNT)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    if is_admin(telegram_id):
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def intervals_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏱ 3 daqiqa"), KeyboardButton(text="⏱ 5 daqiqa")],
            [KeyboardButton(text="⏱ 10 daqiqa"), KeyboardButton(text="⏱ 15 daqiqa")],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def tariff_inline_kb() -> InlineKeyboardMarkup:
    s = get_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📅 1 oy — {s.tariff_1_month_uzs:,} so'm",
                    callback_data="tariff:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📅 6 oy — {s.tariff_6_month_uzs:,} so'm",
                    callback_data="tariff:6",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📅 12 oy — {s.tariff_12_month_uzs:,} so'm",
                    callback_data="tariff:12",
                )
            ],
            [InlineKeyboardButton(text=BTN_CANCEL, callback_data="cancel_tariff")],
        ]
    )


def phone_share_kb() -> ReplyKeyboardMarkup:
    from aiogram.types import KeyboardButton

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
            [
                InlineKeyboardButton(text="📢 Yangi kampaniya", callback_data="nav:campaign"),
                InlineKeyboardButton(text="📊 Holat", callback_data="nav:status"),
            ],
        ]
    )


def groups_inline_kb(
    group_rows: list[tuple[str, str, bool]],
) -> InlineKeyboardMarkup:
    """group_rows: (uuid_str, label, selected)"""
    buttons: list[list[InlineKeyboardButton]] = []
    for gid, label, sel in group_rows:
        mark = "✅ " if sel else "⬜ "
        buttons.append(
            [InlineKeyboardButton(text=f"{mark}{label[:30]}", callback_data=f"grp:tog:{gid}")]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="➕ Guruh chat ID", callback_data="grp:add"),
            InlineKeyboardButton(text="Davom etish ▶️", callback_data="grp:done"),
        ]
    )
    buttons.append([InlineKeyboardButton(text=BTN_CANCEL, callback_data="grp:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
