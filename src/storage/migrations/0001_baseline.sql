-- Schema base do app (users, invite_codes, conversations, messages).
--
-- Idempotente de propósito: `CREATE TABLE IF NOT EXISTS`, sem nenhum DROP.
-- Este arquivo é aplicado à mão contra o Supabase de produção (ver README.md
-- deste diretório) — um DROP aqui apagaria dados reais. Os testes aplicam o
-- mesmo arquivo, então o schema de teste nunca mais diverge do de produção.
--
-- Diferenças propositais em relação à produção: sem RLS (os testes conectam
-- com o dono do banco, para quem o RLS não se aplica de qualquer forma) e sem
-- as tabelas de indexação (run_log, chunks_docx, chunk_stats), que não
-- participam do fluxo de conversas.

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT false,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code       TEXT PRIMARY KEY,
    created_by BIGINT REFERENCES users (id),
    used_by    BIGINT REFERENCES users (id),
    used_at    TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users (id),
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role = ANY (ARRAY['user'::text, 'assistant'::text])),
    content          TEXT NOT NULL,
    search_mode      TEXT,
    retrieved_chunks JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
