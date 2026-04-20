"""
Redis-based signalling between bot (editor) and Celery workers (sender).

WHY
---
``process_campaign`` Celery task ichida kampaniya ``message_text`` bir marta DB
dan o'qiladi va 1-5 daqiqa davomida protsess xotirasida turadi (SQLAlchemy
``expire_on_commit=False`` bo'lgani uchun keyingi commitlardan keyin ham
refresh bo'lmaydi). Bu vaqt ichida foydalanuvchi bot orqali matnni tahrir
qilsa, DB yangilanadi, lekin worker stale qiymatni ishlatib **eski xabar**
yuborishda davom etadi.

Yana: ``delete_all_campaigns_for_user`` chaqirilgan bo'lsa, worker hali ishlayotgan
kampaniya uchun ``send_logs`` yozuvlarini commit qilolmaydi (FK violation) va
butun batch silent fail bo'ladi.

YECHIM
------
Redis ni ``write-through cache`` + ``revoke pub`` sifatida ishlatamiz:

- Bot tahrirda DB bilan birga Redis kaliti ``campaign:text:{cid}`` ga yangi
  matnni yozadi (TTL 24 soat). Worker har yuborishdan oldin Redis dan matnni
  o'qiydi — mavjud bo'lsa o'sha matn ishlatiladi, yo'q bo'lsa DB dagi qiymat.
- ``campaign:revoke:{cid}`` kalitini qo'yish — workerga "bu round tugasin"
  signali. Worker har iteration boshida tekshiradi va mavjud bo'lsa loop'dan
  chiqib, ``finish_schedule`` da ``next_run_at = now + short_delay`` qo'yadi
  va oddiy (muvaffaqiyatli) yakunlanadi. Bu orqali FK violation, pending
  batchlar yo'qolishi va foydalanuvchining "eski matn ketyapti" simptomi
  bartaraf bo'ladi.

Redis yo'q bo'lsa yoki xato bersa, tizim oddiy rejimga qaytadi (graceful
degradation) — DB matni ishlatiladi, revoke signali e'tiborga olinmaydi.
"""
from __future__ import annotations

import logging
import uuid

import redis

from engine.redis_pool import get_redis

logger = logging.getLogger(__name__)

# 24 soat: odatda kampaniyaning ``interval_minutes`` dan ancha uzoq.
_TEXT_TTL_SECONDS = 24 * 60 * 60

# 10 daqiqa: revoke signali maksimum shuncha tirik turadi. Worker bir
# roundning eng uzoq ish vaqtida ham o'qib olishi uchun yetarli.
_REVOKE_TTL_SECONDS = 10 * 60


def _text_key(campaign_id: uuid.UUID | str) -> str:
    return f"campaign:text:{campaign_id}"


def _revoke_key(campaign_id: uuid.UUID | str) -> str:
    return f"campaign:revoke:{campaign_id}"


def set_text(campaign_id: uuid.UUID | str, text: str) -> None:
    """
    Kampaniya matnini Redis ga yozadi. Bot tahrirda DB commit bilan birga
    chaqiriladi. Redis xatolari yashiriladi (DB hamisha source of truth).
    """
    try:
        r = get_redis()
        r.setex(_text_key(campaign_id), _TEXT_TTL_SECONDS, text)
    except Exception as exc:
        logger.warning("set_text failed cid=%s: %s", campaign_id, exc)


def get_text(r: redis.Redis, campaign_id: uuid.UUID | str) -> str | None:
    """
    Redis dan kampaniya matnini o'qiydi. Worker har iteration da chaqiradi.
    ``None`` qaytsa, DB qiymati ishlatiladi (fallback).
    """
    try:
        v = r.get(_text_key(campaign_id))
        if v is None:
            return None
        return v if isinstance(v, str) else v.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("get_text failed cid=%s: %s", campaign_id, exc)
        return None


def clear_text(campaign_id: uuid.UUID | str) -> None:
    try:
        get_redis().delete(_text_key(campaign_id))
    except Exception:
        pass


def set_revoke(campaign_id: uuid.UUID | str, reason: str = "edit") -> None:
    """
    "Bu round grace ichida tugasin" signali. Bot ``delete_all``,
    ``update_message_text`` yoki ``stop_campaign`` da chaqiradi.
    """
    try:
        get_redis().setex(_revoke_key(campaign_id), _REVOKE_TTL_SECONDS, reason)
    except Exception as exc:
        logger.warning("set_revoke failed cid=%s: %s", campaign_id, exc)


def is_revoked(r: redis.Redis, campaign_id: uuid.UUID | str) -> bool:
    """Worker har iteration da bu kalitni tekshiradi."""
    try:
        return bool(r.exists(_revoke_key(campaign_id)))
    except Exception:
        return False


def clear_revoke(campaign_id: uuid.UUID | str) -> None:
    """
    Worker round tugashi bilan revoke signalini tozalaydi. Foydalanuvchi
    keyingi tahrir kiritmaguncha yana ishlashi uchun.
    """
    try:
        get_redis().delete(_revoke_key(campaign_id))
    except Exception:
        pass
