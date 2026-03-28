-- PostgreSQL schema: Telegram automation SaaS (userbot MTProto)
-- Run: psql $DATABASE_URL -f schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL UNIQUE,
    username VARCHAR(255),
    full_name VARCHAR(512),
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_users_telegram_id ON users (telegram_id);

CREATE TABLE proxies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label VARCHAR(255),
    proxy_type VARCHAR(32) NOT NULL, -- socks5, http, mtproxy
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,
    username VARCHAR(255),
    password_enc TEXT,
    secret VARCHAR(255),
    is_healthy BOOLEAN NOT NULL DEFAULT TRUE,
    last_error TEXT,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_proxies_user_id ON proxies (user_id);

CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    proxy_id UUID REFERENCES proxies(id) ON DELETE SET NULL,
    phone VARCHAR(32),
    session_enc TEXT, -- encrypted StringSession or path reference
    session_path VARCHAR(512),
    status VARCHAR(32) NOT NULL DEFAULT 'pending_login',
    flood_wait_until TIMESTAMPTZ,
    max_groups_limit INTEGER NOT NULL DEFAULT 8,
    warm_up_sent INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_accounts_user_id ON accounts (user_id);
CREATE INDEX ix_accounts_status ON accounts (status);

CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    telegram_chat_id BIGINT NOT NULL,
    title VARCHAR(512),
    username VARCHAR(255),
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    last_error TEXT,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, telegram_chat_id)
);
CREATE INDEX ix_groups_user_id ON groups (user_id);
CREATE INDEX ix_groups_valid ON groups (user_id, is_valid);

CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Campaign',
    message_text TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes IN (3, 5, 10, 15)),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    rotation VARCHAR(32) NOT NULL DEFAULT 'round_robin',
    skip_group_probability DOUBLE PRECISION NOT NULL DEFAULT 0.08,
    min_delay_seconds DOUBLE PRECISION NOT NULL DEFAULT 3.0,
    max_delay_seconds DOUBLE PRECISION NOT NULL DEFAULT 18.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_campaigns_user_id ON campaigns (user_id);
CREATE INDEX ix_campaigns_status ON campaigns (status);

CREATE TABLE campaign_groups (
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, group_id)
);

CREATE TABLE campaign_accounts (
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, account_id)
);

CREATE TABLE schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    next_run_at TIMESTAMPTZ NOT NULL,
    last_run_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_schedules_next_run ON schedules (next_run_at);

CREATE TABLE send_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
    group_id UUID REFERENCES groups(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    meta JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_send_logs_campaign ON send_logs (campaign_id, created_at DESC);
CREATE INDEX ix_send_logs_account ON send_logs (account_id, created_at DESC);
CREATE INDEX ix_send_logs_created ON send_logs (created_at DESC);

CREATE TABLE system_settings (
    key VARCHAR(128) PRIMARY KEY,
    value_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_settings (key, value_json) VALUES
  ('bot_enabled', 'true'::jsonb),
  ('maintenance_message', 'null'::jsonb)
ON CONFLICT (key) DO NOTHING;
