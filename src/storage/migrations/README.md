# Migrações

Fonte da verdade do schema do Postgres (Supabase). Os arquivos são aplicados
**à mão** no SQL Editor do Supabase, em ordem de nome de arquivo — `0001_...`
antes de `0002_...`, e assim por diante. Não há ferramenta de migração
automática rodando contra produção.

Cada arquivo é **idempotente**: usa `CREATE TABLE IF NOT EXISTS` e
`ADD COLUMN IF NOT EXISTS`, nunca `DROP`. Isso permite reaplicar um arquivo já
aplicado sem risco, e é o que garante que o schema de teste (aplicado pelo
`tests/conftest.py`, que roda estes mesmos arquivos) nunca diverge do de
produção — antes disso, `tests/schema.sql` era uma réplica mantida à mão e
podia ficar desatualizada.

**Atenção:** até o momento, ninguém aplicou o `0002_advisor_state.sql` no
banco de produção do Supabase. Aplique-o manualmente antes de habilitar o
Agente Conselheiro em produção.
