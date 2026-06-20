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

### 2.1 Campos obrigatorios per-item (adicionado 2026-05-17 — rocksmash hardening)

Alem de `id` e `commands`, cada entry em `buckets[*].items[*]` DEVE carregar tres campos canonicos de auditoria/runtime que outros consumers leem direto do bucket (sem cair em `items_index`):

| Campo       | Tipo   | Obrigatorio em | Significado | Consumer |
|-------------|--------|----------------|-------------|----------|
| `kind`      | string | T0 (create-structure) | Lifecycle slot: `"preparo"` (1o item), `"iteration"` (corpo), `"finalizacao"` (ultimo item). Sem `kind`, consumers que filtram por lifecycle (rocksmash, qualquer expander futuro) defaultam para `"iteration"` e processam preparo/finalizacao por engano. | `loop_rocksmash_expander.build_loop_rocksmash_specs` (filtra `kind=="iteration"`). |
| `task_path` | string | T0 (create-structure) | Caminho relativo a `loop_root` (ex: `tasks/items/task-NNN-slug.md`) OU absoluto. Resolvido por `_resolve_task_path` (relativo -> anchored em `loop_root`). | `loop_rocksmash_expander._resolve_task_path` (per-iteration `:do`/`:review-done`). |
| `target`    | string | opcional (alias de `task_path`) | Alias historico (legacy V2). `_resolve_task_path` aceita ambos; `task_path` ganha precedencia se ambos presentes. | idem `task_path`. |

Por que no bucket e nao so em `items_index`: per CONTRACT.md secao 1, `items_index` e metadata de auditoria; runtime read autoritario e `buckets[*].items[*]`. Consumers em runtime (loader e expanders) leem do bucket por contrato. `_iter_items` do rocksmash faz backfill best-effort de `items_index` quando bucket nao tem o campo (retro-compat para loops pre-2026-05-17), mas isso emite o anti-pattern: producers novos devem escrever DIRETO no bucket.

Producers (`/loop:create-structure`, `/loop:integration`) devem materializar `kind` + `task_path` em ambos `buckets[*].items[*]` e `items_index[NNN]` (paridade exata, gate W9 do `/loop:workflow-app`).

### 2.2 Path field convention (adicionado 2026-05-19 — Onda 9 hardening, anti workspace-doubled-path)

**Regra de ouro:** todo campo path do bloco `daily_loop` (e adjacentes) e **filename-only relativo a `loop_root`** (ou path raso `tasks/...` para `spec_path`/`task_path`). Absoluto e tolerado para `loop_root` e `basic_flow.*`; workspace-relative (com slug embutido) e PROIBIDO.

**Por que:** o helper `resolve_loop_path(value, loop_root)` em `loader.py` aplica regra simples — relativos resolvem como `loop_root / value`, absolutos sao usados as-is. Se um producer grava `daily_loop.progress_path = "blacksmith/loop-archives/{slug}/PROGRESS.md"`, o loader resolve como `{loop_root}/blacksmith/loop-archives/{slug}/PROGRESS.md` (duplicacao do slug) e quebra com `PROGRESS.md nao encontrado`. O contrato simples e a-prova-de-substituicao porque NAO depende de o consumidor saber qual e a "base" da relativizacao.

**Tabela canonica por campo:**

| Campo                              | Convencao                                              | Exemplo correto                        | Anti-pattern (PROIBIDO)                                       |
|------------------------------------|--------------------------------------------------------|----------------------------------------|---------------------------------------------------------------|
| `daily_loop.loop_root`             | Absoluto (preferido) OU workspace-relative resolvivel  | `/abs/.../blacksmith/loop-archives/{slug}` | n/a                                                       |
| `daily_loop.progress_path`         | Filename-only relativo a `loop_root`                   | `"PROGRESS.md"`                        | `"blacksmith/loop-archives/{slug}/PROGRESS.md"`               |
| `daily_loop.tasks_dir`             | Filename-only relativo a `loop_root`                   | `"tasks"`                              | `"blacksmith/loop-archives/{slug}/tasks"`                     |
| `daily_loop.log_path`              | Filename-only relativo a `loop_root`                   | `"_LOOP-LOG.md"`                       | qualquer string com `/` embutindo o slug                      |
| `daily_loop.source_config_path`    | Filename-only relativo a `loop_root`                   | `"_LOOP-CONFIG.json"`                  | workspace-relative                                            |
| `daily_loop.buckets[*].spec_path`  | Relativo a `loop_root` comecando por `tasks/`          | `"tasks/T-opus-high.md"`               | absoluto OU prefixado com `blacksmith/.../{slug}/`            |
| `daily_loop.buckets[*].items[*].task_path` | Relativo a `loop_root` (`tasks/items/...`)     | `"tasks/items/task-001-...md"`         | bare-relativo com slug embutido                               |
| `items_index[*].task_path`         | Relativo a `loop_root` (`tasks/items/...`)             | `"tasks/items/task-001-...md"`         | absoluto sem necessidade                                      |
| `metadata.source_md`               | Filename-only relativo a `loop_root`                   | `"source.md"`                          | `"blacksmith/loop-archives/{slug}/source.md"`                 |

**Excecao:** tokens em `buckets[*].items[*].commands` que apontam para arquivos (`--task <path>`, `/cmd:update <path>`) sao **workspace-relative** (porque `command_queue_widget` injeta com `cwd == workspace_root`). Esse caso e separado do contrato de path do `daily_loop.*` e e coberto pela validacao W4b do `/loop:workflow-app`.

**Detector canonico (referencia python):**

```python
from workflow_app.daily_loop import (
    assert_loop_root_relative_path,
    diagnose_workspace_doubled_path,
)

# Diagnostico (retorna sugestao de fix ou None):
suggestion = diagnose_workspace_doubled_path(value, loop_root)
# Enforce (raises DailyLoopConfigError):
assert_loop_root_relative_path(value, loop_root, label="progress_path")
```

Ambos exportados em `workflow_app.daily_loop.__init__`. Implementacao em `loader.py`. Testes em `tests/workflow_app/test_daily_loop_loader.py` (classes `TestDiagnoseWorkspaceDoubledPath`, `TestAssertLoopRootRelativePath`).

**Gates que enforcam esta regra (numeros reconciliados 2026-05-22 — antes citavam C15/W10 por engano, que sao os gates do par Kimi):**

- Producer (`/loop:create-structure`): secao "Contrato T0 obrigatorio para os PATHS de `daily_loop`" documenta o shape filename-only + self-test antes de gravar o JSON; DEVE nao gerar workspace-relative.
- Producer (`/loop:integration`): re-materializa `items[].commands` mas NAO reescreve `progress_path`/`tasks_dir`/`log_path`; preserva o shape gravado por `/loop:create-structure`.
- Validator estrutural (`/loop:review` **C16**): detecta + auto-fixa (`fix_action: edit-json`, substitui pelo basename canonico) os campos `progress_path`/`tasks_dir`/`log_path` com segmento embutido; tambem valida resolucao efetiva contra `loop_root` fisico.
- Validator pre-runtime (`/loop:workflow-app` **W12**): detecta + bloqueia veredict APROVADO; `auto_fixable: false` (correcao via re-rodar `/loop:create-structure` ou via C16 do `/loop:review`). Inclui W12.b — resolucao efetiva do path contra `loop_root` fisico.
- Runtime defense (`loader.py::build_daily_loop_specs` e `build_loop_specs`): mensagens de erro enriquecidas com sugestao via `diagnose_workspace_doubled_path` quando `PROGRESS.md nao encontrado` por path doubling.

> **Nota:** `/loop:review` C15 e `/loop:workflow-app` W10 sao os gates do **par Kimi** (adjacencia/contencao de `/cmd:kimi-pair-*`), NAO desta regra de path. Esta secao citava esses numeros por engano ate 2026-05-22 — corrigido para C16/W12 no hardening `blacksmith/loop/05-22-loop-path-hardening.md`.

**Bug-fix referencia:** (a) `blacksmith/loop-archives/05-19-gap-tasklist/_HANDOFF.md` (Onda 9, 2026-05-19) — loop quebrou em runtime porque 6 campos foram gravados workspace-relative pelo `/loop:create-structure`. (b) `blacksmith/loop-archives/05-21-implantation-tasklist-aba-brainstorm` (corrigido 2026-05-22) — `progress_path`/`tasks_dir` workspace-relative com slug embutido; correcao + criacao dos gates C16/W12 documentada em `blacksmith/loop/05-22-loop-path-hardening.md`.

### 2.3 Top-level `mode` discriminator + rocksmash 4-command iteration (adicionado 2026-05-19 — B6 rocksmash quad-loop integration)

**Regra de ouro:** o campo top-level `mode` em `_LOOP-CONFIG.json` declara o sabor canonico da fila. Quando `mode == "rocksmash"`, cada item com `kind == "iteration"` (ou sem `kind`, tratado como iteration) carrega EXATAMENTE 4 tokens canonicos em `commands` (apos remover `/clear|/model|/effort`) e nessa ordem: `do` -> `review-done` -> `compare` -> `integrate`. Para os demais valores (`"normal"`, `"task"`, `"cmd"`, `"cmd-single"`, `"both"`, ausente), a contagem permanece variavel (tipicamente 4 — `create-task` + `review-created-task` + `execute-task` + `review-executed-task` — no fluxo `--task`/`--both`).

**Enum canonico:**

| Valor de `mode`   | Origem                              | Per-iteration commands | Consumer canonico                                   |
|-------------------|-------------------------------------|------------------------|----------------------------------------------------|
| `"rocksmash"`     | `/loop --rocksmash`, `/legacy:detect`| 4 (do/review-done/compare/integrate) | `build_loop_rocksmash_specs` + `build_loop_specs` |
| `"task"`          | `/loop --task`                      | variavel               | `build_loop_specs`                                  |
| `"cmd"`           | `/loop --cmd`                       | variavel               | `build_loop_specs`                                  |
| `"cmd-single"`    | `/loop --cmd-single`                | variavel + expanded    | `build_loop_specs`                                  |
| `"both"`          | `/loop --both`                      | variavel               | `build_loop_specs`                                  |
| `"mkt_assets"`    | `/mkt-assets` (lane gemea de `/loop`)| variavel, tokens `/mkt-assets:*` | `build_loop_specs` (lane containment)    |
| `"normal"`        | retro-compat (sem CLI flag)         | variavel               | `build_loop_specs` ou `build_daily_loop_specs`      |
| ausente / null    | retro-compat V3 pre-2026-05-19      | tratado como `"normal"`| idem                                                |

**Validador canonico (referencia python):**

```python
from workflow_app.daily_loop import (
    is_rocksmash_mode,
    assert_rocksmash_iteration_shape,
    is_mkt_assets_mode,
    assert_mkt_assets_iteration_shape,
)

if is_rocksmash_mode(raw_config):
    assert_rocksmash_iteration_shape(raw_config)  # raises DailyLoopConfigError

if is_mkt_assets_mode(raw_config):
    assert_mkt_assets_iteration_shape(raw_config)  # raises DailyLoopConfigError
```

Os quatro exportados em `workflow_app.daily_loop.__init__`. Implementacao em `loader.py`. Os helpers rocksmash sao chamados internamente em `build_loop_specs` (lane `/loop`) e em `build_loop_rocksmash_specs` (lane `queue-btn-rocksmash`); os helpers mkt-assets sao chamados em `build_loop_specs` (lane `/loop` / `queue-btn-mkt-assets`) e em `build_daily_loop_specs` (paridade defensiva).

**mkt-assets lane (2026-06-18):** `mode == "mkt_assets"` declara a lane `/mkt-assets`, gemea de `/loop` (preparo -> iteration_template -> finalizacao) que reusa este motor a exemplo de `/kimi-loop`. Diferente de rocksmash, NAO ha contagem fixa de tokens: a lane mantem o shape variavel do `/loop` (`create-task` + `review-created-task` + `execute-task` + `review-executed-task`). O `assert_mkt_assets_iteration_shape` aplica **lane containment**: cada item `kind == "iteration"` (apos remover `/clear|/model|/effort`) so pode despachar tokens no namespace `/mkt-assets:*` — gate de discovery contra o execution_risk "botao aparece mas comando cai no handler errado / falha silenciosa". Itens `preparo`/`finalizacao` sao pulados (podem carregar housekeeping cross-lane, ex. `/loop:iteraction:review-executed-loop`). `commands == []` e tolerado apenas pre-integration (`metadata.integration_completed_at` ausente).

**Producers (gravam `mode`):**

- `/loop:create-structure` — escreve `mode` top-level apos detectar o flag do CLI (`--rocksmash` => `"rocksmash"`; demais => valor literal do flag). Sem flag, omite o campo (defaulta a non-rocksmash silenciosamente).
- `/loop:integration` — preserva `mode`; quando `mode == "rocksmash"`, materializa `buckets[*].items[*].commands` com os 4 tokens canonicos (e replica em `items_index[NNN].commands` para auditoria W9).
- `/legacy:detect` — promove loops legacy rocksmash setando `mode = "rocksmash"` E aplicando backfill via `/legacy:enqueue-all-modules` para converter `[do, review-done]` em `[do, review-done, compare, integrate]` (B12).

**Migracao:** loops V3 sem `mode` (pre-2026-05-19) sao tratados como `"normal"` automaticamente, sem warning. Loops rocksmash legacy (com `daily_loop.rocksmash_legacy_two_step: true`) continuam emitindo 2 comandos por iteracao no expander; o backfill B12 promove para 4 comandos quando o operador estiver pronto.

**Gate de runtime:** `assert_rocksmash_iteration_shape` rejeita com `DailyLoopConfigError` quando o shape diverge dos 4 tokens canonicos. Falha apresenta o `id` do item, a sequencia observada e a sequencia esperada — Zero Silencio. Para itens com `commands == []` em estado pre-integration (`metadata.integration_completed_at` ausente), o validator tolera o placeholder (alinha com a tabela da secao 2: shape `{"id":"NNN","commands":[]}` e legitimo pre-`/loop:integration`).

### 2.4 Chaves top-level prefixadas com `_` — namespace advisory reservado (adicionado 2026-05-21 — T-05 R5 stale-marking)

**Regra de ouro:** chaves top-level de `_LOOP-CONFIG.json` cujo nome comeca com underscore (`_comment`, `_fixture_scope`, `_stale_suspect`, ...) sao **namespace advisory reservado**: carregam metadados para humanos ou ferramentas auxiliares e o loader DEVE ignora-las. `config_parser.parse_config()` e `build_*_specs` extraem apenas campos conhecidos por nome (`kind`, `daily_loop`, `basic_flow`, `mode`, ...) e nao falham diante de chaves extras; `validate-loop-config.py` (W9) exige apenas `kind` + `daily_loop` e nao enforca `additionalProperties: false`. Logo, escrever uma chave `_*` no topo e seguro e nao quebra runtime nem auditoria.

Produtores podem usar esse namespace para sinalizacao que nao deve influenciar a fila. Exemplo canonico: `_stale_suspect` (gravado por T-05 / risco R5) marca loops nao executados gerados na janela de um bug de integracao — ver `blacksmith/05-21-brainstorm/T-05-marcacao-stale.md`. A marca e advisory: nao bloqueia o loader; um gate de runtime que recuse importar loop com `_stale_suspect` presente seria hardening adicional, fora deste contrato hoje.

Qualquer futura adocao de JSON Schema com `additionalProperties: false` para `_LOOP-CONFIG.json` DEVE whitelistar o prefixo `_` (pattern property `^_`) para preservar este namespace.

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
            "kind": "iteration",
            "task_path": "tasks/items/task-001-...md",
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
            "kind": "iteration",
            "task_path": "tasks/items/task-002-...md",
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

### 3.1 Gold example — modo `rocksmash` (4 commands por iteracao)

Variante canonica quando `mode == "rocksmash"`. Cada item iteration carrega EXATAMENTE 4 tokens canonicos (apos remover `/clear|/model|/effort`).

```json
{
  "name": "exemplo-rocksmash",
  "kind": "daily-loop",
  "mode": "rocksmash",
  "basic_flow": { "...": "..." },
  "daily_loop": {
    "slug": "exemplo-rocksmash",
    "loop_root": "/abs/path/blacksmith/loop-archives/exemplo-rocksmash",
    "buckets": [
      {
        "id": "T-opus-high",
        "model": "opus",
        "effort": "high",
        "items": [
          {
            "id": "002",
            "kind": "iteration",
            "task_path": "tasks/items/task-002-...md",
            "commands": [
              "/clear",
              "/model opus",
              "/effort high",
              "/loop-rocksmash:do blacksmith/loop-archives/exemplo-rocksmash/tasks/items/task-002-...md",
              "/loop-rocksmash:review-done blacksmith/loop-archives/exemplo-rocksmash/tasks/items/task-002-...md",
              "/loop-rocksmash:compare blacksmith/loop-archives/exemplo-rocksmash/tasks/items/task-002-...md",
              "/loop-rocksmash:integrate blacksmith/loop-archives/exemplo-rocksmash/tasks/items/task-002-...md"
            ]
          }
        ]
      }
    ]
  }
}
```

Notas sobre o gold rocksmash:

- Tokens canonicos (apos strip de directives): `["/loop-rocksmash:do", "/loop-rocksmash:review-done", "/loop-rocksmash:compare", "/loop-rocksmash:integrate"]`. Ordem importa.
- Suffix `<task_path>` em cada token e permitido e ignorado pelo validador (que compara apenas a primeira palavra de cada comando).
- Opt-in legacy: para manter o shape de 2 comandos (apenas `:do` + `:review-done`), gravar `daily_loop.rocksmash_legacy_two_step: true` E NAO declarar `mode == "rocksmash"`. O validador `assert_rocksmash_iteration_shape` so dispara quando `mode == "rocksmash"`.
- Items `kind in {"preparo", "finalizacao"}` sao ignorados pelo validador.
- `assert_rocksmash_iteration_shape` tolera `commands == []` quando `metadata.integration_completed_at` esta ausente (placeholder pre-`/loop:integration`).

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
| `build_loop_specs(raw_config, loop_root)` | linhas 802-988 (chamada de `_resolve_item_commands` em 933; warning em 952) | lane `/loop --task\|--cmd\|--cmd-single\|--both` (`queue-btn-loop`, `queue-btn-cmd-single`) | Comportamento diverge de `build_daily_loop_specs` em `review_done_command` (ver nota abaixo). |

**Nota de divergencia `review_done_command` entre lanes (fix 2026-05-20):**

- **Lane legacy `/daily-loop` (`build_daily_loop_specs`):** `review_done_command` e injetado SEMPRE apos cada item, independente de `canonical_cmds`. Comportamento inalterado.
- **Lane `/loop` (`build_loop_specs`):** `review_done_command` e injetado SOMENTE no path de fallback (quando `canonical_cmds` esta vazio). Quando `canonical_cmds` esta populado, o reviewer per-item ja esta embutido nos proprios comandos (`/loop:iteraction:review-executed-task`, `/cmd:review`, etc.) e injetar `review_done_command` adicionalmente causaria contaminacao cross-lane (`/daily-loop:review-done` revisando output de `/loop:iteraction:execute-task`). Isso e semanticamente incorreto: sao fluxos ortogonais, com contratos de argumentos e responsabilidades incompativeis.

Per-item na lane legacy `/daily-loop`: apos o `do` (literal canonico ou wrapper de fallback), `build_daily_loop_specs` emite `CommandSpec(name=f"{review_done_command} --slug {slug} --item {item_id}")` (default `/daily-loop:review-done`). Ao termino da fila, emite UMA vez `CommandSpec(name=f"{review_command} --slug {slug}")` (default `/daily-loop:review`).

Per-item na lane `/loop` com `canonical_cmds` populado: `build_loop_specs` NAO emite `review_done_command`. O reviewer e o ultimo comando da sequencia `canonical_cmds`. Ao termino da fila, emite UMA vez `CommandSpec(name=f"{review_command} --slug {slug}")` (default `/daily-loop:review`, substituivel por `/loop:iteraction:review-executed-loop` via `daily_loop.review_command`).

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
