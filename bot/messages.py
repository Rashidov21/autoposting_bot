"""Standart bot matnlari (bitta joydan import)."""

# Reply tugmalar (middleware va keyboard bilan bir xil qator bo'lishi shart)
BTN_TARIFF = "💳 Tarif va to'lov"
BTN_CAMPAIGN = "📢 Kampaniya"
BTN_STATUS = "📊 Holat"
BTN_STOP = "⏹ To'xtatish"
BTN_VIDEO = "🎬 Video qo'llanma"
BTN_ACCOUNT = "🔗 Akkaunt ulash"
BTN_HELP = "❓ Yordam"
BTN_ADMIN = "🛠 Admin panel"
BTN_CANCEL = "❌ Bekor qilish"

# Obunasiz ruxsat berilgan matn tugmalar
TEXT_ALLOWED_WITHOUT_SUBSCRIPTION = frozenset(
    {
        BTN_TARIFF,
        BTN_HELP,
    }
)

# Umumiy
MSG_BOT_DISABLED_GLOBAL = "Bot vaqtincha o'chirilgan."
MSG_BLOCKED = "Siz bloklangansiz."
MSG_SUBSCRIPTION_REQUIRED = (
    "Avtopost va boshqa pullik funksiyalar uchun obuna kerak. «Tarif va to'lov» bo'limidan tarif tanlang."
)
MSG_WELCOME = (
    "Assalomu alaykum. Avtopost boshqaruv paneli.\n"
    "MTProto userbot orqali guruhlarga xabar yuboriladi.\n"
    "Avval obuna bo'ling, keyin kampaniya yarating."
)

MSG_HELP = (
    "• 💳 «Tarif va to'lov» — obuna narxlari va to'lov skrinshoti.\n"
    "• 📢 «Kampaniya» — xabar matni, guruhlar va interval.\n"
    "• 📊 «Holat» — kampaniya va statistika.\n"
    "• ⏹ «To'xtatish» — barcha ishlayotgan kampaniyalarni pauza.\n"
    "• 🔗 «Akkaunt ulash» — Telegram akkaunt (userbot) ulanishi.\n"
    "Bitta vaqtda faqat bitta aktiv kampaniya bo'lishi mumkin."
)

MSG_PHOTO_NEED_TARIFF = (
    "Avval «Tarif va to'lov»dan tarifni tanlang. Keyin to'lov skrinshotini yuboring."
)
MSG_PHOTO_IGNORE_SUBSCRIBED = "Bu rasm qabul qilinmadi. Menyu tugmalaridan foydalaning."
MSG_PAYMENT_PHONE_INVALID = "Telefon raqamini to'g'ri formatda yuboring (masalan +998901234567 yoki kontakt tugmasi)."
MSG_PAYMENT_NEED_PHONE_FIRST = "Avval aloqa telefon raqamingizni yuboring (matn yoki 📱 Kontaktni ulashish)."

# Tarif / to'lov
MSG_TARIFF_MENU = "Tarifni tanlang:"
MSG_PAYMENT_PHONE_PROMPT = (
    "Aloqa uchun telefon raqamingizni yuboring:\n"
    "• Xalqaro formatda matn sifatida (masalan +998901234567)\n"
    "• Yoki pastdagi «📱 Kontaktni ulashish» tugmasidan foydalaning.\n"
    "Keyin to'lov skrinshotini so'raymiz."
)
MSG_PAYMENT_SCREENSHOT_PROMPT = "Endi to'lov skrinshotini rasm sifatida yuboring."
MSG_PAYMENT_SUBMITTED = "Arizangiz qabul qilindi. Admin tasdig'ini kuting."
MSG_PAYMENT_APPROVED = "To'lovingiz tasdiqlandi. Obuna faollashtirildi. Endi «Kampaniya» yarating."
MSG_PAYMENT_REJECTED = "To'lov arizasi rad etildi. Qayta urinib ko'ring yoki admin bilan bog'laning."

# Kampaniya
MSG_CAMPAIGN_OLD_PAUSED = (
    "Oldingi aktiv kampaniya pauzaga o'tkazildi. Faqat bitta kampaniya bir vaqtda ishlaydi."
)
MSG_CAMPAIGN_STARTED = "Kampaniya ishga tushdi."
MSG_CAMPAIGN_NAME_DEFAULT = "Kampaniya"
MSG_GROUPS_EMPTY = (
    "Hali saqlangan guruh yo'q. «➕ Guruh chat ID» tugmasi orqali chat ID yuboring "
    "(masalan superguruh ID: -100...)."
)
MSG_GROUPS_SELECT = "Yuborish uchun guruhlarni belgilang (✅), keyin «Davom etish»."
MSG_GROUPS_NONE_SELECTED = "Kamida bitta guruhni tanlang."
MSG_ENTER_GROUP_CHAT_ID = "Guruhning Telegram chat ID sini raqam sifatida yuboring (masalan -1001234567890)."
MSG_GROUP_ADDED = "Guruh qo'shildi."
MSG_CAMPAIGN_PROMPT_TEXT = "Kampaniya xabar matnini yuboring:"
MSG_INTERVAL_PROMPT = "Intervalni tanlang (daqiqa):"
MSG_STOP_DONE = "{n} ta kampaniya to'xtatildi."
MSG_STOP_NEXT_HINT = "Keyingi qadam:"

# Obuna tugashi (worker)
MSG_SUBSCRIPTION_EXPIRED = (
    "Obuna muddati tugadi. Kampaniyangiz to'xtatildi. «Tarif va to'lov» orqali yangilang."
)

# Admin
MSG_ADMIN_ONLY = "Bu bo'lim faqat adminlar uchun."
MSG_ADMIN_MENU = (
    "🛠 Admin panel.\n"
    "• 👥 Foydalanuvchilar — ro'yxat va blok\n"
    "• 💰 To'lovlar — kutilayotgan arizalar\n"
    "• Bot ON/OFF — barcha uchun\n"
    "• 🎬 Video — qo'llanma videosini yangilash\n"
    "• /admin — bu menyu"
)
MSG_USER_BLOCKED_OK = "Foydalanuvchi bloklandi."
MSG_USER_UNBLOCKED_OK = "Blokdan chiqarildi."
MSG_ADMIN_BOT_ENABLED = "Bot yoqildi (barcha foydalanuvchilar uchun)."
MSG_ADMIN_BOT_DISABLED = "Bot o'chirildi (barcha foydalanuvchilar uchun)."
MSG_VIDEO_SAVED = "Video qo'llanma yangilandi."
MSG_VIDEO_NONE = "Video hali yuklanmagan. Admin sozlamalaridan keyin qayta urinib ko'ring."
MSG_PAYMENT_ALREADY_RESOLVED = "Bu ariza allaqachon yopilgan."
MSG_PAYMENT_APPROVE_OK = "To'lov tasdiqlandi."
MSG_PAYMENT_REJECT_OK = "To'lov rad etildi."
