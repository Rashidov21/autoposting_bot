"""Barcha ReplyKeyboard va bot matnlari — handlers + keyboards bilan mos."""

from __future__ import annotations

# --- ReplyKeyboard tugmalari ---
BTN_TARIFF = "💳 Tarif va to'lov"
BTN_CAMPAIGN = "📢 Kampaniya"
BTN_STATUS = "📊 Holat"
BTN_STOP = "⏹ To'xtatish"
BTN_VIDEO = "🎬 Qo'llanma"
BTN_ACCOUNT = "👤 Akkaunt ulash"
BTN_HELP = "❓ Yordam"
BTN_CANCEL = "Bekor qilish"
BTN_ADMIN = "🛠 Admin panel"

# Eski nom (ixtiyoriy importlar uchun)
BTN_CREATE_CAMPAIGN = BTN_CAMPAIGN

# Interval tanlash (kampaniya)
INTERVAL_3 = "3 daqiqa"
INTERVAL_5 = "5 daqiqa"
INTERVAL_10 = "10 daqiqa"
INTERVAL_15 = "15 daqiqa"

INTERVAL_BUTTONS: tuple[str, ...] = (INTERVAL_3, INTERVAL_5, INTERVAL_10, INTERVAL_15)

# --- Foydalanuvchi /start va yordam ---
MSG_WELCOME = (
    "Assalomu alaykum. Avtopost boshqaruv paneli.\n"
    "MTProto userbot orqali guruhlarga xabar yuboriladi.\n"
    "Bir necha qadamda yangi kampaniyani sozlang."
)

MSG_HELP = (
    "📌 Qisqa yo'riqnoma:\n"
    "• «Tarif va to'lov» — obuna va to'lov.\n"
    "• «Kampaniya» — xabar matni va guruhlar.\n"
    "• «Holat» — joriy kampaniyalar.\n"
    "• «To'xtatish» — barcha yuborishlarni pauza.\n"
    "• «Qo'llanma» — video (admin sozlasagina).\n"
    "• «Akkaunt ulash» — Telethon akkaunt."
)

# --- Kampaniya ---
MSG_CAMPAIGN_PROMPT_TEXT = "Yuboriladigan xabar matnini yuboring:"
MSG_CAMPAIGN_NAME_DEFAULT = "Kampaniya"
MSG_GROUPS_SELECT = (
    "Yuborish uchun guruhlarni belgilang (✅), keyin «Davom etish».\n"
    "Pastda «Guruh chat ID» yangi guruh qo'shish uchun."
)
MSG_GROUPS_EMPTY = (
    "Hozircha saqlangan guruh yo'q. «➕ Guruh chat ID» orqali chat ID qo'shing "
    "(guruhda userbot bo'lishi kerak)."
)
MSG_ENTER_GROUP_CHAT_ID = "Guruhning chat ID sini yuboring (masalan -100...):"
MSG_GROUP_ADDED = "Guruh qo'shildi. Tanlovni yangilandi."
MSG_GROUPS_NONE_SELECTED = "Kamida bitta guruhni tanlang."
MSG_INTERVAL_PROMPT = "Intervalni tanlang (daqiqa):"
MSG_CAMPAIGN_STARTED = "✅ Kampaniya ishga tushdi."
MSG_CAMPAIGN_OLD_PAUSED = (
    "Eslatma: boshqa ishlayotgan kampaniyalar pauzaga olindi (bir vaqtning o'zida bitta faol)."
)

# --- To'lov ---
MSG_TARIFF_MENU = "Tarifni tanlang (oy bo'yicha):"
MSG_PAYMENT_PHONE_PROMPT = "Telefon raqamingizni yuboring (kontakt yoki matn, +998...)."
MSG_PAYMENT_PHONE_INVALID = "Telefon noto'g'ri. + bilan xalqaro formatda yuboring."
MSG_PAYMENT_SCREENSHOT_PROMPT = "To'lov skrinshotini rasm sifatida yuboring."
MSG_PAYMENT_SUBMITTED = "✅ Arizangiz qabul qilindi. Admin tekshirgach, obuna yangilanadi."
MSG_PAYMENT_NEED_PHONE_FIRST = "Avvalo telefon raqamingizni yuboring (to'lov bosqichida)."

# --- To'lov (admin tasdiq xabarlari foydalanuvchiga) ---
MSG_PAYMENT_ALREADY_RESOLVED = "Bu ariza allaqachon ko'rib chiqilgan."
MSG_PAYMENT_APPROVE_OK = "Tasdiqlandi."
MSG_PAYMENT_REJECT_OK = "Rad etildi."
MSG_PAYMENT_APPROVED = "✅ To'lovingiz tasdiqlandi. Obuna yangilandi."
MSG_PAYMENT_REJECTED = "❌ To'lov arizangiz rad etildi. Batafsil uchun admin bilan bog'laning."

# --- Admin ---
MSG_ADMIN_MENU = "🛠 Admin boshqaruv paneli. Tanlang:"
MSG_ADMIN_BOT_DISABLED = "Bot foydalanuvchilar uchun o'chirildi (OFF)."
MSG_ADMIN_BOT_ENABLED = "Bot foydalanuvchilar uchun yoqildi (ON)."
MSG_VIDEO_SAVED = "✅ Qo'llanma video saqlandi."

# --- To'xtatish / foto ---
MSG_STOP_DONE = "{n} ta kampaniya to'xtatildi."
MSG_STOP_NEXT_HINT = "Pastdagi tugmalar orqali yangi kampaniya yoki holatni oching."
MSG_VIDEO_NONE = "Hozircha video qo'llanma sozlanmagan."
MSG_PHOTO_IGNORE_SUBSCRIBED = "Rasm qabul qilinmadi — obuna faol. To'lov uchun «Tarif va to'lov»."
MSG_PHOTO_NEED_TARIFF = "Obuna uchun avval «Tarif va to'lov» bo'limidan tarif tanlang."
