"""
Distributed lock (fencing token + heartbeat) for campaign execution.

WHY
---
Joriy implementatsiya ``SET NX EX 1800`` bilan oddiy lock ishlatadi. Muammolar:

1. Worker crash bo'lsa (OOM, SIGKILL by Celery time_limit, container restart)
   ``finally: _release_campaign_lock`` bajarilmaydi. Natija: lock **to'liq 30
   daqiqa** qolib ketadi va ushbu vaqt ichida kampaniya uchun hech qanday
   round ishga tushmaydi. Foydalanuvchi simptomi: "bot 1-2 ta tashlab keyin
   jim bo'lib qoldi".

2. Agar TTL ni kichik qilsak (masalan 60s), uzoq round paytida TTL tugab
   boshqa worker lockni o'g'irlab olishi mumkin -> ikki parallel send ->
   akkaunt banlanadi.

YECHIM
------
Fencing-token + heartbeat pattern (Martin Kleppmann taklifiga moslashtirilgan):

- Lock olinganda tasodifiy ``token`` (uuid4) yaratiladi va Redis ga yoziladi.
- Worker har ``heartbeat_interval`` soniyada lockni ``XX`` flagi bilan yangilaydi
  (faqat hozirgi qiymat bizniki bo'lsa TTL yangilanadi). Bu Lua orqali atomik.
- Worker graceful release'da Lua bilan ``if GET==token then DEL`` -> boshqa
  workerning lockni tasodifan o'chirmaymiz.
- Worker crash bo'lsa, heartbeat to'xtaydi, TTL tugaydi (masalan 60s), boshqa
  worker yangi token bilan lockni qo'lga kiritadi.

Bu orqali crash recovery vaqti 30 min dan 60s gacha qisqaradi, va split-brain
himoyalangan qoladi.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass

import redis

logger = logging.getLogger(__name__)

# Atomik release: faqat token mos kelsa DEL qilamiz.
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# Atomik heartbeat: faqat token mos kelsa TTL ni yangilaymiz (lockni o'ziniki
# deb bilsa). Boshqa worker olgan bo'lsa biz TTL ga tegmaymiz.
_HEARTBEAT_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""


@dataclass
class HeldLock:
    """Qo'lga kiritilgan distributed lock holati."""

    key: str
    token: str
    ttl_ms: int
    heartbeat_interval_s: float

    _stop: threading.Event
    _thread: threading.Thread | None


def acquire(
    r: redis.Redis,
    key: str,
    *,
    ttl_ms: int = 60_000,
    heartbeat_interval_s: float = 20.0,
) -> HeldLock | None:
    """
    Fencing token bilan lock olish. Muvaffaqiyat bo'lsa ``HeldLock`` qaytaradi va
    background heartbeat thread ishga tushadi. Aks holda ``None``.

    Default TTL 60 soniya: worker crash bo'lsa maksimum shuncha kutiladi.
    Heartbeat har 20 soniyada TTL ni yangilaydi, demak soatlab ishlaydigan
    roundlar ham bemalol o'tadi.
    """
    token = uuid.uuid4().hex
    ok = r.set(key, token, nx=True, px=ttl_ms)
    if not ok:
        return None

    stop = threading.Event()

    def _heartbeat_loop() -> None:
        script = r.register_script(_HEARTBEAT_SCRIPT)
        # Birinchi tick'ni darhol emas, intervaldan keyin bajaramiz -> ortiqcha
        # network roundtripni oldini olamiz.
        while not stop.wait(heartbeat_interval_s):
            try:
                res = script(keys=[key], args=[token, ttl_ms])
                if not res:
                    # Lock biznikidan boshqaniki bo'lib qolgan bo'lsa, heartbeat
                    # to'xtaydi. Bu holat odatda TTL mayda sozlanganda yuz beradi.
                    logger.warning(
                        "lock_heartbeat_lost key=%s token=%s", key, token,
                    )
                    return
            except Exception as exc:
                # Redis muvaqqat uzilishi — keyingi tickda qayta urinamiz.
                logger.warning("lock_heartbeat_error key=%s: %s", key, exc)

    thread = threading.Thread(
        target=_heartbeat_loop,
        name=f"lock-hb-{key}",
        daemon=True,
    )
    thread.start()

    return HeldLock(
        key=key,
        token=token,
        ttl_ms=ttl_ms,
        heartbeat_interval_s=heartbeat_interval_s,
        _stop=stop,
        _thread=thread,
    )


def release(r: redis.Redis, held: HeldLock) -> bool:
    """Heartbeatni to'xtatib, tokenni atomik tekshirib lockni bo'shatadi."""
    # Avval heartbeat thread'ni to'xtatamiz -> release paytida parallel
    # heartbeat lockni qayta yangilamaydi.
    held._stop.set()
    if held._thread is not None:
        held._thread.join(timeout=held.heartbeat_interval_s + 1.0)

    try:
        script = r.register_script(_RELEASE_SCRIPT)
        n = int(script(keys=[held.key], args=[held.token]) or 0)
        return n > 0
    except Exception as exc:
        logger.warning("lock_release_error key=%s: %s", held.key, exc)
        return False


def force_release_if_held(r: redis.Redis, key: str, token: str) -> bool:
    """
    Bir qayta-ishlashda alohida kerak bo'lganda (recovery skriptlar uchun)
    berilgan token bilan lockni bo'shatish.
    """
    try:
        script = r.register_script(_RELEASE_SCRIPT)
        return bool(script(keys=[key], args=[token]))
    except Exception:
        return False


def wait_until_free(
    r: redis.Redis,
    key: str,
    *,
    timeout_s: float = 5.0,
    poll_s: float = 0.2,
) -> bool:
    """
    Key bo'shaguncha (``EXISTS == 0``) kutadi. Timeout'gacha bo'shasa True,
    aks holda False. Bot handlerlarida "tozalashdan oldin ishlayotgan roundga
    revoke signali yuborib, uning tugashini kutish" uchun foydalidir.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if not r.exists(key):
                return True
        except Exception:
            return False
        time.sleep(poll_s)
    return not bool(r.exists(key))
