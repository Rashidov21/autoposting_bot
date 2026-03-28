from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Kampaniya yaratish")],
            [KeyboardButton(text="Holat"), KeyboardButton(text="To'xtatish")],
            [KeyboardButton(text="Akkaunt ulash")],
        ],
        resize_keyboard=True,
    )


def intervals_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="3 daqiqa"), KeyboardButton(text="5 daqiqa")],
            [KeyboardButton(text="10 daqiqa"), KeyboardButton(text="15 daqiqa")],
            [KeyboardButton(text="Bekor qilish")],
        ],
        resize_keyboard=True,
    )
