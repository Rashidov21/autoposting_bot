-- Migration 0002: Per-(account, group) blocklist
--
-- WHY
-- ---
-- Hozirgi ``engine/sender.py`` ``ChatWriteForbidden``, ``ChannelPrivate``,
-- ``ChatAdminRequired`` xatolarida ``groups.is_valid=FALSE`` qilib global
-- invalid belgilab qo'yadi. Ammo bu xatolar **akkaunt-guruh** darajasidagi
-- holat — bir akkaunt guruhga a'zo emas, ammo boshqa akkaunt a'zo bo'lishi
-- mumkin. Global belgilash barcha akkauntlar uchun guruhni o'chiradi va
-- foydalanuvchilarning "ba'zi akkauntlarda ishlaydi, ba'zida yo'q" degan
-- shikoyatini keltirib chiqaradi.
--
-- Ushbu migration alohida ``account_group_blocklist`` jadvalini yaratadi:
-- har bir (account_id, group_id) juftligi mustaqil ravishda bloklanadi.
-- ``groups.is_valid`` endi faqat "guruh Telegramdan tamomila yo'qolgan"
-- (ChatIdInvalid, PeerIdInvalid) holati uchun ishlatiladi.
--
-- ROLLBACK
-- --------
-- DROP TABLE IF EXISTS account_group_blocklist;
--
-- Ishga tushirish (VPS da):
--   docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB \
--       -f /migrations/0002_account_group_blocklist.sql
-- yoki:
--   psql "$DATABASE_URL" -f migrations/0002_account_group_blocklist.sql

CREATE TABLE IF NOT EXISTS account_group_blocklist (
    account_id   UUID        NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    group_id     UUID        NOT NULL REFERENCES groups(id)   ON DELETE CASCADE,
    reason       VARCHAR(64) NOT NULL,
    error_message TEXT,
    blocked_until TIMESTAMPTZ,   -- NULL = permanent; future timestamp = temporary
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_account_group_blocklist_account
    ON account_group_blocklist (account_id);

CREATE INDEX IF NOT EXISTS idx_account_group_blocklist_group
    ON account_group_blocklist (group_id);

-- Qo'shimcha: sender auth drift detektsiyasini yozish uchun status kolonkasi
-- allaqachon mavjud (pending_login/active/banned). Shu bilan birga
-- ``reauth_required`` holatini qo'llab-quvvatlash uchun hech qanday schema
-- o'zgarishi shart emas — ``accounts.status`` VARCHAR(32) ga mos.
