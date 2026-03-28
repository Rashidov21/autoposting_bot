from __future__ import annotations

import random


def random_delay(min_s: float, max_s: float) -> float:
    lo, hi = (min_s, max_s) if min_s <= max_s else (max_s, min_s)
    return random.uniform(lo, hi)


def maybe_skip_group(probability: float) -> bool:
    if probability <= 0:
        return False
    return random.random() < probability


def vary_message_text(text: str) -> str:
    """
    Kontentni har safar bir xil 'invisible fingerprint' qilmaslik muhim.
    Ko‘p hollarda matn o‘zgarmaydi; ba’zida nozik variantlar (kamroq ZWSP).
    """
    r = random.random()
    if r < 0.42:
        return text
    if r < 0.78:
        # Ba’zan oxirida oddiy bo‘shliq yoki tor no-break space
        if random.random() < 0.55:
            return text + (" " if not text.endswith(" ") else "")
        return text + "\u202f"
    # Kamdan-kam ZWSP (oldingi versiyaga nisbatan kamroq)
    return text + ("\u200b" if random.random() < 0.35 else "")


def warm_up_multiplier(warm_up_sent: int) -> float:
    """Yangi akkauntlar uchun sekinroq."""
    if warm_up_sent < 10:
        return 1.75
    if warm_up_sent < 30:
        return 1.28
    return 1.0


def shuffle_order(items: list) -> list:
    """Ro‘yxat nusxasini aralashtirish (tashqi ro‘yxatni o‘zgartirmaydi)."""
    out = list(items)
    random.shuffle(out)
    return out
