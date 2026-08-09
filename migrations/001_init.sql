-- CortexOne schema. Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS users (
    id               BIGSERIAL PRIMARY KEY,
    email            TEXT        NOT NULL,
    email_normalized TEXT        NOT NULL UNIQUE,
    password_hash    TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sidebar query: a user's conversations, most recently active first.
CREATE INDEX IF NOT EXISTS conversations_user_updated_idx
    ON conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    -- Denormalised from conversations so the rate-limit count and every
    -- ownership check can be answered without a join.
    user_id         BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Transcript replay, in insertion order.
CREATE INDEX IF NOT EXISTS messages_conversation_idx
    ON messages (conversation_id, id);

-- Rolling-window rate limit.
CREATE INDEX IF NOT EXISTS messages_user_created_idx
    ON messages (user_id, created_at DESC);
