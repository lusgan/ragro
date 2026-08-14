-- Schema das tabelas do app, usado só pelos testes.
--
-- ATENÇÃO: o schema de produção vive no Supabase e foi criado à mão — este
-- arquivo é uma réplica, não a fonte da verdade. Ele foi extraído do banco real
-- (information_schema) e precisa ser atualizado junto com qualquer alteração
-- feita lá, senão os testes passam contra um schema que não existe mais.
--
-- Diferenças propositais em relação à produção: sem RLS (os testes conectam com
-- o dono do banco, para quem o RLS não se aplica de qualquer forma) e sem as
-- tabelas de indexação (run_log, chunks_docx, chunk_stats), que não participam
-- do fluxo de conversas.

DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS invite_codes CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT false,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE invite_codes (
    code       TEXT PRIMARY KEY,
    created_by BIGINT REFERENCES users (id),
    used_by    BIGINT REFERENCES users (id),
    used_at    TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users (id),
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role = ANY (ARRAY['user'::text, 'assistant'::text])),
    content          TEXT NOT NULL,
    search_mode      TEXT,
    retrieved_chunks JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
