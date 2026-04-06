"""To'lov bo'limi uchun HTML matn (tarif summasi + rekvizit)."""

from __future__ import annotations

import html

from app.core.config import Settings


def _sep_uzs(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def build_payment_instruction_html(settings: Settings, months: int) -> str:
    amounts = {
        1: settings.tariff_1_month_uzs,
        6: settings.tariff_6_month_uzs,
        12: settings.tariff_12_month_uzs,
    }
    amt = amounts.get(months)
    if amt is None:
        raise ValueError("tariff months")
    card = (settings.payment_card_number or "").strip() or "—"
    parts = [
        "<b>To'lov usullari:</b> Uzcard, Humo, Uzum, Payme, Click, Paynet.",
        f"<b>Karta / rekvizit:</b> <code>{html.escape(card)}</code>",
        f"<b>Summa:</b> {_sep_uzs(amt)} so'm ({months} oy).",
        "<b>Keyingi qadam:</b> ko'rsatilgan summani o'tkazing, skrinshot yuboring. "
        "Admin tasdiqlagach obuna yoqiladi va bot to'liq ishlaydi.",
    ]
    extra = (settings.payment_instructions_text or "").strip()
    if extra:
        parts.insert(0, html.escape(extra))
    return "\n\n".join(parts)
