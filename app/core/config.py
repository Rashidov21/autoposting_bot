from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "autopost-saas"
    debug: bool = False

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/autopost"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout: int = Field(default=30, ge=5)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_ignore_result: bool = True
    celery_result_expires_seconds: int = Field(default=3600, ge=300, le=172800)
    celery_default_queue: str = "default"
    celery_campaign_queue: str = "campaign"
    celery_scheduler_queue: str = "scheduler"
    celery_worker_prefetch_multiplier: int = Field(default=1, ge=1, le=8)
    celery_worker_max_tasks_per_child: int = Field(default=30, ge=1, le=500)
    celery_worker_max_memory_per_child_kb: int = Field(default=450_000, ge=128_000, le=2_000_000)

    telegram_api_id: int = 0
    telegram_api_hash: str = ""

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def _coerce_api_id(cls, v):
        if v is None or v == "":
            return 0
        return int(v)

    bot_token: str = ""

    fernet_key: str = ""
    internal_api_secret: str = "change-me"
    sessions_dir: Path = Path("./sessions")

    # Admin Telegram ID lar (vergul bilan) — /admin panel
    admin_telegram_ids: str = ""
    # Yangi foydalanuvchi uchun avtomatik qo'shiladigan default guruhlar (vergul bilan)
    default_group_chat_ids: str = ""

    # To'lov — foydalanuvchiga ko'rsatiladigan qo'shimcha matn (ixtiyoriy)
    payment_instructions_text: str = ""

    # Demo — yangi foydalanuvchi uchun bepul muddat (soat)
    demo_hours: int = Field(default=24, ge=1, le=720)

    # Tarif summalari (so'm) — .env da
    tariff_1_month_uzs: int = Field(default=25_000, ge=0)
    tariff_6_month_uzs: int = Field(default=120_000, ge=0)
    tariff_12_month_uzs: int = Field(default=210_000, ge=0)

    # To'lov kartasi / rekvizit (ko'rsatiladi)
    payment_card_number: str = ""

    # Telethon — ulanish va qayta urinish (production)
    telethon_connection_retries: int = Field(default=3, ge=1, le=10)
    telethon_retry_delay: int = Field(default=2, ge=1, le=30)
    telethon_timeout: int = Field(default=60, ge=10, le=300)

    # Yuborish — performance va barqarorlik
    sender_log_commit_batch: int = Field(default=12, ge=1, le=500)
    schedule_due_campaigns_batch_limit: int = Field(default=300, ge=10, le=5000)
    campaign_lock_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    campaign_soft_time_limit_seconds: int = Field(default=2400, ge=60, le=7200)
    campaign_time_limit_seconds: int = Field(default=3600, ge=120, le=10800)

    # Anti-ban — xatti-harakat va kontent
    typing_simulation_probability: float = Field(default=0.82, ge=0.0, le=1.0)
    post_typing_pause_factor: float = Field(default=0.55, ge=0.2, le=1.0)

    @property
    def admin_telegram_id_set(self) -> frozenset[int]:
        return frozenset(parse_admin_telegram_ids(self.admin_telegram_ids))

    @property
    def default_group_chat_id_list(self) -> list[int]:
        return parse_int_csv(self.default_group_chat_ids)

    @property
    def telethon_api(self) -> tuple[int, str]:
        if not self.telegram_api_id or not self.telegram_api_hash:
            raise RuntimeError("TELEGRAM_API_ID va TELEGRAM_API_HASH ni sozlang")
        return self.telegram_api_id, self.telegram_api_hash


def parse_int_csv(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def parse_admin_telegram_ids(raw: str) -> list[int]:
    return parse_int_csv(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()
