"""Adequacao das diretivas `/model` e `/effort` ao Main LLM da fila (C27).

Problema que este modulo resolve
--------------------------------
Os templates da aba `COMMAND SEQUENCE` (`output-toolbar-left`) emitem blocos
canonicos `/clear` + `/model {X}` + `/effort {Y}` (ver
`templates/quick_templates.py::_inject_clears`). Esses literais sao dialeto
**Claude Code**. Ate 2026-08-17 a fila (`queue-command-list`) os renderizava
identicos para qualquer Main LLM selecionado em `queue-div-main-llm`, entao com
Main Codex/Kimi/Qwen/Grok o operador lia na tela um `/model opus` que o CLI de
destino nunca receberia (o dispatcher ja o suprimia). A UI afirmava um
modelo/effort que nao valia para aquela etapa.

Contrato (decisao D-C27-2, 2026-08-17)
--------------------------------------
- `claude` -> identidade. Nenhum spec e alterado, adicionado ou removido.
- `codex`, `kimi`, `qwen`, `grok` -> as linhas `/model` e `/effort` sao
  REMOVIDAS no enqueue. Nenhum desses CLIs expoe diretiva TEXTUAL de modelo ou
  reasoning; nao ha para onde traduzir.
- Main desconhecido -> identidade (fail-open: nunca APAGAR diretiva por causa
  de um valor que este modulo nao conhece).

**Por que remover em vez de traduzir.** A primeira versao deste modulo
(2026-08-17, mesma data) traduzia `/model opus`+`/effort high` para
`/model sol high` (Codex) e `/model k3`+`/reasoning yes` (Kimi), atras da flag
`SF_MODEL_EFFORT_EQUIV`. A investigacao do item 002 do loop
`08-17-systemforge-multillm-gaps-refactor` foi aos CLIs reais, em PTY
(`pty.fork`, xterm-256color 140x45), e REFUTOU as duas formas — transcricoes em
`blacksmith/loop-archives/08-17-systemforge-multillm-gaps-refactor/_EVIDENCE-RJ1-RJ2-CLI-SYNTAX.md`:

  - **Codex CLI 0.147.0**: `/model sol high` nao e slash-command. A linha vai
    como PROMPT (queima um turno de API; o modelo responde que nao troca o
    backend por ali) e o modelo/effort da sessao NAO muda. O `/model` real e um
    picker interativo de DUAS etapas (`Select Model and Effort` ->
    `Select Reasoning Level`), sem `Usage:` e sem argumentos; `/effort` nao
    existe; `sol`/`spark` nao existem como token solto (os slugs reais sao
    `gpt-5.6-sol` e `gpt-5.3-codex-spark`). Fonte:
    `tui/src/chatwidget/model_popups.rs`.
  - **Kimi Code CLI**: responde `Unknown slash command "/reasoning"`. O
    `/model k3` DESCARTA o argumento e abre picker bloqueante por setas, que
    engole a proxima linha colada — corrompe a fila do autocast. Fonte:
    `kimi_cli/ui/shell/slash.py::model`, que nunca le `args`. Thinking mode e a
    etapa 2 do mesmo picker.

Ou seja: traduzir e pior que nao mandar nada — no Codex custa um turno e mente
sobre o efeito, no Kimi trava a fila. Como nenhum dos dois tem forma textual, a
unica saida honesta na fila e nao renderizar a linha, exatamente como Qwen e
Grok ja faziam. A flag `SF_MODEL_EFFORT_EQUIV` foi REMOVIDA junto com a
traducao: ela so podia ligar um comportamento comprovadamente quebrado.

Como se controla modelo/effort nos CLIs nao-Claude
--------------------------------------------------
Nao pela fila, e sim no BOOT do processo (ou no config do CLI):

  - Codex: `codex -m gpt-5.6-sol -c model_reasoning_effort=high`, ou os
    wrappers `~/.local/bin/codex-high` / `codex-xhigh`, ou `~/.codex/config.toml`.
  - Kimi: `~/.kimi/config.toml` (`default_model`, `default_thinking`).
  - Qwen / Grok: `~/.qwen/settings.json` / `~/.grok/config.toml`.

A tabela de equivalencia boot-time (com os slugs reais e a procedencia de cada
celula) vive em `ai-forge/rules/llm-routing-div.md` §14.1. Ensinar o LAUNCHER a
aplicar essa equivalencia por sessao e trabalho separado (gap R-J3), NAO deste
modulo: ele so decide o que a fila renderiza e o que vai ao PTY.

Residuo de dialeto estrangeiro
------------------------------
Filas salvas antes desta decisao (`get_queue_snapshot` ->
`output/wbs/pipeline-position/{slug}.json`) podem conter `/model sol high`,
`/model k3` ou `/reasoning yes`. Esses literais nao sao validos em CLI nenhum,
inclusive no Claude Code. `is_foreign_directive` os reconhece para que o
dispatcher Claude os suprima + pulse em vez de colar lixo no T1; os dispatchers
nao-Claude ja suprimem toda diretiva por `is_directive_line`.

Backlog: gap C27, Pacote J de
`blacksmith/brainstorm-mcp/08-17-systemforge-multillm-gaps-refactor.md`.
"""

from __future__ import annotations

from workflow_app.domain import CommandSpec

# ─── Conjuntos canonicos ─────────────────────────────────────────────────── #

#: Mains sem diretiva TEXTUAL de modelo/effort: as linhas somem da fila.
#:
#: Os quatro estao aqui pela MESMA razao empirica, so que descoberta em datas
#: diferentes: `qwen`/`grok` nunca tiveram seletor; `codex`/`kimi` tem seletor,
#: mas so como picker interativo que ignora argumento (evidencia no docstring do
#: modulo). Adicionar um LLM sem diretiva textual equivale a inseri-lo aqui.
PROVIDERS_WITHOUT_MODEL_DIRECTIVES: frozenset[str] = frozenset(
    {"codex", "kimi", "qwen", "grok"}
)

#: Unico Main cujo CLI aceita `/model X` e `/effort Y` como texto.
MAIN_LLMS_WITH_NATIVE_DIRECTIVES: frozenset[str] = frozenset({"claude"})

#: Vocabulario Claude Code. Explicito (nao derivado): `/model haiku` e um
#: modelo legitimo que nenhuma tabela de traducao jamais listou.
_CLAUDE_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})
_CLAUDE_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "max"})

#: Todo head que carrega modelo/effort em qualquer dialeto que a fila possa ter
#: guardado. `/reasoning` continua aqui mesmo sem ser mais produzido: filas
#: salvas antes de 2026-08-17 podem trazer a linha, e ela precisa ser
#: reconhecida como diretiva para ser suprimida em vez de virar "comando".
_DIRECTIVE_HEADS: frozenset[str] = frozenset({"/model", "/effort", "/reasoning"})

#: Tokens de modelo que so podem ter vindo da traducao revogada (Codex `sol`/
#: `spark`, Kimi `k3`). Conjunto FECHADO e historico: nao cresce, porque nada
#: mais produz dialeto estrangeiro. Serve so para o dispatcher Claude reconhecer
#: residuo de snapshot.
_LEGACY_FOREIGN_MODEL_TOKENS: frozenset[str] = frozenset({"sol", "spark", "k3"})


def is_directive_line(name: str) -> bool:
    """True para uma linha de modelo/effort em qualquer dialeto conhecido.

    Casa o token EXATO em inicio de linha: `/model-foo` e um comando de projeto
    que mencione `/effort` no meio do texto NAO casam (mesmo rigor de C-42 que
    o sentinel de delegacao aplica). Usado pelos dispatchers para decidir se a
    linha entra no tratamento de diretiva, antes de saber se ela e nativa.
    """
    parts = (name or "").strip().split()
    return bool(parts) and parts[0].lower() in _DIRECTIVE_HEADS


def is_native_directive(name: str, main_llm: str) -> bool:
    """True se `name` pode ir raw ao terminal do `main_llm`.

    So o Claude Code tem diretiva textual de modelo/effort. Para todo o resto
    isto e sempre False — e por isso o dispatcher de cada CLI nao-Claude
    suprime + pulsa qualquer diretiva que chegue nele (residuo de snapshot, ou
    fila enfileirada sob Claude e depois trocada de Main).

    Discrimina por VOCABULARIO, nao por marca no `CommandSpec`: o dispatcher
    recebe texto, e texto e o unico contrato estavel entre enqueue e dispatch.
    """
    parts = (name or "").strip().split()
    if len(parts) < 2:
        # `/model` pelado nunca e nativo: nao ha valor para o CLI aplicar.
        return False
    head, value = parts[0].lower(), parts[1].lower()
    main = (main_llm or "").strip().lower()

    if main not in MAIN_LLMS_WITH_NATIVE_DIRECTIVES:
        return False

    if head == "/model":
        return value in _CLAUDE_MODELS
    return head == "/effort" and value in _CLAUDE_EFFORTS


def is_foreign_directive(name: str) -> bool:
    """True se `name` esta num dialeto que CLI nenhum em uso entende.

    Guard do lado Claude, e **fail-open por construcao**: reprova apenas o que
    e comprovadamente residuo da traducao revogada (`/model sol high`,
    `/model spark low`, `/model k3`, `/reasoning ...`) e deixa passar qualquer
    outra diretiva. A assimetria e deliberada — negar tudo que nao esta no
    vocabulario suprimiria `/model haiku` e qualquer effort futuro do Claude
    Code, e suprimir diretiva legitima do Main default e estrago maior do que
    deixar passar um literal exotico.
    """
    parts = (name or "").strip().split()
    if not parts:
        return False
    head = parts[0].lower()
    if head == "/reasoning":
        # Nunca existiu: nem no Kimi (que responde `Unknown slash command`),
        # nem no Claude Code. So pode ser residuo.
        return True
    if head == "/model" and len(parts) > 1:
        return parts[1].lower() in _LEGACY_FOREIGN_MODEL_TOKENS
    return False


def adapt_specs_to_main(
    specs: list[CommandSpec], main_llm: str
) -> list[CommandSpec]:
    """Remove as diretivas `/model`/`/effort` quando o Main nao as entende.

    Funcao PURA: nao muta `specs` nem os `CommandSpec` recebidos. `position`
    NAO e renumerado aqui — quem chama (`load_pipeline`) ja renumera 1-based
    depois de inserir, e renumerar duas vezes esconderia bug de contagem.

    IDEMPOTENTE por construcao: a segunda passada nao encontra mais diretiva
    nenhuma para remover. Isso importa porque `restore_queue_snapshot`
    reconstroi os specs a partir dos nomes ja renderizados e chama
    `load_pipeline` de novo.

    Identidade garantida (mesma lista, mesmos objetos) quando:
      - `main_llm` e `claude` ou qualquer valor desconhecido (fail-open);
      - a lista nao contem nenhuma linha de diretiva.
    """
    main = (main_llm or "").strip().lower()
    if main not in PROVIDERS_WITHOUT_MODEL_DIRECTIVES:
        return specs
    # O predicado e `is_directive_line`, nao "dialeto Claude": uma linha em
    # dialeto congelado de outro Main (`/model k3`, restaurada de snapshot)
    # tambem nao tem nada que este CLI possa aplicar, entao tambem sai.
    kept = [s for s in specs if not is_directive_line(s.name)]
    return specs if len(kept) == len(specs) else kept
