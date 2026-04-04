# Telegram avtopost SaaS — integratsiyalangan tizim

**Database (PostgreSQL)** + **Worker (Celery)** + **Scheduler (Celery Beat)** + **Telegram bot (aiogram)** + **API (FastAPI)** + **Telethon engine** bitta loyihada birlashtirilgan.

> **Muhim:** guruhlarga yuborish **MTProto userbot** (Telethon) orqali; **Bot API** faqat boshqaruv boti uchun. Spam va qoidalar buzilishiga olib kelishi mumkin — faqat ruxsat berilgan auditoriya uchun.

---

## 1. Modullar qanday bog‘langan

| Modul | Rol | Texnologiya |
|--------|-----|-------------|
| **Database** | Foydalanuvchilar, akkauntlar, kampaniyalar, `schedules.next_run_at`, `send_logs` | PostgreSQL + SQLAlchemy (`app/db/`) |
| **Scheduler** | Vaqt bo‘yicha navbat — qaysi kampaniya ishga tushishi | **Celery Beat** (`worker/celery_app.py` → `beat_schedule`) |
| **Worker** | Reja bo‘yicha vazifalar: kampaniya aylanmasi, login kodlari | **Celery worker** (`worker/tasks.py`) |
| **Telegram bot** | `/start`, tarif/to‘lov, kampaniya (inline guruhlar), admin (`ADMIN_TELEGRAM_IDS`), video qo‘llanma | **aiogram** (`bot/`) — DB + Celery |
| **API** | Health, ichki admin (ixtiyoriy) | **FastAPI** (`app/main.py`) |

### Ma’lumot oqimi (qisqa)

```mermaid
sequenceDiagram
  participant U as Foydalanuvchi
  participant Bot as Aiogram bot
  participant DB as PostgreSQL
  participant Beat as Celery Beat
  participant Redis as Redis
  participant W as Celery worker
  participant TG as Telethon MTProto

  U->>Bot: Kampaniya / akkaunt
  Bot->>DB: INSERT/UPDATE
  Bot->>Redis: Celery task (login)
  W->>TG: send_code / sign_in

  Beat->>Redis: har ~30s schedule_due_campaigns
  W->>DB: next_run_at bo'yicha kampaniyalar
  W->>Redis: process_campaign task_id
  W->>TG: guruhlarga xabar
  W->>DB: send_logs, schedules
```

1. **Scheduler (Beat)** har ~30 soniyada `schedule_due_campaigns` ni ishga tushiradi.
2. Vazifa `schedules.next_run_at <= now` va `campaigns.status = running` bo‘lgan kampaniyalarni topadi, `process_campaign` ni Redis orqali **navbatga** qo‘yadi (`task_id` bilan dublikat kamaytiriladi).
3. **Worker** `process_campaign` ichida Telethon bilan yuboradi, `send_logs` va keyingi `next_run_at` ni yangilaydi.
4. **Bot** foydalanuvchi va kampaniyani DB ga yozadi; **login** uchun `send_login_code_task` / `complete_login_task` Redis orqali worker da bajariladi.

---

## 2. Dependencylar

### Python ( `requirements.txt` )

| Guruh | Paketlar |
|--------|----------|
| API | `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `python-multipart` |
| DB | `sqlalchemy>=2.0`, `psycopg2-binary` |
| Navbat | `celery[redis]`, `redis` |
| Telegram | `telethon`, `aiogram`, `PySocks` |
| Xavfsizlik | `python-dotenv`, `cryptography` |

**Talab:** Python **3.11+** (tavsiya **3.12**). SQLAlchemy **2.x** (`Mapped` va boshqalar uchun).

### Tashqi servislar

| Servis | Port (default) | Vazifa |
|--------|----------------|--------|
| PostgreSQL | 5432 | Ma’lumotlar |
| Redis | 6379 | Celery broker + backend + login kutilishi |

### Docker rasmlar

`postgres:16-alpine`, `redis:7-alpine`, loyiha uchun bitta `Dockerfile` (barcha servislar bir image).

---

## 3. Muhit o‘zgaruvchilari ( `.env` )

`cp .env.example .env` qiling va to‘ldiring:

| O‘zgaruvchi | Majburiy | Tavsif |
|-------------|----------|--------|
| `DATABASE_URL` | Ha | `postgresql+psycopg2://user:pass@host:5432/db` |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Ha | Oddiy holda Redis DB 0/1/2 |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Ha (worker + login) | [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | Ha (bot) | @BotFather |
| `FERNET_KEY` | Ha (session shifrlash) | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `INTERNAL_API_SECRET` | Ha (API himoyasi) | Uzoq tasodifiy qator |
| `ADMIN_TELEGRAM_IDS` | Yo‘q (bot ichidagi admin panel uchun) | Telegram **user id** lar, vergul bilan: `123,456` |
| `TARIFF_1_MONTH_UZS`, `TARIFF_6_MONTH_UZS`, `TARIFF_12_MONTH_UZS` | Yo‘q | Tarif narxlari (so‘m, faqat matn va tanlov) |
| `PAYMENT_INSTRUCTIONS_TEXT` | Yo‘q | To‘lov rekvizitlari va ko‘rsatma (uzun matn) |

**Obuna va to‘lov:** foydalanuvchi tarifni tanlab skrinshot yuboradi; admin bot ichida tasdiqlaydi. **Bitta aktiv kampaniya:** yangisi ishga tushganda qolganlari `paused` holatga o‘tadi. **Celery Beat** `expire_subscriptions` vazifasi (soatiga marta) obunasi tugagan foydalanuvchilarning ishlayotgan kampaniyalarini to‘xtatadi va xabar yuboradi.

**Mavjud PostgreSQL (prod):** yangi ustunlar va `payment_requests` uchun bir marta `scripts/migrate_saas_v1.sql` ni ishlating (`psql $DATABASE_URL -f scripts/migrate_saas_v1.sql`). Keyin `payment_requests.contact_phone` uchun `scripts/migrate_saas_v2_contact_phone.sql` ni bir marta ishlating. Yangi o‘rnatishda `python -m scripts.init_db` (yangilangan `schema.sql`) yetarli.

---

## 4. Lokal ishga tushirish (to‘liq zanjir)

Loyiha **ildizidan** ishlang (`PYTHONPATH` odatda ildiz bo‘ladi).

### 4.1 PostgreSQL va Redis

O‘zingizda ishga tushiring yoki Docker:

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=autopost -p 5432:5432 postgres:16-alpine
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 4.2 O‘rnatish va jadval

```bash
pip install -r requirements.txt
cp .env.example .env
# .env ni tahrirlang — localhost uchun DATABASE_URL va Redis URL lar

python -m scripts.init_db
```

Alternativa: `psql ... -f schema.sql`

### 4.3 To‘rt jarayon (alohida terminal)

| # | Buyruq | Tavsif |
|---|--------|--------|
| 1 | `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | API + health |
| 2 | `celery -A worker.celery_app:celery_app worker -l info` | Telethon vazifalari |
| 3 | `celery -A worker.celery_app:celery_app beat -l info` | **Scheduler** |
| 4 | `python -m bot.main` | Boshqaruv boti |

**Tekshiruv:** `GET http://localhost:8000/health` va `GET http://localhost:8000/api/v1/health/ready` (DB + Redis).

**Makefile** (Git Bash / WSL):

```bash
make install
make init-db
make run-api    # alohida terminalda
make run-worker
make run-beat
make run-bot
```

---

## 5. Docker (barcha servislar birga)

```bash
cp .env.example .env
# TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_TOKEN, FERNET_KEY, INTERNAL_API_SECRET

docker compose build
docker compose up -d
```

**Birinchi marta jadval:**

```bash
docker compose run --rm api python -m scripts.init_db
```

Servislar: `db`, `redis`, `api` (8000), `worker`, `beat` (scheduler), `bot`.

Loglar: `docker compose logs -f worker beat bot`

---

## 6. Modul papkalari

| Papka | Mazmun |
|--------|--------|
| `app/` | FastAPI, `db/models`, servislar, analytics |
| `bot/` | Aiogram — bot UI |
| `worker/` | Celery ilova + **Beat jadvali (scheduler)** |
| `engine/` | Telethon: client, login, yuborish, anti-ban |
| `scripts/` | `init_db` |
| `schema.sql` | SQL DDL (ixtiyoriy import) |

---

## 7. API (ixtiyoriy)

`/api/v1/*` ichki endpointlar (`users`, `campaigns`, `admin`, `analytics`, `health`) `X-Internal-Secret` bilan himoyalangan.

---

## 8. Muammolar

| Simptom | Tekshirish |
|---------|------------|
| Bot javob bermaydi | `BOT_TOKEN`, `db` ishlayaptimi, `bot` konteyner loglari |
| Kampaniya yuborilmaydi | `worker` + `beat` ishlayaptimi, `campaigns.status=running`, `schedules.next_run_at` |
| Login ishlamaydi | `TELEGRAM_API_ID/HASH`, `FERNET_KEY`, Redis, worker loglari |
| Import xatosi | `sqlalchemy>=2.0`, loyiha ildizidan ishga tushirish |

---

## 9. Qisqa xulosa

- **Scheduler** = **Celery Beat** (`beat` servisi) — Redis orqali worker ga yuborish vaqtlarini boshqaradi.
- **Worker** = **Celery worker** — Telethon va DB bilan haqiqiy ishni bajaradi.
- **Database** = barcha modullar uchun yagona manba — bot va worker bir xil `DATABASE_URL` dan foydalanadi.
- **Telegram bot** = foydalanuvchi interfeysi; yuborish **worker + engine** da.
