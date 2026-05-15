# CONTRACT — `daily_loop` runtime shape (workflow-app)

> **Autoridade:** este documento e a fonte da verdade canonica para o shape do bloco `daily_loop` em `_LOOP-CONFIG.json` consumido pelo `workflow-app` (PySide6/Qt6). Toda divergencia entre specs `/loop:*` e o runtime do loader e resolvida aqui.
>
> **Escopo:** `ai-forge/workflow-app/src/workflow_app/daily_loop/loader.py` e os 3 specs canonicos `/loop:create-structure`, `/loop:integration`, `/loop:workflow-app`.
>
> **Origem:** consolidacao da secao 1.1 + 3.6 + 3.8 do `blacksmith/loop-archives/05-13-micro-architecture-refactor/_HARDENING-REPORT.md` (loop deste hardening: `blacksmith/loop-archives/05-13-hardening-cmd-flow/`, item 008 P1).

---

## 1. Statement canonico (regra de ouro)

`items_index` e **metadata de auditoria**; **runtime read autoritario** e `buckets[*].items[*].commands`.

- O loader (`loader.py::_resolve_item_commands`) procura comandos por-item **exclusivamente** em `daily_loop.buckets[*].items[*]`. O campo `daily_loop.items_index` **nao e consultado em runtime** pelo loader para resolver comandos — `grep items_index ai-forge/workflow-app/src/workflow_app/daily_loop/loader.py` retorna zero ocorrencias em `_resolve_item_commands`. As poucas leituras de `items_index` no loader sao para *blocked_reason* (gate `task_type=ambiguous`) e para *warning explicito* quando o fallback dispara mas `items_index` tem `commands` materializadas (Zero Silencio).
- `items_index[NNN].commands` permanece como **historia paralela** que `/loop:individual-analysis` e `/loop:integration` gravam para auditoria (`_INTEGRATION-LOG.md`, `_ANALYSIS-LOG.md`, replay). Sob nenhuma circunstancia substitui o caminho autoritario.
- Divergencia entre `items_index[NNN].commands` e `buckets[*].items[*].commands` (mesmo `id`) e **blocker** detectado por `/loop:workflow-app` na validacao **W9 — Bucket Items Shape Coherence**.

---

## 2. Shape match table (autoritativa)

Tabela literal copiada da secao 1.1 do `_HARDENING-REPORT.md`. Define o que `_resolve_item_commands` retorna para cada shape possivel em `buckets[*].items[*]` e se o caller (`build_daily_loop_specs` / `build_loop_specs`) cai no fallback wrapper `/daily-loop:do --slug ... --item ...`.

| Entry shape em `buckets[*].items[*]`           | `_resolve_item_commands` retorna | Fallback? | Veredito       |
|------------------------------------------------|----------------------------------|-----------|----------------|
| `"001"` (string)                               | `None`                           | sim       | legacy `--task` (retro-compat) |
| `{"id":"001"}` (dict sem `commands`)           | `[]`                             | sim       | anti-pattern  |
| `{"id":"001","commands":[]}`                   | `[]`                             | sim       | placeholder pre-`/loop:integration` (T0 valido) |
| `{"id":"001","commands":null}`                 | `[]`                             | sim       | anti-pattern  |
| `{"id":"001","commands":["/clear", ...]}` (>0) | `list[str]` literal              | **nao**   | shape canonico pos-`/loop:integration` |

Notas:

- "Fallback? sim" significa que o caller emite `CommandSpec(name=f"{do_command} --slug {slug} --item {item_id}")`, onde `do_command` default e `/daily-loop:do`. Em lane `/loop --task|--cmd|--cmd-single|--both` isso e regressao silenciosa do anti-pattern de wrapper de loop legado.
- Token `/daily-loop:do` **NUNCA** pode aparecer dentro de `items[*].commands`. `loader.py::_resolve_item_commands` rejeita com `DailyLoopConfigError` (linhas 293-298) — Zero Silencio.
- Shape `{"id":"001","commands":[]}` e legitimo durante a janela `/loop:create-structure` -> `/loop:integration`; passa a ser anti-pattern apos `/loop:integration` completar.

---

## 3. Gold example — schema canonico V3 + `daily_loop`

Copy-paste pronto para `_LOOP-CONFIG.json` em qualquer loop sob `blacksmith/loop-archives/{name}/`. Reflete o shape que o `metrics-project-pill` aceita (`config_parser.parse_config()` exige V3 com `basic_flow`) e que `_on_daily_loop_clicked` -> `build_daily_loop_specs` / `build_loop_specs` consome.

```json
{
  "name": "exemplo-loop",
  "kind": "daily-loop",
  "basic_flow": {
    "brief_root": "/abs/path/blacksmith/loop-archives/exemplo-loop",
    "docs_root":  "/abs/path/blacksmith/loop-archives/exemplo-loop",
    "wbs_root":   "/abs/path/blacksmith/loop-archives/exemplo-loop",
    "workspace_root": "/abs/path"
  },
  "project_details": {
    "language": { "pt-BR": true },
    "target_stack": {}
  },
  "daily_loop": {
    "version": "1.1.0",
    "slug": "exemplo-loop",
    "loop_root": "/abs/path/blacksmith/loop-archives/exemplo-loop",
    "progress_path": "PROGRESS.md",
    "tasks_dir": "tasks",
    "log_path": "_LOOP-LOG.md",
    "total_items": 2,
    "clear_between_items": true,
    "do_command": "/loop:iteraction:execute-task",
    "review_done_command": "/daily-loop:review-done",
    "review_command": "/daily-loop:review",
    "task_types": { "001": "task", "002": "cmd" },
    "buckets": [
      {
        "id": "T-sonnet-standard",
        "model": "sonnet",
        "effort": "standard",
        "task_file": "tasks/T-sonnet-standard.md",
        "items": [
          {
            "id": "001",
            "commands": [
              "/clear",
              "/model sonnet",
              "/effort standard",
              "/loop:iteraction:create-task blacksmith/loop-archives/exemplo-loop/tasks/items/task-001-...md",
              "/loop:iteraction:review-created-task blacksmith/loop-archives/exemplo-loop/tasks/items/task-001-...md",
              "/clear",
              "/loop:iteraction:execute-task blacksmith/loop-archives/exemplo-loop/tasks/items/task-001-...md",
              "/clear",
              "/model opus",
              "/loop:iteraction:review-executed-task blacksmith/loop-archives/exemplo-loop/tasks/items/task-001-...md"
            ]
          },
          {
            "id": "002",
            "commands": [
              "/clear",
              "/model sonnet",
              "/cmd:create blacksmith/loop-archives/exemplo-loop/tasks/items/task-002-...md",
              "/cmd:review /micro:brief blacksmith/loop-archives/exemplo-loop/tasks/items/task-002-...md"
            ]
          }
        ]
      }
    ],
    "items_index": {
      "001": {
        "task_file": "tasks/items/task-001-...md",
        "task_type": "task",
        "commands": ["...mesma sequencia que buckets[0].items[0].commands..."],
        "priority": "P1"
      },
      "002": {
        "task_file": "tasks/items/task-002-...md",
        "task_type": "cmd",
        "commands": ["...mesma sequencia que buckets[0].items[1].commands..."],
        "priority": "P2"
      }
    }
  }
}
```

Notas sobre o gold:

- `items_index[NNN].commands` deve replicar literalmente `buckets[*].items[*].commands` do mesmo `id` (paridade exata). Divergencia e detectada por W9.
- `daily_loop.do_command` define o wrapper de fallback (alvo do anti-pattern). Em modo `--both`/`--task`/`--cmd` canonico, **o fallback nunca dispara** porque `commands` esta populado em `buckets[*].items[*]`.
- `task_types[NNN]` controla o gate `task_type=ambiguous` no loader (`_normalize_items()` rejeita itens ambiguous; resolucao manual obrigatoria via `/loop:check-tasks-and-cmd`).

---

## 4. Producers (escritores deste shape)

Tres comandos canonicos produzem e mantem o shape `daily_loop.buckets[*].items[*]`. Qualquer outro escritor e regressao.

| Producer | Spec canonico | Quando escreve | O que escreve |
|----------|---------------|----------------|---------------|
| `/loop:create-structure` | [`.claude/commands/loop/create-structure.md`](../../../../../.claude/commands/loop/create-structure.md) | FASE 1 do orquestrador `/loop` | Cria o esqueleto de `daily_loop.buckets[*].items[*]` ja como `[{"id": "NNN", "commands": []}, ...]` desde T0 (contrato P0 binding — `commands: []` placeholder, NUNCA strings). Tambem grava `items_index[NNN]` paralelo. |
| `/loop:integration`     | [`.claude/commands/loop/integration.md`](../../../../../.claude/commands/loop/integration.md)     | FASE 3 do orquestrador `/loop` | Preenche `daily_loop.buckets[*].items[*].commands` com a sequencia literal materializada (placeholders resolvidos, /clear/model/effort no boundary de runs, wrapper Kimi quando elegivel). Replica em `items_index[NNN].commands` para auditoria. |
| `/loop:workflow-app`    | [`.claude/commands/loop/workflow-app.md`](../../../../../.claude/commands/loop/workflow-app.md)    | FASE 5 do orquestrador `/loop` (validacao + handoff) | NAO escreve `commands` per-item; valida coerencia. Gate W9 — Bucket Items Shape Coherence: compara `buckets[*].items[*].commands` contra `items_index[NNN].commands` byte-a-byte; blocker se entry e string, error se diverge, blocker se ausente em `buckets[*]`. |

Producers complementares (escrevem auditoria, nunca o shape autoritario):

- `/loop:individual-analysis` — grava `items_index[NNN].model`, `items_index[NNN].effort`, `items_index[NNN].kimi_eligible` (FASE 2). Nao toca `buckets[*].items[*].commands`.
- `/loop:mark-type` — rotula `daily_loop.task_types[NNN]` (modo `--both`). Nao toca `commands`.
- `/loop:check-tasks-and-cmd` — gate de re-rotulagem para items ambiguous. Nao toca `commands` autoritarios.

---

## 5. Consumers (leitores deste shape)

Tres call sites em `loader.py` consomem o shape canonico. Toda regressao silenciosa do fallback dispara warning explicito (Zero Silencio) via `_warn_silent_fallback_if_items_index_populated` (linha 385).

| Consumer | Localizacao em `loader.py` | Lane do workflow-app | Comportamento |
|----------|---------------------------|----------------------|---------------|
| `_resolve_item_commands(daily_loop, item_id)` | linhas 252-300 | helper compartilhado | Retorna `list[str]` literal quando `buckets[*].items[*].commands` esta populado; retorna `[]` ou `None` nos shapes do fallback (vide tabela secao 2). Rejeita `/daily-loop:do` dentro de `commands` com `DailyLoopConfigError`. |
| `build_daily_loop_specs(raw_config, loop_root)` | linhas 421-712 (chamada de `_resolve_item_commands` em 568; warning em 587) | lane legacy `/daily-loop` (`queue-btn-daily-loop`) | Emite UM `CommandSpec` por entrada de `commands` quando populado. Caso fallback: emite `CommandSpec(name=f"{do_command} --slug {slug} --item {item_id}")` + warning stderr se `items_index[item_id].commands` tem conteudo (drift detectavel). |
| `build_loop_specs(raw_config, loop_root)` | linhas 802-988 (chamada de `_resolve_item_commands` em 933; warning em 952) | lane `/loop --task\|--cmd\|--cmd-single\|--both` (`queue-btn-loop`, `queue-btn-cmd-single`) | Mirror exato de `build_daily_loop_specs` para a lane do `/loop`, com a unica diferenca de que NAO atualiza `PROGRESS.md` automaticamente (responsabilidade do `/loop:iteraction:review-executed-task` no `[post]`). |

Per-item, apos o `do` (literal canonico ou wrapper de fallback), todos os 3 consumers emitem `CommandSpec(name=f"{review_done_command} --slug {slug} --item {item_id}")` (default `/daily-loop:review-done`). Ao termino da fila, emitem UMA vez `CommandSpec(name=f"{review_command} --slug {slug}")` (default `/daily-loop:review`). Esses dois caminhos finais NAO tem lane "per-item commands" e nao sao afetados pela precedencia do shape.

---

## 6. Anti-patterns (shapes que caem no fallback)

Os 4 shapes abaixo disparam o fallback `/daily-loop:do --slug ... --item ...` em runtime. Em lane canonica `/loop --both|--task|--cmd|--cmd-single` isso e regressao silenciosa do bug original documentado na secao 1 do `_HARDENING-REPORT.md`. Gate W9 do `/loop:workflow-app` bloqueia commit destes shapes (item 004 do hardening).

| # | Shape em `buckets[*].items[*]`        | Como o loader trata | Por que e anti-pattern | Remediacao |
|---|---------------------------------------|---------------------|------------------------|------------|
| 1 | `"001"` (string nua)                  | `_resolve_item_commands` retorna `None`; caller emite wrapper `/daily-loop:do --slug X --item 001`. | Lane `/loop` canonica precisa de `commands` literais (`/cmd:*`, `/execute-task`, `/skill:*` etc.). Wrapper assume convencao de task de implementacao e ignora a materializacao de `/loop:integration`. | `/loop:integration` re-rodada; OU script `ai-forge/scripts/audit-loop-configs.py --fix` que promove string -> dict copiando de `items_index[NNN].commands`. |
| 2 | `{"id":"001"}` (dict sem `commands`)  | `_resolve_item_commands` retorna `[]`; caller emite wrapper. | Chave `commands` ausente equivale a placeholder nao resolvido. `/loop:integration` falhou ou nao rodou. | Re-rodar `/loop:integration`. Verificar logs em `_INTEGRATION-LOG.md`. |
| 3 | `{"id":"001","commands":[]}`          | `_resolve_item_commands` retorna `[]`; caller emite wrapper. | Legitimo apenas pre-`/loop:integration` (T0). Apos FASE 3, indica que `/loop:integration` nao preencheu este item. | Re-rodar `/loop:integration`. Se persistir, abrir item em `/loop:individual-analysis` e re-materializar. |
| 4 | `{"id":"001","commands":null}`        | `_resolve_item_commands` retorna `[]`; caller emite wrapper. | `null` explicito em vez de lista — bug de serializacao ou downgrade manual. | Re-rodar `/loop:integration`. Auditar JSON manualmente. |

Validacao pre-commit (item 3.8 do hardening, P2): hook `PreToolUse` em `.claude/settings.local.json` (ou git pre-commit) que invoca o validador W9 contra qualquer `_LOOP-CONFIG.json` modificado, bloqueando commit de shape incoerente.

---

## 7. Cross-references

Este CONTRACT.md e linkado bidirecionalmente:

- **CLAUDE.md Tier 2** — secao "Subflows alternativos > Loop especifico (F4d)" referencia este arquivo.
- **Specs editados nos itens 002/003/004 do loop `05-13-hardening-cmd-flow`:**
  - [`.claude/commands/loop/integration.md`](../../../../../.claude/commands/loop/integration.md) — secao OVERRIDE CANONICO 2026-05-12 aponta para este CONTRACT.md como autoridade do shape.
  - [`.claude/commands/loop/create-structure.md`](../../../../../.claude/commands/loop/create-structure.md) — secao "Contrato T0 obrigatorio para `daily_loop.buckets[*].items` (P0)" aponta para este CONTRACT.md.
  - [`.claude/commands/loop/workflow-app.md`](../../../../../.claude/commands/loop/workflow-app.md) — secao OVERRIDE CANONICO 2026-05-12 e PASSO 7.5 (W9) apontam para este CONTRACT.md.
- **Loader runtime:** [`ai-forge/workflow-app/src/workflow_app/daily_loop/loader.py`](loader.py) — autoridade de implementacao.
- **Relatorio de origem:** [`blacksmith/loop-archives/05-13-micro-architecture-refactor/_HARDENING-REPORT.md`](../../../../../blacksmith/loop-archives/05-13-micro-architecture-refactor/_HARDENING-REPORT.md) — secao 1.1 (tabela shape match), 3.6 (decisao de criar este documento), 3.8 (gate pre-commit).
- **Loop de hardening:** [`blacksmith/loop-archives/05-13-hardening-cmd-flow/`](../../../../../blacksmith/loop-archives/05-13-hardening-cmd-flow/) — itens 002/003/004 (patches nas specs), 008 (este CONTRACT.md).
- **Auditoria retroativa:** [`ai-forge/scripts/audit-loop-configs.py`](../../../../scripts/audit-loop-configs.py) — script de varredura/fix que detecta e remedia loops afetados; relatorio em `blacksmith/loop-archives/_AUDIT-2026-05-13.md`.

---

## 8. Quando atualizar este CONTRACT.md

Atualizar este arquivo (e o WORKFLOW-INDEX.json downstream) sempre que:

1. **Loader muda** (`loader.py::_resolve_item_commands`, `build_daily_loop_specs`, `build_loop_specs`): atualizar secoes 2 (tabela), 5 (consumers) e 6 (anti-patterns).
2. **Spec producer muda** (`/loop:create-structure`, `/loop:integration`, `/loop:workflow-app`): atualizar secao 4.
3. **Novo shape e adicionado** em `buckets[*].items[*]`: atualizar secao 2 + secao 6 (anti-pattern se cair no fallback).
4. **Cross-reference adicional** em qualquer spec do `.claude/commands/loop/`: atualizar secao 7.

Manter paridade com `_HARDENING-REPORT.md` secao 1.1: se a tabela divergir, o `_HARDENING-REPORT.md` registra a historia do bug, este CONTRACT.md registra a verdade canonica vigente.
