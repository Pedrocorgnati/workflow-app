# DB Migration Report — Workflow App

Projeto: workflow-app
ORM: Alembic + SQLAlchemy 2.x
Database: SQLite (WAL mode)
Gerado em: 2026-03-15

---

## Status Geral

| Item | Status |
|------|--------|
| Migration 0001 (schema completo) | ✅ Existente |
| Cobertura vs models.py | ✅ 100% — zero delta |
| Alembic configurado (alembic.ini + env.py) | ✅ |
| render_as_batch=True (SQLite ALTER TABLE) | ✅ |
| DB inicializado via Alembic | ⚠️ create_all() direto |

---

## Migrations Existentes

| # | Arquivo | Operação | Tabelas Afetadas | Reversível |
|---|---------|----------|-----------------|------------|
| 1 | `20260311_0001_initial_schema.py` | CREATE TABLE (6x) | templates, template_commands, pipeline_executions, command_executions, app_configs, execution_logs | Sim |

---

## Entidades Cobertas pela Migration 0001

| Tabela | Colunas | Indexes | FKs | Downgrade |
|--------|---------|---------|-----|-----------|
| `templates` | id, name, description, template_type, is_factory, sha256, created_at, updated_at | — | — | ✅ |
| `template_commands` | id, template_id, position, command_name, model_type, interaction_type, estimated_seconds, is_optional | `ix_template_commands_template_id` | templates(id) CASCADE | ✅ |
| `pipeline_executions` | id, template_id, project_config_path, status, permission_mode, commands_total/completed/failed/skipped, tokens_input/output, cost_usd, started_at, completed_at, created_at | `ix_pipeline_executions_status_started` | templates(id) SET NULL | ✅ |
| `command_executions` | id, pipeline_id, position, command_name, model, interaction_type, status, is_optional, output_text, error_message, tokens_input/output, elapsed_seconds, started_at, completed_at, created_at | `ix_command_executions_pipeline_position` | pipeline_executions(id) CASCADE | ✅ |
| `app_configs` | id, key, value, updated_at | — | — | ✅ |
| `execution_logs` | id, pipeline_id, command_execution_id, level, message, summary_content, export_path, created_at | `ix_execution_logs_pipeline_timestamp` | pipeline_executions(id) CASCADE, command_executions(id) SET NULL | ✅ |

---

## Ordem de Execução

Para evitar violações de FK:

1. `templates` (sem dependências)
2. `app_configs` (sem dependências)
3. `template_commands` → depende de `templates`
4. `pipeline_executions` → depende de `templates`
5. `command_executions` → depende de `pipeline_executions`
6. `execution_logs` → depende de `pipeline_executions` + `command_executions`

---

## Comandos de Aplicação

### Instalação Nova (sem DB existente)

```bash
cd ai-forge/workflow-app

# Opção A — via Alembic (recomendado para rastreamento de versão)
DB_PATH=~/.workflow-app/workflow.db alembic upgrade head

# Opção B — via create_all() (comportamento atual do DatabaseManager.setup())
# Executado automaticamente ao iniciar o app
```

### DB Existente criado via create_all() — Stamp

Se o banco já existe (criado pelo `DatabaseManager.setup()` via `create_all()`),
o Alembic não sabe que a migration 0001 já foi aplicada. Execute o stamp:

```bash
cd ai-forge/workflow-app
DB_PATH=~/.workflow-app/workflow.db alembic stamp 0001
```

Isso grava a versão atual na tabela `alembic_version` sem re-executar as migrations.
Após o stamp, novas migrations futuras podem ser aplicadas normalmente.

### Verificar versão atual

```bash
DB_PATH=~/.workflow-app/workflow.db alembic current
```

### Produção

```bash
# 1. Faça backup do banco antes
cp ~/.workflow-app/workflow.db ~/.workflow-app/workflow.db.bak_$(date +%Y%m%d_%H%M%S)

# 2. Aplique as migrations
DB_PATH=~/.workflow-app/workflow.db alembic upgrade head

# 3. Verifique
DB_PATH=~/.workflow-app/workflow.db alembic current
```

---

## Rollback

Para reverter a migration 0001 (ATENÇÃO: destrói todos os dados):

```bash
# PERIGO — remove TODAS as tabelas
DB_PATH=~/.workflow-app/workflow.db alembic downgrade base
```

---

## Geração de Novas Migrations

Ao adicionar/alterar modelos em `src/workflow_app/db/models.py`:

```bash
cd ai-forge/workflow-app

# Gerar migration com autogenerate (detecta diff entre models e DB)
DB_PATH=~/.workflow-app/workflow.db alembic revision --autogenerate -m "descricao_da_mudanca"

# Revisar o arquivo gerado em alembic/versions/
# Aplicar
DB_PATH=~/.workflow-app/workflow.db alembic upgrade head
```

**Nota SQLite:** `render_as_batch=True` está configurado no `env.py`. Isso é necessário
porque SQLite não suporta `ALTER COLUMN` / `DROP COLUMN` nativamente — Alembic emula
essas operações via CREATE TABLE + COPY + DROP + RENAME.

---

## Checklist de Segurança

| Item | Status |
|------|--------|
| Migration 0001 tem downgrade() completo | ✅ |
| Colunas NOT NULL novas têm DEFAULT | ✅ |
| FKs têm ON DELETE explícito | ✅ (CASCADE ou SET NULL) |
| Indexes criados para todas as FKs | ✅ |
| render_as_batch=True configurado para SQLite | ✅ |
| Idempotência via checkfirst=True no create_all | ✅ |

---

## Alerta: create_all() vs Alembic

**Situação atual:** `DatabaseManager.setup()` chama `Base.metadata.create_all(engine, checkfirst=True)` diretamente, sem passar pelo Alembic.

**Implicação:** A tabela `alembic_version` não é criada automaticamente, portanto `alembic current` retornará vazio em bancos existentes.

**Solução para DBs novos:** considere chamar `alembic upgrade head` no `DatabaseManager.setup()` no lugar de `create_all()`, ou manter o padrão atual e executar o stamp manualmente após o primeiro boot.

---

## Seed de Dados

O seed de factory templates é feito programaticamente pelo `DatabaseManager._seed_initial_data()`,
que chama `seed_factory_templates()` — função idempotente que verifica existência antes de inserir.

8 factory templates são criados na primeira execução:
`JSON`, `Brief: New`, `Brief: Feature`, `Modules`, `Deploy`, `Daily`, `Marketing`, `Business`

Não há migration Alembic para seed de dados — comportamento intencional, pois os templates
são versionados pelo SHA-256 do CLAUDE.md e atualizados via `refresh_factory_templates()`.
