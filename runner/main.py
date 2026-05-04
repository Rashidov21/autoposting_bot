from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import uuid

from app.core.config import get_settings
from app.db.session import SessionLocal
from engine.redis_pool import get_redis
from engine.sender import run_campaign_round_async
from engine.telethon_pool import TelethonClientPool

logger = logging.getLogger(__name__)


async def _consume_loop(pool: TelethonClientPool, stop: asyncio.Event) -> None:
    settings = get_settings()
    r = get_redis()
    key = settings.session_runner_queue_key
    while not stop.is_set():
        try:
            popped = await asyncio.to_thread(r.brpop, key, 5)
        except Exception:
            logger.exception("session_runner brpop failed")
            await asyncio.sleep(2.0)
            continue
        if not popped:
            continue
        _, raw = popped
        try:
            data = json.loads(raw)
            cid = uuid.UUID(data["campaign_id"])
        except Exception as e:
            logger.warning("session_runner bad_message raw=%r err=%s", raw, e)
            continue
        db = SessionLocal()
        try:
            await run_campaign_round_async(db, cid, client_pool=pool)
        except Exception:
            logger.exception("session_runner round failed campaign=%s", cid)
        finally:
            db.close()


async def _amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    pool = TelethonClientPool()
    stop = asyncio.Event()

    def _handle_sig(*_: object) -> None:
        stop.set()

    try:
        signal.signal(signal.SIGINT, _handle_sig)
        signal.signal(signal.SIGTERM, _handle_sig)
    except ValueError:
        # Windows yoki boshqa muhitda signal sinxron emas
        pass

    consumer = asyncio.create_task(_consume_loop(pool, stop))
    await stop.wait()
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    await pool.disconnect_all()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
