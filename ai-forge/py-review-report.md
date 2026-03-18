# Relatório de Auditoria Python — Workflow App

**Projeto:** workflow-app (PySide6 + SQLAlchemy + SQLite desktop)
**Data:** 2026-03-11
**Versão Python:** 3.11+ (pyproject.toml: `requires-python = ">=3.11"`)
**Stack:** Python, PySide6/Qt6, SQLAlchemy 2.x, SQLite, python-statemachine

---

## Resumo Executivo

| Camada | Sub-comando | Issues | Corrigidos | Pendentes |
|--------|-------------|--------|------------|-----------|
| 1 — Fundação | configuration | 4 | 0 | 4 |
| 1 — Fundação | typing | 3 | 1 | 2 |
| 1 — Fundação | dependencies | 4 | 0 | 4 |
| 2 — Arquitetura | architecture | 2 | 0 | 2 |
| 2 — Arquitetura | hardcodes | 3 | 0 | 3 |
| 3 — Dados | data-handling | 2 | 0 | 2 |
| 4 — Segurança | security | 1 | 0 | 1 |
| 5 — Qualidade | error-handling | 3 | 0 | 3 |
| 5 — Qualidade | testing | 3 | 0 | 3 |
| 6 — Otimização | performance | 1 | 0 | 1 |
| 6 — Otimização | async | 1 | 0 | 1 |
| 6 — Otimização | scalability | 3 | 0 | 3 |
| 7 — DevOps | ci-cd | 5 | 0 | 5 |
| 7 — DevOps | packaging | 3 | 0 | 3 |
| 8 — Frameworks | web-framework | SKIP | — | — |
| 8 — Frameworks | api | SKIP | — | — |
| **TOTAL** | **14 executados** | **38** | **1** | **37** |

**Veredicto:** ✅ App funcional e segura — gaps são de infra dev e código de qualidade, não de corretude.

---

## Issues Críticos (Ação Imediata)

| Prioridade | ID | Descrição | Arquivo |
|------------|----|-----------|---------|
| 🔴 Alto | DEP-002 | `claude-agent-sdk` não declarado em `pyproject.toml` — dependência de runtime invisível | `pyproject.toml` |
| 🔴 Alto | CICD-001 | Nenhum pipeline de CI/CD — sem gate automático de qualidade | `.github/workflows/` (ausente) |
| 🔴 Alto | CICD-002 | Linter não determinístico (`ruff \|\| flake8`) — comportamento varia por ambiente | `Makefile` |
| 🟡 Médio | CONF-001 | `[tool.mypy]`/`[tool.ruff]` ausentes no `pyproject.toml` — configs sem centralização | `pyproject.toml` |
| 🟡 Médio | CONF-002 | `.env.example` ausente — onboarding de novos devs prejudicado | raiz do projeto |
| 🟡 Médio | DEP-001 | Upper bounds ausentes em todas as dependências — exposição a breaking changes | `pyproject.toml` |
| 🟡 Médio | ERH-001 | `except Exception: pass` silencia erros em callbacks críticos | `pipeline_manager.py:348,355,387` |
| 🟡 Médio | ERH-002 | `AppError.cause` não usa `raise ... from exc` — traceback obscurecido | `errors.py` |
| 🟡 Médio | ASYNC-001 | `asyncio.get_event_loop()` deprecado no Python 3.10+ | `sdk_worker.py:118` |
| 🟡 Médio | TEST-001 | Cobertura não medida automaticamente no `make test` | `pyproject.toml`, `Makefile` |

---

## Findings Detalhados por Sub-comando

### 1. configuration — 4 issues (0 corrigidos)

- **CONF-001 (Médio)** — `pyproject.toml` não possui `[tool.mypy]`, `[tool.ruff]` nem `[tool.coverage]`. Apenas `[tool.pytest.ini_options]` presente.
- **CONF-002 (Médio)** — `.env` existe mas `.env.example` não. Novas instalações precisam de documentação das variáveis.
- **CONF-003 (Baixo)** — `AppConfig` usa `_cache: dict` como variável de classe (padrão válido mas não idiomático). Não usa `pydantic_settings.BaseSettings`.
- **CONF-004 (Baixo)** — `pyproject.toml` sem `license`, `authors`, `classifiers`, `project.urls`.

### 2. typing — 3 issues (1 corrigido)

- **TYP-001 ✅ CORRIGIDO** — `db/models.py` usava `from typing import List` (deprecado 3.9+) e `Mapped[List["X"]]`. Corrigido para `Mapped[list["X"]]`. Removido import `List`.
- **TYP-002 (Baixo)** — 15+ arquivos com `Optional[X]` em vez de `X | None`. Todos têm `from __future__ import annotations`, sintaxe `X | None` seria mais moderna.
- **TYP-003 (Baixo)** — `config_bar.py:209`, `sdk_adapter.py:_get_client()` sem hint de retorno. `mypy --strict` não está configurado.

### 3. dependencies — 4 issues (0 corrigidos)

- **DEP-001 (Alto)** — Todas as dependências sem upper bound: `PySide6>=6.6.0`, `SQLAlchemy>=2.0.0`, `alembic>=1.13.0`, `python-statemachine>=2.0.0`, `pyte>=0.8.0`.
- **DEP-002 (Alto)** — `claude-agent-sdk` não declarado em `pyproject.toml`. É dependência de runtime.
- **DEP-003 (Médio)** — Sem `pip-audit`/`safety` configurado para scan de vulnerabilidades.
- **DEP-004 (Baixo)** — `requirements.txt` e `uv.lock` presentes mas processo de geração não documentado.

### 4. architecture — 2 issues (0 corrigidos)

- **ARCH-001 (Baixo)** — `pipeline_manager.py:427` acessa `self._extras._tokens` (atributo privado de outra classe). Quebra encapsulamento.
- **ARCH-002 (Baixo)** — `main_window.py:193` acessa `self._metrics_bar._btn_new.clicked` (atributo privado de widget filho). A separação de camadas em geral está bem estruturada.

### 5. hardcodes — 3 issues (0 corrigidos)

- **HC-001 (Médio)** — `sdk_adapter.py:39-42` — model strings hardcoded: `"claude-haiku-4-5"`, `"claude-sonnet-4-5"`, `"claude-opus-4-5"`. Centralizados no dict `_MODEL_STRINGS` no módulo (adequado), mas sem vínculo com `AppConfig`.
- **HC-002 (Baixo)** — `sdk_worker.py:132` — timeout `300.0` sem constante nomeada. Deveria ser `INTERACTIVE_TIMEOUT_S = 300`.
- **HC-003 (Baixo)** — `main_window.py:82` — cor `"#18181B"` hardcoded, duplicando `tokens.py:COLORS.background`.

### 6. data-handling — 2 issues (0 corrigidos)

- **DH-001 (Médio)** — `token_tracker.py:95-97` usa `session.query(CommandExecution).filter(...)` (ORM legado). Inconsistente com estilo `select()` moderno usado em `template_manager.py`.
- **DH-002 (Baixo)** — `history_manager.py` mistura `.query()` legado com `.execute(select(...))` moderno. Uniformizar para `select()`-based.

### 7. security — 1 issue (0 crítico)

- **SEC-001 (Baixo)** — Zero vulnerabilidades críticas. Sem eval/pickle/os.system/subprocess(shell=True)/MD5 para senhas/YAML inseguro/credenciais hardcoded. `.env` corretamente no `.gitignore`. `.env.example` ausente (cross-ref CONF-002).

### 8. error-handling — 3 issues (0 corrigidos)

- **ERH-001 (Médio)** — `main_window.py:327`, `pipeline_manager.py:348,355,387,436` — `except Exception: pass` sem logging. Silencia erros reais.
- **ERH-002 (Médio)** — `errors.py` — `AppError.cause` não usa `raise AppError(...) from exc`. Rastreamento de causa pode ser obscurecido.
- **ERH-003 (Baixo)** — `sdk_adapter.py:419-428` — `except Exception: pass` em hooks de cleanup sem `logger.debug`.

### 9. testing — 3 issues (0 corrigidos)

- **TEST-001 (Médio)** — `make test` sem `--cov`. Cobertura não medida. Sem `--cov-fail-under` no `pyproject.toml`.
- **TEST-002 (Baixo)** — `test_config_bar.py` emite `RuntimeWarning: Failed to disconnect (None)` em 20 casos. Fixture de teardown frágil.
- **TEST-003 (Baixo)** — `pytest.ini_options` sem `markers`, `filterwarnings`, `asyncio_mode`. Sub-pastas `e2e/` e `integration/` não têm markers para isolamento.

### 10. performance — 1 issue (0 corrigido)

- **PERF-001 (Baixo)** — `history_manager.py` executa 4 round-trips para sumário de histórico (2 `.count()` + 2 queries de dados). Pode ser consolidado. Impacto mínimo em SQLite local.

### 11. async — 1 issue (0 corrigido)

- **ASYNC-001 (Médio)** — `sdk_worker.py:118` — `asyncio.get_event_loop()` deprecado no Python 3.10+. Correto: `asyncio.get_running_loop()` dentro de coroutine.

### 12. scalability — 3 issues (0 corrigidos)

- **SCL-001 (Baixo / N/A desktop)** — Sem health endpoints/métricas/tracing. Esperado para app desktop local.
- **SCL-002 (Baixo)** — `signal_bus` singleton global importado diretamente em `MainWindow` e `OutputPanel`. Em cenários multi-janela futuro, preferir injeção explícita (já usada no `PipelineManager`).
- **SCL-003 (Baixo)** — `db_manager` singleton global. Correto para processo único desktop.

### 13. ci-cd — 5 issues (0 corrigidos)

- **CICD-001 (Alto)** — Sem `.github/workflows/`. Nenhum pipeline de CI/CD automático.
- **CICD-002 (Alto)** — `make lint` usa `ruff check ... || flake8 ...`. Linter variável por ambiente.
- **CICD-003 (Médio)** — Sem `pip-audit`/`safety` no pipeline.
- **CICD-004 (Médio)** — `make test` sem `--cov`. Cobertura nunca medida automaticamente.
- **CICD-005 (Baixo)** — Sem versionamento semântico automatizado.

### 14. packaging — 3 issues (0 corrigidos)

- **PKG-001 (Médio)** — `pyproject.toml` sem `license`, `authors`, `classifiers`, `project.urls`.
- **PKG-002 (Baixo)** — `[project.optional-dependencies.dev]` inclui apenas pytest. `ruff`, `mypy`, `pip-audit` não declarados como extras.
- **PKG-003 (Baixo)** — Build via `python -m build` não testado. Sem `twine check` no Makefile.

### 15. web-framework — ⏭️ SKIP
> App desktop PySide6. Sem FastAPI/Flask/Django.

### 16. api — ⏭️ SKIP
> Sem API REST pública. Integração via Claude Agent SDK (subprocess/SDK).

---

## Arquivos Mais Afetados

| Arquivo | Issues | Tipos |
|---------|--------|-------|
| `pyproject.toml` | 8 | configuration, dependencies, packaging, ci-cd |
| `pipeline_manager.py` | 3 | error-handling, architecture, data-handling |
| `sdk_adapter.py` | 3 | typing, hardcodes, error-handling |
| `sdk_worker.py` | 2 | async, hardcodes |
| `main_window.py` | 3 | error-handling, hardcodes, architecture |
| `history_manager.py` | 2 | data-handling, performance |
| `token_tracker.py` | 1 | data-handling |
| `db/models.py` | 1 ✅ | typing (resolvido) |

---

## Correções Aplicadas

| Arquivo | Linha | Antes | Depois | Sub-comando |
|---------|-------|-------|--------|-------------|
| `src/workflow_app/db/models.py` | 16 | `from typing import List, Optional` | `from typing import Optional` | typing |
| `src/workflow_app/db/models.py` | múltiplas | `Mapped[List["X"]]` | `Mapped[list["X"]]` | typing |

**Verificação pós-correção:** `pytest tests/test_db.py tests/test_db_manager.py` — 39 passed, 0 failed ✅

---

## Métricas de Qualidade

| Métrica | Valor Atual | Meta |
|---------|------------|------|
| Testes passando | 747 / 747 (100%) | 100% |
| Vulnerabilidades críticas | 0 | 0 |
| Vulnerabilidades de segurança | 0 | 0 |
| Issues Alto | 3 | 0 |
| Issues Médio | 10 | 0 |
| Issues Baixo | 24 | < 10 |
| Dependência não declarada | 1 (`claude-agent-sdk`) | 0 |

---

## Próximos Passos Recomendados

1. **DEP-002** — Adicionar `claude-agent-sdk` ao `[project.dependencies]` em `pyproject.toml`
2. **ASYNC-001** — Trocar `asyncio.get_event_loop()` → `asyncio.get_running_loop()` em `sdk_worker.py:118`
3. **ERH-001** — Adicionar `logger.debug(exc)` nos blocos `except Exception: pass` em `pipeline_manager.py`
4. **CONF-001** — Adicionar `[tool.ruff]` e `[tool.mypy]` ao `pyproject.toml`
5. **CONF-002** — Criar `.env.example` documentando variáveis necessárias

---

**Gerado por:** `/validate-stack` → `/python:py-review`
**Data:** 2026-03-11
**SystemForge Documentation First Development**
