from __future__ import annotations

import hashlib
import random
import uuid

# ---------------------------------------------------------------------------
# Device pools — Telegram da keng tarqalgan Android qurilmalar
# ---------------------------------------------------------------------------
_MODELS = [
    "Samsung Galaxy S23",
    "Samsung Galaxy S22",
    "Samsung Galaxy A54",
    "Samsung Galaxy A34",
    "Xiaomi 13",
    "Xiaomi 12 Pro",
    "Redmi Note 12 Pro",
    "Redmi Note 11",
    "POCO X5 Pro",
    "POCO M5s",
    "Realme 11 Pro",
    "Realme 10 Pro",
    "OnePlus 11",
    "OnePlus Nord 3",
    "Vivo V27 Pro",
    "OPPO Reno10 Pro",
]

_ANDROID_VERSIONS = [
    "Android 11",
    "Android 12",
    "Android 13",
    "Android 14",
]

# Telegram Android APK versiyalari (2024-2025 oralig'i)
_APP_VERSIONS = [
    "10.3.2",
    "10.4.0",
    "10.5.0",
    "10.5.2",
    "10.6.1",
    "10.7.0",
    "10.8.1",
    "10.9.0",
    "11.0.0",
    "11.1.2",
]

_LANG_CODES = ["uz", "ru", "en"]


def device_params(account_id: uuid.UUID) -> dict[str, str]:
    """
    Account UUID asosida deterministik (har safar bir xil, lekin akkauntlar o'rtasida farqli)
    TelegramClient device parametrlarini qaytaradi.

    Bir xil account_id → har doim bir xil profil.
    Har xil account_id → statistik jihatdan farqli profil.
    """
    seed = int(hashlib.sha256(str(account_id).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    lang = rng.choice(_LANG_CODES)
    return {
        "device_model": rng.choice(_MODELS),
        "system_version": rng.choice(_ANDROID_VERSIONS),
        "app_version": rng.choice(_APP_VERSIONS),
        "lang_code": lang,
        "system_lang_code": lang,
    }
