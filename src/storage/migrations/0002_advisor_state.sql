-- Estado da sessão do Agente Conselheiro (docs/arquitetura-agentes.md) e a
-- marcação de qual agente gerou cada mensagem. Colunas novas, `IF NOT EXISTS`
-- pelo mesmo motivo do 0001: é seguro reaplicar contra produção.

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS advisor_state JSONB;
ALTER TABLE messages      ADD COLUMN IF NOT EXISTS agent TEXT;
