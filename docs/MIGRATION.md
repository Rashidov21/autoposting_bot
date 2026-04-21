# Ma’lumotlar bazasi strategiyasi

Loyihada ikki usul mavjud; **prod** da bittasini tanlang va boshqa yo‘lni qo‘llamang (CHECK / unique nomosligi oldini olish uchun).

## A) Yangi o‘rnatish: `scripts.init_db` (tavsiya — oddiy)

SQLAlchemy `Base.metadata.create_all` — jadvallar **joriy** `app/db/models.py` bo‘yicha yaratiladi.

```bash
python -m scripts.init_db
```

Docker:

```bash
docker compose run --rm api python -m scripts.init_db
```

Bu yo‘lda `migrations/*.sql` **majburiy emas** (faqat tarixiy yoki qo‘lda patch uchun).

## B) SQL manba: `schema.sql` + `migrations/`

Agar DB ni SQL bilan boshqarish kerak bo‘lsa:

1. `schema.sql` — to‘liq DDL (yangi bo‘sh cluster).
2. Keyin ketma-ket `migrations/0002_*.sql`, `0003_*.sql`, … — mavjud DB ga patch.

**Diqqat:** `schema.sql` bilan jadvallar allaqachon yaratilgan bo‘lsa, `init_db` ni **qayta** ishlatish takroriy indeks/constraint xatolariga olib kelishi mumkin.

## C) Kelajak: Alembic

Agar versiyalashni bir joyda avtomatlashtirish kerak bo‘lsa — Alembic qo‘shish va `migrations/*.sql` ni bosqichma-bosqich `revision` ga o‘tkazish tavsiya etiladi (ushbu hujjat rejaviy).
