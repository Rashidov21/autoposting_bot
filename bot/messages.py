"""Barcha ReplyKeyboard va bot matnlari — handlers + keyboards bilan mos."""

from __future__ import annotations

# --- ReplyKeyboard tugmalari ---
BTN_TARIFF = "💳 Tarif va to'lov"
BTN_CAMPAIGN = "📢 Xabar"
BTN_STATUS = "📊 Holat"
BTN_STOP = "⏹ To'xtatish"
BTN_VIDEO = "🎬 Qo'llanma"
BTN_ACCOUNT = "👤 Akkaunt ulash"
BTN_HELP = "❓ Yordam"
BTN_CANCEL = "Bekor qilish"
BTN_ADMIN = "🛠 Admin panel"

BTN_CREATE_CAMPAIGN = BTN_CAMPAIGN

# Bosqichda boshqa menyuga bosilganda (FSM)
MSG_FSM_SWITCH_MENU = (
    "Jarayon bekor qilindi. Pastdagi tugmalardan keraklisini qayta bosing.\n"
    "Yoki «📢 Xabar»dan xabar sozlashni davom ettiring."
)

# Interval tanlash (xabar)
INTERVAL_3 = "3 daqiqa"
INTERVAL_5 = "5 daqiqa"
INTERVAL_10 = "10 daqiqa"
INTERVAL_15 = "15 daqiqa"

INTERVAL_BUTTONS: tuple[str, ...] = (INTERVAL_3, INTERVAL_5, INTERVAL_10, INTERVAL_15)

MAIN_MENU_TEXTS: frozenset[str] = frozenset(
    {
        BTN_TARIFF,
        BTN_CAMPAIGN,
        BTN_STATUS,
        BTN_STOP,
        BTN_VIDEO,
        BTN_ACCOUNT,
        BTN_HELP,
        BTN_ADMIN,
        BTN_CANCEL,
    }
)

# --- Foydalanuvchi /start va yordam ---
MSG_WELCOME = (
    "👋 Assalomu alaykum!\n\n"
    "Bu yerda avtomatik xabarlarni guruhlarga yuborishni boshqarasiz "
    "(Telethon userbot orqali).\n\n"
    "▶️ Boshlash: pastdagi tugmalardan birini tanlang.\n"
    "❓ Chalg‘maslik uchun: «❓ Yordam»."
)

MSG_HELP = (
    "📖 Nima qilish mumkin?\n\n"
    "💳 Tarif va to'lov — obuna olish, to'lov skrinshoti yuborish.\n"
    "📢 Xabar — matn, guruhlar va interval (yangi yoki mavjudni tahrirlash).\n"
    "📊 Holat — keyingi yuborish vaqti va statistika.\n"
    "⏹ To'xtatish — barcha yuborishlarni vaqtincha to'xtatish.\n"
    "🎬 Qo'llanma — video (faqat shaxsiy chatda; admin sozlasagina).\n"
    "👤 Akkaunt ulash — Telethon akkauntni ulash.\n\n"
    "🔁 Pastdagi tugmalar — boshqa bo'limga o'tish.\n"
    "«Bekor qilish» — joriy bosqichni tugatadi."
)

# --- Xabar (kampaniya) ---
MSG_CAMPAIGN_PROMPT_TEXT = (
    "✏️ Yuboriladigan xabar matnini yuboring.\n\n"
    "«Bekor qilish» — bekor. Boshqa menyuga o'tish uchun tugmani bosing (jarayon to'xtaydi)."
)
MSG_CAMPAIGN_NAME_DEFAULT = "Xabar"
MSG_GROUPS_SELECT = (
    "👥 Yuborish uchun guruhlarni belgilang (✅), keyin «Davom etish».\n"
    "➕ «Guruh chat ID» — yangi guruh qo'shish."
)
MSG_GROUPS_EMPTY = (
    "📭 Hozircha saqlangan guruh yo'q.\n"
    "➕ «Guruh chat ID» orqali chat ID qo'shing (guruhda userbot bo'lishi kerak)."
)
MSG_ENTER_GROUP_CHAT_ID = "✏️ Guruhning chat ID sini yuboring (masalan -100...):\n«Bekor qilish» yoki bosh menyuga qaytish mumkin."
MSG_GROUP_ADDED = "✅ Guruh qo'shildi. Tanlov yangilandi."
MSG_GROUPS_NONE_SELECTED = "⚠️ Kamida bitta guruhni tanlang."
MSG_INTERVAL_PROMPT = "⏱ Intervalni tanlang (pastdagi tugmalar):"
MSG_CAMPAIGN_STARTED = "✅ Xabar ishga tushdi."
MSG_CAMPAIGN_OLD_PAUSED = (
    "ℹ️ Boshqa faol xabarlar pauzaga olindi (bir vaqtning o'zida bitta faol xabar)."
)

MSG_XABAR_PANEL_CAPTION = "📋 Mavjud xabar — tahrirlash yoki yangisini boshlash:"
MSG_XABAR_EDIT_TEXT_PROMPT = "✏️ Yangi matnni yuboring (oldingi matn almashtiriladi):\n«Bekor qilish» — bekor."
MSG_XABAR_EDIT_TEXT_DONE = "✅ Matn yangilandi."
MSG_XABAR_EDIT_INTERVAL_DONE = "✅ Interval yangilandi."
MSG_XABAR_EDIT_GROUPS_DONE = "✅ Guruhlar yangilandi."
MSG_XABAR_NEW_CONFIRM = (
    "🆕 Yangi xabar boshlaysizmi? Joriy barcha xabarlar o'chiriladi.\n"
    "Davom etish uchun xabar matnini yuboring yoki «Bekor qilish»."
)
MSG_VIDEO_PRIVATE_ONLY = (
    "🎬 Qo'llanma videosi faqat bot bilan shaxsiy chatda yuboriladi.\n"
    "Guruhda emas — botga shaxsiy xabar yuboring."
)

# --- To'lov ---
MSG_TARIFF_MENU = "Tarifni tanlang (oy bo'yicha):"
MSG_PAYMENT_PHONE_PROMPT = "Telefon raqamingizni yuboring (kontakt yoki matn, +998...)."
MSG_PAYMENT_PHONE_INVALID = "Telefon noto'g'ri. + bilan xalqaro formatda yuboring."
MSG_PAYMENT_SCREENSHOT_PROMPT = "To'lov skrinshotini rasm sifatida yuboring."
MSG_PAYMENT_SUBMITTED = "✅ Arizangiz qabul qilindi. Admin tekshirgach, obuna yangilanadi."
MSG_PAYMENT_NEED_PHONE_FIRST = "Avvalo telefon raqamingizni yuboring (to'lov bosqichida)."

# --- To'lov (admin tasdiq) ---
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
MSG_STOP_DONE = "{n} ta xabar oqimi to'xtatildi."
MSG_STOP_NEXT_HINT = "Pastdagi tugmalar: yangi xabar yoki holat."
MSG_VIDEO_NONE = "📭 Admin hali video qo'llanma yuklamagan."
MSG_PHOTO_IGNORE_SUBSCRIBED = "Rasm qabul qilinmadi — obuna faol. To'lov uchun «Tarif va to'lov»."
MSG_PHOTO_NEED_TARIFF = "Obuna uchun avval «Tarif va to'lov» bo'limidan tarif tanlang."

# Inline (to'xtatishdan keyin)
INLINE_NAV_NEW_XABAR = "📢 Yangi xabar"
INLINE_NAV_STATUS = "📊 Holatni ko'rish"
