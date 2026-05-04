from __future__ import annotations

import logging
import time
import uuid

import redis

logger = logging.getLogger(__name__)


def wait_account_send_slot_sync(
    redis_client: redis.Redis,
    account_id: uuid.UUID,
    max_sends_per_minute: int,
) -> None:
    """
    Redis orqali akkaunt bo'yicha daqiqalik oynada yuborishlar sonini cheklaydi.
    ``max_sends_per_minute`` <= 0 bo'lsa hech narsa qilmaydi.
    """
    if max_sends_per_minute <= 0:
        return
    while True:
        window = int(time.time()) // 60
        key = f"sender:rl:{account_id}:{window}"
        n = redis_client.incr(key)
        if n == 1:
            redis_client.expire(key, 75)
        if n <= max_sends_per_minute:
            return
        redis_client.decr(key)
        now = time.time()
        sleep_s = max(0.05, 60.0 - (now % 60.0) + 0.05)
        logger.debug(
            "account_send_rate_wait account=%s sleep_s=%.2f",
            account_id,
            sleep_s,
        )
        time.sleep(sleep_s)
