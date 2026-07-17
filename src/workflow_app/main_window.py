"""
MainWindow — Workflow App shell (module-01/TASK-3 + module-14/TASK-4).

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │ MetricsBar (48px)                                           │
  │ ConfigBar (48px)  [⬡ project]  [Workflow][Comandos]         │
  ├─────────────────────────────────────────────────────────────┤
  │ ViewStack (QStackedWidget):                                 │
  │   Page 0 — Workflow:                                        │
  │     QSplitter: CommandQueueWidget(280px) | LeftTabWidget    │
  │       Tab 0: (toolbox header removido) + OutputPanel        │
  │       Tab 1: History (FilterPanel + list + detail)          │
  │   Page 1 — Comandos:                                        │
  │     TemplateBuilderWidget (full width)                      │
  │   Page 2 — Kanban:                                          │
  │     KanbanView (full width)                                 │
  │   Page 3 — Module Detail:                                   │
  │     ModuleDetailView (full width)                           │
  └─────────────────────────────────────────────────────────────┘

Window: resize(1280, 720), setMinimumSize(1024, 600)
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import yaml
from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.add_command_dialog import AddCommandDialog
from workflow_app.command_queue.command_queue_widget import (
    PERSONA_FILTER_CATEGORIES,
    PERSONA_FILTER_DEFAULT,
    PROMPT_FILTER_CATEGORIES,
    PROMPT_FILTER_DEFAULT,
    CommandQueueWidget,
)
from workflow_app.config.app_state import app_state
from workflow_app.config.config_bar import ConfigBar
from workflow_app.config.config_parser import parse_config
from workflow_app.domain import CommandSpec
from workflow_app.errors import ConfigError
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.services.delivery_reader import DeliveryReader
from workflow_app.services.lock_service import LockService
from workflow_app.signal_bus import signal_bus
from workflow_app.template_builder.template_builder_widget import TemplateBuilderWidget
from workflow_app.views.kanban import KanbanView
from workflow_app.views.module_detail import ModuleDetailView
from workflow_app.widgets.execution_detail_panel import ExecutionDetailPanel
from workflow_app.widgets.execution_history_widget import ExecutionHistoryWidget
from workflow_app.widgets.filter_panel import FilterPanel
from workflow_app.widgets.mcp_prompt_actions import append_public_context, build_prompt
from workflow_app.widgets.mcp_prompt_button import (
    VALID_ACTIONS,
    VALID_BUTTON_TYPES,
    VALID_TERMINALS,
    MCPPromptButton,
)
from workflow_app.widgets.toast_notifier import ToastNotifier
from workflow_app.widgets.version_update_banner import VersionUpdateBanner


class _BrainstormSeedError(ValueError):
    """Seed invalido em blacksmith/brainstorm-mcp/0[1-9]-*.md."""


# Mapping canonico slug->display do radio de provider runtime
# (T3 do loop 05-21-implantation-tasklist-aba-brainstorm).
# Slugs lowercase sao a source-of-truth interna; o capitalize ocorre
# apenas no momento de gerar prompt/UI para nao depender de button.text()
# (fragil a i18n + refactor de label, cf. hardening §1/§2 da task).
_BRAINSTORM_PROVIDER_LABELS: dict[str, str] = {
    "claude": "Claude",
    "kimi": "Kimi",
    "codex": "Codex",
}
_BRAINSTORM_PROVIDER_SLUGS: frozenset[str] = frozenset(_BRAINSTORM_PROVIDER_LABELS)


# QSS canonico do gear (reuso do toolbar-prompts-config-gear original em
# main_window.py:1517-1537). Aplicado pelo `_GearButton` abaixo.
_GEAR_QSS = (
    "QPushButton { background-color: #3F3F46;"
    "  border: 1px solid #52525B; border-radius: 5px; padding: 0; }"
    "QPushButton:hover { background-color: #52525B; border-color: #71717A; }"
    "QPushButton:pressed { background-color: #FBBF24; }"
    "QPushButton:pressed QLabel { color: #18181B; }"
)


class _GearButton(QPushButton):
    """Botao gear 24x24 reutilizavel.

    Hierarquia `QPushButton + QLabel filho com WA_TransparentForMouseEvents`
    preserva o click-target (cf. hardening §8 task-005 do loop
    05-21-implantation-tasklist-aba-brainstorm). QSS compartilhado via
    `_GEAR_QSS` (mesmo bloco do `toolbar-prompts-config-gear`).
    """

    def __init__(
        self,
        testid: str,
        tooltip: str,
        parent: QWidget | None = None,
        size: int = 24,
        font_px: int = 12,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setProperty("testid", testid)
        self.setStyleSheet(_GEAR_QSS)
        label = QLabel("⚙", self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"color: #FAFAFA; font-size: {font_px}px;"
            " background: transparent; border: none;"
        )
        label.setGeometry(0, 0, size, size)


_SEED_MAX_BYTES = 64 * 1024
_SEED_REQUIRED_KEYS = {
    "slug",
    "button_type",
    "agent_name",
    "agent_path",
    "action",
    "target_path",
}
_SEED_TARGET_TERMINAL_RUNTIME_SENTINEL = "depende-do-radio"

logger = logging.getLogger(__name__)

# ── Directory shortcuts for the Workspace terminal label bar ─────────────── #
# main_window.py lives at: .../systemForge/ai-forge/workflow-app/src/workflow_app/
_WORKFLOW_APP_DIR = str(Path(__file__).resolve().parents[2])  # .../ai-forge/workflow-app
_SYSTEMFORGE_DIR  = str(Path(__file__).resolve().parents[4])  # .../systemForge

# Task 7 (loop 05-13-workflow-app-layout-2): prompt longo literal embutido,
# preservado byte-a-byte (sha256 d70879ea1e07618ae5ad26f024558c232dde70e5f587c5f8416a3064ab90787e)
# das linhas 97-319 de blacksmith/loop-archives/05-13-workflow-app-layout-2/source.md.
# Tratado como literal — nao parsear, nao interpolar, nao executar.
PROGRESS_PROMPT = """\
Sistema de Execucao Adversarial com Double-MCP + Codex Review
Objetivo
Analise profundamente o problema informado utilizando /mcp:dual, defina a melhor solucao tecnica, proponha uma arquitetura adequada e gere uma sequencia de tasks tecnicas executaveis.
Apos gerar as tasks:
Execute-as sequencialmente.
Faca revisao adversarial obrigatoria via /mcp:codex em cada task.
Faca uma revisao holistica final do conjunto completo.
Mantenha rastreabilidade continua em PROGRESS.md.

FASE 1 — DISCUSSAO E PLANEJAMENTO
1. Debate tecnico inicial
Utilize /mcp:dual para:
Identificar a causa raiz do problema.
Debater alternativas de solucao.
Avaliar tradeoffs tecnicos.
Identificar riscos arquiteturais.
Definir a solucao mais robusta e sustentavel.
Definir arquitetura final da implementacao.
O debate deve produzir:
Diagnostico do problema.
Estrategia escolhida.
Arquitetura proposta.
Dependencias afetadas.
Riscos conhecidos.
Criterios de aceite globais.

2. Geracao das tasks
Com base na arquitetura definida:
Crie uma lista de tasks:
Sequenciais.
Atomicas.
Executaveis.
Testaveis.
Sem sobreposicao.
Ordenadas logicamente.
Com criterios de aceite explicitos.
Cada task deve conter:
Objetivo.
Escopo.
Criterios de aceite.
Arquivos potencialmente afetados.
Dependencias de outras tasks.
IMPORTANTE:
Nao criar tasks vagas.
Nao criar tasks excessivamente grandes.
Nao misturar refactor amplo com correcao funcional.
Nao introduzir escopo novo sem justificativa explicita.

3. Revisao previa das tasks
Antes de executar qualquer task:
Utilize /mcp:codex para revisar toda a lista de tasks em modo adversarial.
O review deve validar:
Ordem logica.
Cobertura completa do problema.
Ausencia de gaps.
Ausencia de redundancias.
Riscos de regressao.
Clareza dos criterios de aceite.
Coerencia arquitetural.
Somente apos aprovacao iniciar execucao.

FASE 2 — SETUP OBRIGATORIO
1. Criar PROGRESS.md
Criar PROGRESS.md na raiz do projeto contendo:
Cabecalho
Objetivo.
Data.
Escopo.
Fonte/origem das tasks.
Arquitetura definida.
Regras operacionais.

Tabela de rastreabilidade
#
Task
Status
Codex Verdict
Evidencia
Notas

Status validos:
pending
in-progress
review
done
blocked
Inicialmente:
Todas as tasks devem comecar como pending.

2. Regras de integridade
Nao e permitido:
Reordenar tasks arbitrariamente.
Criar tasks extras sem justificativa.
Alterar escopo silenciosamente.
Pular revisao adversarial.
Toda mudanca estrutural deve ser registrada em Notas.

FASE 3 — LOOP OPERACIONAL POR TASK
Para cada task k = 1..N:

Etapa 1 — Inicio
Atualizar imediatamente o PROGRESS.md:
Status -> in-progress

Etapa 2 — Implementacao
Implementar a task:
Da forma mais minima possivel.
Sem refactors fora do escopo.
Sem mudancas especulativas.
Sem antecipar tasks futuras.
Priorizar:
Clareza.
Determinismo.
Isolamento.
Baixo risco de regressao.

Etapa 3 — Review adversarial obrigatorio
Atualizar status:
review
Invocar /mcp:codex em modo adversarial review passando:
Descricao completa da task.
Criterios de aceite.
Diff gerado.
Arquivos alterados.
Contexto arquitetural relevante.
O review deve validar:
Se a implementacao realmente resolve a task.
Se houve regressao.
Se existe codigo orfao.
Se existem estados indefinidos.
Se ha inconsistencias arquiteturais.
Se o codigo segue CLAUDE.md.

Etapa 4 — Interpretacao do veredito
Se APROVADO
Marcar task como done.
Registrar:
Veredito.
Evidencias.
Arquivos alterados.
Paths relevantes.
Linhas-chave.
Observacoes relevantes.

Se RESSALVAS
Corrigir problemas.
Reexecutar /mcp:codex.
Maximo de 3 rodadas.
Se exceder 3 rodadas:
Marcar como blocked.
Registrar motivo detalhado.
Continuar somente se o bloqueio nao inviabilizar tasks dependentes.

Se REPROVADO
Corrigir obrigatoriamente antes de avancar.
Reexecutar review.
Maximo de 3 rodadas.
Persistindo falha:
Marcar blocked.
Registrar justificativa tecnica completa.
Solicitar intervencao do usuario se necessario.

Etapa 5 — Gate obrigatorio
Nunca avancar para k+1 enquanto k nao estiver:
done
OU
blocked com justificativa explicita registrada.

FASE 4 — REVISAO HOLISTICA FINAL
Apos todas as tasks:
Executar /mcp:codex novamente em modo adversarial holistico.
O review final deve validar:
Cobertura
Alguma task original ficou parcialmente implementada?
Alguma implementacao ficou incompleta?
Coerencia
Contradicoes entre tasks.
Regressoes.
Codigo morto.
Codigo orfao.
Duplicacoes.
Integracao
Compatibilidade entre mudancas.
Fluxos quebrados.
Acoplamentos perigosos.
Gaps entre tasks.
Qualidade transversal
Validar regras invioalveis do projeto:
Zero Orfaos
Zero Silencio
Zero Estados Indefinidos
ECU
Demais regras descritas em CLAUDE.md

FASE 5 — REGISTRO FINAL
Adicionar ao PROGRESS.md:
Revisao Final
Conteudo obrigatorio:
Veredito final.
Gaps encontrados.
Correcoes aplicadas.
Riscos remanescentes.
Limitacoes conhecidas.
Observacoes arquiteturais.
Estado final do sistema.

REGRAS GERAIS (INVIOLAVEIS)
Atualizar PROGRESS.md imediatamente apos cada transicao de status.
Nunca atualizar status em batch.
Nunca pular o gate do /mcp:codex.
Nunca ocultar falhas.
Nunca assumir comportamento implicito sem validacao.
Em caso de bloqueio critico insoluvel:
Parar.
Explicar claramente.
Solicitar direcionamento do usuario.

RELATORIO FINAL OBRIGATORIO
Ao final da execucao, reportar:
Quantidade de tasks done
Quantidade de tasks blocked
Resumo executivo da implementacao
Principais riscos remanescentes
"""


# NEXT MODULE — referencia curta para o agente.
# Toda a documentacao detalhada (estrutura do SPECIFIC-FLOW.json, presence flags,
# fases, armadilhas, condicoes) foi extraida para ai-forge/rules/dcp-cmd-list-build.md
# em 2026-05-17. O slot publica apenas a instrucao de leitura — o agente segue dali.
NEXT_MODULE_PROMPT = (
    "leia o ai-forge/rules/dcp-cmd-list-build.md para entender as regras antes "
    "de fazer a implantacao do proximo module DCP. O documento referenciado cobre "
    "identificacao do proximo module, presence flags, fases A..I, gates obrigatorios, "
    "armadilhas conhecidas e checklist de validacao. Regras de /clear, /model e "
    "/effort vivem em ai-forge/rules/workflow-app-command-lists.md."
)


# Online Review — auditoria do remoto/producao do workspace_root do projeto
# ativo (consultar metrics-project-pill / app_state.config). Publica um
# prompt que orienta o agente a acessar repositorio remoto, infra de
# deploy, MCPs e credenciais (SSH/tokens) para testar, corrigir e gerar
# relatorio. Tratado como literal — nao parsear, nao interpolar.
ONLINE_REVIEW_PROMPT = """\
Online Review — Auditoria do remoto/producao do projeto carregado

Objetivo
Acessar o repositorio remoto e o ambiente de producao do projeto exibido em metrics-project-pill (workspace_root configurado em .claude/projects/{slug}.json), executar bateria de testes em producao, identificar e corrigir problemas e gerar relatorio.

FASE 1 — Inventario de acessos
1. Resolver projeto ativo: ler .claude/projects/{slug}.json a partir de app_state.config (workspace_root, project_dir, hosting, database, target_stack).
2. Listar credenciais disponiveis em credentials.* (github, ssh, vercel, railway, expo_eas, supabase, sentry, dns, cloudflare, hosting_platform, docker_registry, mcp_servers). Mascarar valores em log ({first10}***{last4}).
3. Listar MCPs habilitados consultando .mcp.json + credentials.mcp_servers (Tavily, Firecrawl, Perplexity, Playwright, Axe-core, Supabase, Codex, Kimi).
4. Identificar deploy target (Vercel/Railway/Hostinger/Hostgator/Expo/static) a partir de config.hosting.

FASE 2 — Acesso remoto
1. GitHub: comparar HEAD local x remoto via GITHUB_TOKEN (commits ahead/behind, PRs abertos, status checks da branch main).
2. SSH (quando aplicavel): conectar com ssh.host/user/port/pass, coletar uptime, processos do app, ultimas linhas dos logs de erro.
3. Provider API: vercel deployments list / railway service status / expo build:list / supabase project status / hosting platform health.
4. DNS/Cloudflare: validar A/AAAA/CNAME do dominio principal e zonas ativas.

FASE 3 — Testes em producao
1. Health-check do dominio principal: HTTP status, TTFB, SSL valido, headers de seguranca.
2. Smoke tests das rotas publicas criticas (homepage, login, dashboard, APIs core do projeto).
3. E2E Playwright dos fluxos principais (auth, checkout, formularios primarios) — somente se Playwright MCP estiver habilitado.
4. Conferir runtime env vars sem expor valores: vercel env ls / railway variables list — comparar com requisitos do projeto.
5. Auditar logs de erro recentes (Sentry/Vercel logs/Supabase logs) das ultimas 24h e classificar por severidade.

FASE 4 — Diagnostico e correcao
1. Listar problemas encontrados com severidade (critical/high/medium/low) + causa raiz.
2. Aplicar correcoes triviais (configs, headers, redirects, env vars faltantes) — commitar em main seguindo trunk-based (sem feature branches).
3. Correcoes nao triviais: abrir tasks no wbs_root e registrar em pending-actions/{slug}.md.
4. Validar cada correcao re-executando o teste do cenario afetado.

FASE 5 — Relatorio
Gerar output/online-review/{slug}-{YYYY-MM-DD-HHMM}.md com:
- Sumario executivo (verde / amarelo / vermelho) e veredito global.
- Inventario de acessos consultados (com credenciais mascaradas).
- Resultados dos testes em tabela (cenario, esperado, observado, status).
- Problemas encontrados (severidade, causa raiz, correcao aplicada ou pendente).
- Commits gerados (sha + arquivos) e tasks abertas.
- Acoes pendentes propagadas para pending-actions/{slug}.md.
- Riscos remanescentes e proximas validacoes recomendadas.

REGRAS (INVIOLAVEIS)
- Nunca commitar arquivos com segredos (.env, credenciais).
- Nunca executar destruicoes em producao sem confirmacao humana explicita (drop, force-push, delete deployment, rollback de banco).
- Nunca skipar hooks ou bypassar gates de seguranca.
- Toda credencial ausente vira gap em pending-actions/{slug}.md com idempotency key + abortar etapa dependente.
- Mascarar tokens, senhas e URLs sensiveis em qualquer output ({first10}***{last4}).
- Trabalho sempre em main (trunk-based). Rollback via git revert, nunca via branch nova.
"""


# Task 8 (workflow-rules — DCP mechanics): guia detalhado das regras que governam
# SPECIFIC-FLOW.json: como /clear, /model, /effort funcionam, persistencia de estado,
# quando mudar de modelo (Opus/Sonnet) sem resetar desnecessariamente, e padroes
# de grupos de comandos. Tratado como literal — nao parsear, nao interpolar.
WORKFLOW_RULES_PROMPT = """\
🎯 REGRAS PADRÃO DE SPECIFIC-FLOW.json — Sistema de Diretivas DCP

OBJETIVO
Entender exatamente como /clear, /model e /effort funcionam em SPECIFIC-FLOW.json,
como o estado persiste entre comandos, quando resetar com /clear, e por que a
estrutura de grupos é crítica para evitar vazamento de configuração.

═══════════════════════════════════════════════════════════════════════════════

FUNDAÇÃO: TRINITY OF DIRECTIVES

Todo SPECIFIC-FLOW.json é construído sobre 3 directives especiais que nao sao
comandos reais, mas SIM CONFIGURADORES DE ESTADO:

1. **/model {opus|sonnet}**
   - Define qual Claude vai executar o PROXIMO comando
   - PERSISTE para comandos seguintes até novo /model encontrado
   - Influencia: tempo de execucao, custo, qualidade de reasoning
   - DEFAULT (se nao especificado): sonnet (recomendado, equilibrio custo-qualidade)

2. **/effort {low|medium|high}**
   - Define quantos tokens e quantas tentativas o Claude usa
   - PERSISTE para comandos seguintes até novo /effort encontrado
   - low: rapido, menos raciocinio, bom para tarefas triviais
   - medium: padrao, equilibrio entre qualidade e velocidade
   - high: raciocinio profundo, melhor qualidade, mais caro
   - DEFAULT (se nao especificado): medium

3. **/clear**
   - RESETA ambos /model e /effort para defaults (sonnet, medium)
   - NAO e opcional — obrigatorio no fim de cada grupo de comandos
   - Previne vazamento de configuracao para comandos indesejados
   - CONSEQUENCIA DE OMISSAO: o proximo comando herda model/effort do anterior

═══════════════════════════════════════════════════════════════════════════════

PADRÃO DE GRUPO CANÔNICO

Toda sequencia de comandos DEVE seguir este padrao:

```json
[
  {
    "name": "/model opus",
    "model": "opus",
    "effort": "none",
    "interaction": "auto",
    "phase": "FASE_X_NAME"
  },
  {
    "name": "/effort high",
    "model": "none",
    "effort": "high",
    "interaction": "auto",
    "phase": "FASE_X_NAME"
  },
  {
    "name": "{COMANDO-REAL}",
    "model": "opus",         // Herda do /model anterior
    "effort": "high",        // Herda do /effort anterior
    "interaction": "auto",
    "phase": "FASE_X_NAME"
    // campos opcionais: per_task, mandatory, condition, source_ref, gate_policy
  },
  {
    "name": "/clear",
    "model": "none",
    "effort": "none",
    "interaction": "auto",
    "phase": "FASE_X_NAME"   // Mesma fase do grupo
  }
]
```

REGRA INVIOLÁVEL: /clear SEMPRE no final. Nunca omita.

═══════════════════════════════════════════════════════════════════════════════

QUANDO CADA MODELO?

### Opus (reasoning complexo, decisoes estruturais)
  Uso: criacao de arquitetura, design decisions, analise profunda, argumentacao
  Exemplos:
    - /create-task (cria estrutura completa da tarefa)
    - /tdd:create-suite (desenha suite de testes)
    - /review-executed-module (analisa qualidade, decision gate)
  effort: high (exigem raciocinio profundo)
  Custo: ~3x mais caro que sonnet

### Sonnet (implementacao, execucao, tarefas padroes)
  Uso: DEFAULT — implement features, build, tests, refactor operacionais
  Exemplos:
    - /execute-task (codificar)
    - /front-end-build (componentizar)
    - /qa:trace (executar testes)
  effort: medium (padroes conhecidos, nao precisa raciocinio pesado)
  Custo: ~1x (baseline)

⚠️ HEURISTICAS:
- Sonnet e suficiente para 90% dos casos (inclusive operacoes mecanicas e determinísticas)
- Opus APENAS quando reasoning/creativity sao critticos
- Quando em duvida: use Sonnet + effort=medium

═══════════════════════════════════════════════════════════════════════════════

PERSISTÊNCIA DE ESTADO: EXEMPLOS

### Exemplo 1 — Mudança de modelo SEM /clear (ERRADO)

```json
[
  {"name": "/model opus", "model": "opus", "effort": "none", ...},
  {"name": "/effort high", "model": "none", "effort": "high", ...},
  {"name": "/create-task", "model": "opus", "effort": "high", ...},
  // FALTOU /clear aqui!
  {"name": "/execute-task", "model": "sonnet", "effort": "medium", ...}
  // ⚠️ /execute-task HERDA opus + high do grupo anterior!
  // Resultado: executada por Opus em high — muito mais caro e lento do que necessario
]
```

### Exemplo 2 — Mudança de modelo COM /clear (CORRETO)

```json
[
  {"name": "/model opus", "model": "opus", ...},
  {"name": "/effort high", "model": "none", "effort": "high", ...},
  {"name": "/create-task", "model": "opus", "effort": "high", ...},
  {"name": "/clear", "model": "none", "effort": "none", ...},  // ← RESET

  {"name": "/model sonnet", "model": "sonnet", ...},  // Novo grupo
  {"name": "/effort medium", "model": "none", "effort": "medium", ...},
  {"name": "/execute-task", "model": "sonnet", "effort": "medium", ...},
  {"name": "/clear", "model": "none", "effort": "none", ...}
]
```

### Exemplo 3 — Mesmo modelo em vários comandos (SEM /clear entre eles)

```json
[
  {"name": "/model sonnet", ...},
  {"name": "/effort medium", ...},
  {"name": "/execute-task TASK-1", "model": "sonnet", "effort": "medium", ...},
  {"name": "/execute-task TASK-2", "model": "sonnet", "effort": "medium", ...},
  {"name": "/execute-task TASK-3", "model": "sonnet", "effort": "medium", ...},
  // Sem /clear entre TASK-1/2/3 — estado PERSISTE (desejado!)
  // Todos executam com sonnet + medium
  {"name": "/clear", ...}  // Reset final
]
```

LECCAO: Omitir /clear entre comandos que QUEREM o mesmo modelo e effort e CORRETO.
Omitir /clear quando ha MUDANCA de modelo e CRITICO (erro).

ATENCAO (multiplicidade per-task — fix loop 06-08/06-09): os nomes TASK-1/2/3 acima sao
ILUSTRATIVOS do agrupamento de diretivas. Ao construir uma lista real, a quantidade e os
nomes dos comandos per-task (/create-task, /execute-task, /review-*-task) vem SEMPRE da
enumeracao dos arquivos reais `TASK-*.md` do module ({wbs_root}/modules/{module_id}/,
padrao `^TASK-(\\d+(?:\\.\\d+)?)\\.md$`, companions tipo TASK-1-REVIEW.md excluidos) — NUNCA
de um contador, range(1..N) ou do loop_multiplier. Modules reais comecam em TASK-0, tem
lacunas e indices decimais; sintetizar por contagem gera "task N nao existe" (fantasma)
e deixa tasks reais descobertas. Regra completa: ai-forge/rules/dcp-cmd-list-build.md §21.

═══════════════════════════════════════════════════════════════════════════════

QUANDO MUDAR DE MODELO NO MEIO DA LISTA?

### Regra Prática: Menos trocas = melhor

Organizar a lista por modelo reduz /clear overhead:

```json
// BOM:
[
  /model opus, /effort high, /create-task, /create-overview, /clear,
  /model sonnet, /effort medium, /execute-task x3, /clear,
  /model sonnet, /effort low, /github-linking, /clear
]

// RUIM:
[
  /model opus, /effort high, /create-task, /clear,
  /model sonnet, /effort medium, /execute-task, /clear,
  /model opus, /effort high, /tdd:create-suite, /clear,  // Volta para opus = caótico
]
```

### Grupos Canônicos do DCP (Exemplo: module-0)

```
FASE_A_CREATION:
  opus/high: /create-task ×N, /create-overview
  [/clear]
  sonnet/medium: /update-task-user-stories
  [/clear]

FASE_B_TDD:
  opus/high: /tdd:create-suite
  [/clear]
  sonnet/medium: /tdd:lock
  [/clear]

FASE_B2_BUILD:
  sonnet/medium: /front-end-build, /back-end-build, /db-migration-create
  [/clear]

FASE_B3_EXECUTION:
  sonnet/medium: /execute-task ×N
  [/clear]

FASE_D5_MODULE_REVIEW:
  opus/high: /review-executed-module, /tdd:mutation-gate (se aplicavel)
  [/clear]
```

Padrão: Opus para decisoes/reasoning (phases A, D5), Sonnet para implementacao (B, B2, B3).
Nota: o `×N` acima = um comando POR ARQUIVO `TASK-*.md` real do module (enumerar o
diretorio; nunca sintetizar de contagem/loop_multiplier — ver ATENCAO da secao anterior).

═══════════════════════════════════════════════════════════════════════════════

ATRIBUTOS OBRIGATÓRIOS EM CADA STEP

```json
{
  "name": "{string, slash-command com args}",
  "model": "{opus|sonnet|none}",                // OBRIGATORIO
  "effort": "{low|medium|high|none}",           // OBRIGATORIO
  "interaction": "auto",                        // Sempre "auto" (nao modificar)
  "phase": "{FASE_X_NAME}",                     // Sempre especificar

  // OPCIONAIS — so quando aplicavel:
  "per_task": true,                             // Se comando itera sobre tasks
  "mandatory": true,                            // Se eh gate bloqueante
  "condition": "{expressao de predicado}",      // Se condicional a presence flags
  "source_ref": "§6.4 L1147",                   // Referencia ao profiles.py
  "gate_policy": {                              // Se eh gate
    "on_failure": "block",
    "source": "canonical"
  }
}
```

═══════════════════════════════════════════════════════════════════════════════

CHECKLIST DE VALIDAÇÃO

☐ Cada grupo de comandos comeca com /model + /effort?
☐ Cada grupo de comandos termina com /clear?
☐ /model none aparece APENAS em /model directive (nunca em comando real)?
☐ /effort none aparece APENAS em /clear ou /model directives?
☐ Não há comando real com model=none ou effort=none (herdarão do anterior)?
☐ Transicoes de modelo estão agrupadas logicamente (opus junto, sonnet junto)?
☐ JSON é valido: python3 -m json.tool < SPECIFIC-FLOW.json?
☐ Fases estão em ordem A → B_TDD → B2 → B3 → C → D → D5 → E → F → F2 → H → I?
☐ Todos os comandos com condition tem seu predicado em profiles.py?
☐ Gates obrigatorios (ex: /delivery:sign-off) tem mandatory=true?

═══════════════════════════════════════════════════════════════════════════════

DICAS PARA EVITAR ARMADILHAS

1. **Copie de module-0** — padrão jah validado, evita inventar
2. **Mantenha /model/effort em bloco** — nao intercale directives com comandos
3. **Valide com jq**: jq '.[] | select(.effort=="none" and .name!="/clear" and .name!="/model") | .name' SPECIFIC-FLOW.json
4. **Se modelo nao mudar** — deixe /clear fora, deixe estado persistir (economy)
5. **Se modelo DEVE mudar** — novo /model + novo /effort + /clear anterior (obrigatorio)
6. **Nao edite manualmente** — use generator.py como autoridade final

═══════════════════════════════════════════════════════════════════════════════

REFERÊNCIA RÁPIDA: MODELS E EFFORTS

| Model | Quando | Custo | Effort | Quando |
|-------|--------|-------|--------|--------|
| opus | Reasoning complexo, criacao, design | ~3x | high | Decisões críticas |
| sonnet | Default, implementacao, build, operacoes mecanicas | ~1x | medium | Maioria dos casos |

═══════════════════════════════════════════════════════════════════════════════

RESUMO FINAL

- /clear e MANDATORIO no fim de cada grupo
- /model e /effort PERSISTEM ate proximo /clear ou nova declaracao
- Opus para reasoning, Sonnet para implementacao
- Agrupar por modelo reduz /clear overhead
- Validar sempre com generator.py, nao edite manualmente
- Module-0 e referencia — copie sua estrutura
"""


_DATATEST_FILTERED_IDS = frozenset({
    "metrics-project-pill",
    "progress-section",
    "listeners-frame",
    "queue-btn-play-next-container",
    "queue-command-list",
    "output-toolbar-left",
    "output-toolbar-center",
    "terminal-route-toggles",
    "output-toolbar-mcp",
    "output-toolbar-test-mode",
    "terminal-interactive",
    "terminal-workspace",
    # Fix T020 (BLOCKER 2) loop 05-21-implantation-tasklist-aba-brainstorm:
    # testid canonico do panel T3 (Codex) e `terminal-codex-output` conforme
    # mcp-flow-implantation-base-archive.md §10.5. Antes era
    # `terminal-workspace-xterm` (so casava o nome interno), o que fazia
    # `_codex_terminal_available()` retornar False sempre. Contrato mantido
    # apos T3 migrar de xterm para pyte (2026-06-01).
    "terminal-codex-output",
})

# NOTE (2026-06): o antigo `_MODAL_TESTIDS` (allowlist curado de testids de
# modal) foi REMOVIDO. O botao ModalTest agora renderiza TODOS os testids
# visiveis dentro do dialog ativo via `_show_modal_testid_overlays` — o
# allowlist estatico ficava defasado e deixava o botao sem efeito em qualquer
# modal novo/nao-catalogado. Espelha o overlay nao-modal (`_show_testid_overlays`).


class ProgressSection(QWidget):
    """Container que hospeda queue-progress-ring + queue-count-label em row.

    Ambos os filhos recebem stretch=1 para que tenham a mesma largura,
    alinhada com a largura dos dots de listeners-frame (listener-interactive
    e listener-workspace).
    Refactor 2026-05-18: extrai a exibicao de progresso do antigo power-bi-section.
    """

    def __init__(self, *, ring, count_label, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressSection")
        self.setProperty("testid", "progress-section")
        from PySide6.QtWidgets import QHBoxLayout, QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#ProgressSection { background-color: #1C1C1F;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        self.setMinimumHeight(108)
        self.setMinimumWidth(224)   # 2×92 + margins(8+8) + spacing(8) + border(1+1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(ring, 1)
        layout.addWidget(count_label, 1)


class DualStatusSection(QWidget):
    """Container responsivo que hospeda progress-section + listeners-frame.

    Em row-mode (largura >= _BREAKPOINT_WIDTH): progress-section a esquerda,
    listeners-frame a direita, ambos com stretch=1 (larguras iguais).
    Em column-mode (largura insuficiente): progress-section no topo,
    listeners-frame embaixo.

    Refactor 2026-05-18: substitui PowerBiSection unificado.
    """

    # Ponto de quebra: soma dos min-w das duas secoes (224 cada) + spacing (8) = 456.
    _BREAKPOINT_WIDTH = 456

    def __init__(self, *, progress_section, listeners_frame, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DualStatusSection")
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._progress_section = progress_section
        self._listeners_frame = listeners_frame
        self._is_row = None
        self._apply_layout(row=True)

    def _apply_layout(self, *, row: bool) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
        from PySide6.QtWidgets import QWidget as _QW
        if self._is_row == row:
            return
        old = self.layout()
        if old is not None:
            old.removeWidget(self._progress_section)
            old.removeWidget(self._listeners_frame)
            _QW().setLayout(old)
        new_layout = QHBoxLayout() if row else QVBoxLayout()
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(8)
        new_layout.addWidget(self._progress_section, 1)
        new_layout.addWidget(self._listeners_frame, 1)
        self.setLayout(new_layout)
        self._is_row = row

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        want_row = self.width() >= self._BREAKPOINT_WIDTH
        if want_row != self._is_row:
            self._apply_layout(row=want_row)


class _DraggableFloatingPanel(QWidget):
    """Floating child panel with bounded drag inside its parent widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.was_dragged = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        parent = self.parentWidget()
        if parent is None:
            return
        top_left_global = event.globalPosition().toPoint() - self._drag_offset
        top_left = parent.mapFromGlobal(top_left_global)
        max_x = max(0, parent.width() - self.width())
        max_y = max(0, parent.height() - self.height())
        self.move(
            min(max(0, top_left.x()), max_x),
            min(max(0, top_left.y()), max_y),
        )
        self.was_dragged = True
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """Main application window."""

    _SETTINGS_GEOMETRY = "MainWindow/geometry"
    _SETTINGS_SPLITTER = "MainWindow/splitterSizes"
    _SETTINGS_LAST_CONFIG = "Project/lastConfigPath"

    # Emitido quando os seeds brainstorm-mcp foram regravados via gear modal
    # (T4 do loop 05-21-implantation-tasklist-aba-brainstorm). Slot
    # `_rebuild_brainstorm_grid` reconstroi a grade sem mem leak.
    _brainstorm_grid_invalidated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SystemForge Desktop")
        self.setMinimumSize(640, 480)
        self.resize(1280, 720)
        self.setObjectName("MainWindow")

        # Pipeline execution state (RF03)
        self._pipeline_manager = None
        self._testid_overlays: list = []
        self._datatest_active = False
        # Task 3 (loop 05-13-workflow-app-layout-2): modo do test-mode column.
        # "off" preserva o default original (overlay desligado na inicializacao).
        self._datatest_mode = "off"
        self._datatest_terminal_write_enabled = False
        self._datatest_panel: _DraggableFloatingPanel | None = None
        self._datatest_panel_button: QPushButton | None = None
        self._px_ruler_toasts: list[QLabel] = []
        self._px_ruler_resize_filter: QObject | None = None

        # Toast dedup para o picker .md da aba brainstorm (T2 do loop
        # 05-21-implantation-tasklist-aba-brainstorm). Idempotencia por sessao:
        # "created" e "mkdir_failed" disparam toast exatamente uma vez;
        # "outside_repo" guarda o ultimo path rejeitado para evitar spam.
        self._brainstorm_toasts: dict[str, bool | str | None] = {
            "created": False,
            "mkdir_failed": False,
            "outside_repo": None,
        }

        # T3 (loop 05-21-implantation-tasklist-aba-brainstorm):
        # slug canonico lowercase do provider ativo para botoes
        # button_type=type-selector-radio-input. Atualizado pelo radio
        # instalado em _build_brainstorm_page (via _on_brainstorm_type_changed).
        # Default canonico = "claude". Display string capitalizada via
        # _BRAINSTORM_PROVIDER_LABELS no consumer.
        self._brainstorm_runtime_type: str = "claude"
        # Debounce do slot _on_mcp_prompt_requested (300ms via QTimer.singleShot).
        self._prompt_in_flight: bool = False
        # Lista de MCPPromptButton instanciados pela grade brainstorm seed-driven.
        self._brainstorm_mcp_btns: list[MCPPromptButton] = []

        self._settings = QSettings("SystemForge", "WorkflowApp")
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_state()
        self._attempt_startup_detection()
        # Modo Remoto removido 2026-05-12 — RemoteServer nao e mais
        # instanciado; signais remote_* permanecem definidos mas sem produtor.

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        central.setStyleSheet("background-color: #18181B;")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # VersionUpdateBanner (hidden by default, shown when templates are outdated)
        self._version_banner = VersionUpdateBanner(parent=central)
        self._version_banner.update_requested.connect(self._on_version_update_requested)
        root_layout.addWidget(self._version_banner)

        # MetricsBar — hidden; owns state machine (dots, timers, signals).
        # Visible children are reparented out before hide() is called.
        self._metrics_bar = MetricsBar(parent=self)
        root_layout.addWidget(self._metrics_bar)

        # ConfigBar (hidden — project selector moved into MetricsBar)
        self._config_bar = ConfigBar(parent=self)
        self._config_bar.hide()
        self._metrics_bar.config_unload_requested.connect(self._unload_config)
        self._metrics_bar.config_reload_requested.connect(self._reload_config)

        # ── ViewStack: 3 pages switched by ConfigBar nav buttons ─────── #
        self._view_stack = QStackedWidget()
        self._view_stack.setObjectName("ViewStack")

        # ── Page 0: Workflow (splitter: CommandQueue + LeftTabWidget) ── #
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("MainSplitter")
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        self._command_queue = CommandQueueWidget(parent=self)
        self._command_queue.setProperty("testid", "main-command-queue")

        # Botao Clear — esvazia o queue-command-list desta instancia.
        # Vive na linha de acoes da fila (nao no MetricsBar nem no bloco de
        # anexos) porque depende diretamente de self._command_queue.
        # Estilo vermelho para sinalizar acao destrutiva, diferenciando dos
        # botoes ambar de selecao de JSON.
        self._clear_queue_btn = QPushButton("Clear")
        self._clear_queue_btn.setProperty("testid", "main-command-queue-clear-btn")
        self._clear_queue_btn.setToolTip("Esvaziar a fila (queue-command-list) desta janela")
        self._clear_queue_btn.setFixedHeight(28)
        self._clear_queue_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #F87171; border: 1px solid #F87171;"
            "  border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 12px; }"
            "QPushButton:hover { background: rgba(248, 113, 113, 0.12); }"
        )
        self._clear_queue_btn.clicked.connect(self._on_clear_queue_clicked)

        # Bloco semantico de anexos como first div inside command queue.
        # Widgets are reparented from MetricsBar (state machine stays in MetricsBar).
        _pill_row = QWidget()
        _pill_row.setObjectName("CommandQueueAttachmentsShell")
        _pill_row.setProperty("testid", "main-command-queue-pill-row")
        _pill_row_layout = QVBoxLayout(_pill_row)
        # Task 1 (loop 05-13-workflow-app-layout-2): margin-top 10 no container que envolve metrics-project-pill.
        _pill_row_layout.setContentsMargins(8, 10, 8, 6)
        _pill_row_layout.setSpacing(4)

        self._attachments_block = QWidget()
        self._attachments_block.setObjectName("AttachmentsBlock")
        self._attachments_block.setProperty("testid", "attachments-block")
        self._attachments_block.setStyleSheet("background: transparent; border: none;")
        _attachments_layout = QVBoxLayout(self._attachments_block)
        _attachments_layout.setContentsMargins(0, 0, 0, 0)
        _attachments_layout.setSpacing(4)

        self._attachments_project_row = QWidget()
        self._attachments_project_row.setProperty("testid", "attachments-project-row")
        self._attachments_project_row.setStyleSheet("background: transparent; border: none;")
        _project_row_layout = QHBoxLayout(self._attachments_project_row)
        _project_row_layout.setContentsMargins(0, 0, 0, 0)
        _project_row_layout.setSpacing(5)
        for _w in (
            self._metrics_bar._project_pill,
            self._metrics_bar._feature_name_input,
            self._metrics_bar._proj_open_btn,
            self._metrics_bar._proj_select_btn,
        ):
            _project_row_layout.addWidget(_w)
        _project_row_layout.addStretch(1)

        self._attachments_loop_row = QWidget()
        self._attachments_loop_row.setProperty("testid", "attachments-loop-row")
        self._attachments_loop_row.setStyleSheet("background: transparent; border: none;")
        _loop_row_layout = QHBoxLayout(self._attachments_loop_row)
        _loop_row_layout.setContentsMargins(0, 0, 0, 0)
        _loop_row_layout.setSpacing(5)
        for _w in (
            self._metrics_bar._loop_pill,
            self._metrics_bar._loop_select_btn,
        ):
            _loop_row_layout.addWidget(_w)
        _loop_row_layout.addStretch(1)

        self._attachments_brainstorm_row = QWidget()
        self._attachments_brainstorm_row.setProperty("testid", "attachments-brainstorm-row")
        self._attachments_brainstorm_row.setStyleSheet("background: transparent; border: none;")
        _brainstorm_row_layout = QHBoxLayout(self._attachments_brainstorm_row)
        _brainstorm_row_layout.setContentsMargins(0, 0, 0, 0)
        _brainstorm_row_layout.setSpacing(5)

        _attachments_layout.addWidget(self._attachments_project_row)
        _attachments_layout.addWidget(self._attachments_loop_row)
        _attachments_layout.addWidget(self._attachments_brainstorm_row)
        _pill_row_layout.addWidget(self._attachments_block)

        _actions_row = QWidget()
        _actions_row.setObjectName("CommandQueueActionsRow")
        _actions_row.setProperty("testid", "main-command-queue-actions-row")
        _actions_row.setStyleSheet("background: transparent; border: none;")
        _actions_row_layout = QHBoxLayout(_actions_row)
        _actions_row_layout.setContentsMargins(8, 0, 8, 6)
        _actions_row_layout.setSpacing(5)
        _actions_row_layout.addWidget(self._clear_queue_btn)
        # Park hidden nav buttons here so MetricsBar is fully decoupled
        for _btn in (self._metrics_bar._btn_workflow, self._metrics_bar._btn_comandos):
            _actions_row_layout.addWidget(_btn)
            _btn.hide()
        _actions_row_layout.addStretch(1)

        # Window label — etiqueta livre para identificar visualmente esta
        # janela quando varias instancias do workflow-app rodam em paralelo.
        # Click + digite. Texto verde, fonte 35, sem persistencia.
        self._window_label = QLineEdit()
        self._window_label.setObjectName("WindowLabelInput")
        self._window_label.setProperty("testid", "main-window-label")
        self._window_label.setPlaceholderText("/")
        self._window_label.setStyleSheet(
            "QLineEdit {"
            " color: #22C55E;"
            " background-color: transparent;"
            " border: none;"
            " font-size: 35px;"
            " font-weight: 600;"
            " padding: 4px 8px;"
            "}"
        )
        # Inserir window_label primeiro (idx 0), depois pill_row (idx 0) para
        # que pill_row fique como primeiro item do main-command-queue (acima
        # de dual-status-section que sera inserido em idx 1 por _build_output_toolbar).
        self._command_queue.layout().insertWidget(0, self._window_label)
        self._command_queue.layout().insertWidget(0, _actions_row)
        self._command_queue.layout().insertWidget(0, _pill_row)

        # MetricsBar no longer has visible children — hide it.
        self._metrics_bar.hide()

        # Output container (refactor 2026-05-12): QTabWidget e a aba
        # "Historico" foram removidos; signal_bus.history_panel_toggled
        # virou no-op via _switch_to_history_tab e _build_history_panel
        # nao e mais invocado em runtime.
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(5)
        # ToolboxHeader removido em 2026-05-12 — substituido pelos quick btns
        # da play bar do CommandQueueWidget (ver AC-1.1 do TASK-1 layout refactor).

        # OutputToolbar (refactor 2026-05-12): faixa unica acima do
        # terminal_splitter. listeners-frame (reparenteado do MetricsBar)
        # na esquerda + os 2 botoes de controle dos terminais (alternar
        # layout + colapsar workspace) na direita. Os botoes
        # JSON/WS/mcp-*/asq-user foram migrados para a 4a div do
        # MetricsBar via _populate_header_actions().
        self._terminal_is_vertical = False
        self._workspace_collapsed = False

        # Row: [queue-header (left, com Prompts/Actions tabs absorvidas)] [queue-toggles] [test-mode]
        # Refactor 2026-05-15 output-toolbar-left consolidation: output-toolbar-center
        # foi deletada inteira. Seus botoes migraram para as tabs Prompts/Actions
        # do CommandQueueHeader (via populate_prompts_tab/populate_actions_tab).
        # output-toolbar-col1-top (`_toolbar_bar`) continua na coluna 1
        # (entre main-window-label e main-command-queue-pill-row).
        _toolbar_bar, _toolbar_left_top = self._build_output_toolbar()

        # Layout em duas linhas:
        # Linha 1: output-toolbar-left | output-toolbar-progress-boxes | output-toolbar-datatest-queue-stack
        # Linha 2: output-toolbar-center | output-toolbar-mcp
        _toolbar_row = QWidget()
        _toolbar_row_layout = QVBoxLayout(_toolbar_row)
        _toolbar_row_layout.setContentsMargins(0, 10, 0, 0)
        _toolbar_row_layout.setSpacing(6)

        # --- Linha 1 ---
        _top_row = QWidget()
        _top_row_layout = QHBoxLayout(_top_row)
        _top_row_layout.setContentsMargins(0, 0, 0, 0)
        _top_row_layout.setSpacing(10)

        # output-toolbar-left: abas primarias (Pipelines/Workflow/Auxiliar/Daily).
        _top_row_layout.addWidget(self._command_queue.header_widget, stretch=1)   # left

        # Slot antes ocupado por output-toolbar-progress-boxes (removido: coluna
        # decorativa sem side effects). Agora hospeda o queue-div-llm-routing
        # reparenteado da play bar do CommandQueueWidget. addWidget reparenteia
        # o box (Main LLM | Parallel Worker | MCP Flags) para esta linha; as
        # secoes MCP + brainstorm sao dobradas nele mais abaixo, apos o
        # _build_mcp_column construir os respectivos radios.
        _top_row_layout.addWidget(self._command_queue._llm_box)                    # llm-routing

        # Ultima coluna empilhada: test-mode em cima, queue-toggles embaixo.
        _queue_toggles_column = self._build_queue_toggles_column()
        _test_mode_column = self._build_test_mode_column()
        _last_column = QWidget()
        _last_column.setObjectName("OutputToolbarDataTestQueueStack")
        _last_column.setProperty("testid", "output-toolbar-datatest-queue-stack")
        _last_column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _last_column.setStyleSheet(
            "QWidget#OutputToolbarDataTestQueueStack { background-color: #1C1C1F;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        _last_column_layout = QVBoxLayout(_last_column)
        _last_column_layout.setContentsMargins(6, 6, 6, 6)
        _last_column_layout.setSpacing(6)
        _last_column_layout.addWidget(_test_mode_column)
        _last_column_layout.addWidget(_queue_toggles_column)
        _top_row_layout.addWidget(_last_column)                                    # test-mode + queue-toggles

        _toolbar_row_layout.addWidget(_top_row)

        # --- Linha 2 ---
        _bottom_row = QWidget()
        _bottom_row_layout = QHBoxLayout(_bottom_row)
        _bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        _bottom_row_layout.setSpacing(10)

        # output-toolbar-center: controles de inserções (Inserções tab + route-toggles
        # + gear) + conteúdo da aba Inserções.
        _center_widget = QWidget()
        _center_widget.setObjectName("OutputToolbarCenter")
        _center_widget.setProperty("testid", "output-toolbar-center")
        _center_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _center_widget.setStyleSheet(
            "QWidget#OutputToolbarCenter { background-color: #1E1E21;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        _center_layout = QVBoxLayout(_center_widget)
        _center_layout.setContentsMargins(4, 4, 4, 4)
        _center_layout.setSpacing(0)
        _center_layout.addWidget(self._command_queue.insertions_bar)
        _center_layout.addWidget(self._command_queue.insertions_content)
        _bottom_row_layout.addWidget(_center_widget, stretch=1)                    # center

        # Coluna MCP: radio Claude/Kimi/Codex + acoes Main MCP/Parallel/Dual.
        _mcp_column = self._build_mcp_column(self._mcp_column_btns)
        _mcp_column.setMinimumWidth(int(_mcp_column.sizeHint().width() * 1.25))
        _bottom_row_layout.addWidget(_mcp_column)                                  # mcp

        # Dobra os seletores de LLM MCP + brainstorm dentro do
        # queue-div-llm-routing (linha 1). _build_mcp_column ja construiu ambos
        # os radios (output-mcp-provider-radio-input e type-selector-radio-input)
        # sem os anexar aos layouts de origem; aqui eles sao reparenteados para
        # o box horizontal, com labels 'MCP' e 'brainstorm'. Funcionalidade
        # preservada: os QButtonGroup e signals seguem intactos.
        _provider_row = getattr(self, "_mcp_provider_radio_input", None)
        if _provider_row is not None:
            self._command_queue.append_llm_routing_section("MCP", _provider_row)
        _brainstorm_row = getattr(self, "_brainstorm_type_selector_row", None)
        if _brainstorm_row is not None:
            self._command_queue.append_llm_routing_section(
                "brainstorm", _brainstorm_row
            )

        _toolbar_row_layout.addWidget(_bottom_row)
        output_layout.addWidget(_toolbar_row)

        # Ordem final de main-command-queue (refactor 2026-05-18):
        # idx 0: _pill_row (metrics-project-pill) — primeiro item
        # idx 1: _toolbar_bar (dual-status-section: progress-section + listeners-frame)
        # idx 2: _window_label
        # idx 3: _toolbar_left_top (output-toolbar-llm-options)
        # _pill_row (idx 0) e _window_label (idx 2) foram inseridos em _setup_ui;
        # dual-status-section entra em idx 1 (entre pill e label) expandindo
        # horizontalmente para preencher a largura do queue.
        self._command_queue.layout().insertWidget(1, _toolbar_bar)
        self._command_queue.layout().insertWidget(3, _toolbar_left_top)

        # Dual terminal: splitter with interactive (top/left) + workspace (bottom/right)
        self._terminal_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._terminal_splitter.setHandleWidth(4)
        self._terminal_splitter.setChildrenCollapsible(False)
        self._terminal_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        from PySide6.QtWidgets import QLabel

        # Top/Left: Interactive terminal (user types here)
        self._interactive_wrapper = QWidget()
        interactive_layout = QVBoxLayout(self._interactive_wrapper)
        interactive_layout.setContentsMargins(0, 0, 0, 0)
        interactive_layout.setSpacing(0)
        interactive_label = QLabel(" INTERACTIVE")
        interactive_label.setFixedHeight(20)
        interactive_label.setStyleSheet(
            "QLabel { background-color: #1A2E05; color: #84CC16;"
            "  font-size: 10px; font-weight: 700; padding-left: 6px; }"
        )
        interactive_layout.addWidget(interactive_label)
        self._output_panel = OutputPanel(parent=self._interactive_wrapper)
        self._output_panel.setProperty("testid", "terminal-interactive")
        interactive_layout.addWidget(self._output_panel, stretch=1)
        interactive_layout.addWidget(
            self._build_terminal_notes_footer("terminal-interactive-notes")
        )
        self._terminal_splitter.addWidget(self._interactive_wrapper)

        # Bottom/Right: Workspace terminal (Kimi / paste target for blue ▶)
        self._workspace_wrapper = QWidget()
        workspace_layout = QVBoxLayout(self._workspace_wrapper)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_workspace_label_bar())
        # Inner splitter perpendicular ao outer (_terminal_splitter). Default
        # outer = Horizontal (T1 left, T2 right) -> inner = Vertical (T2 pyte
        # acima do T3 pyte quando expandido). _apply_workspace_inner_orientation
        # mantem a invariante ao alternar layout.
        self._workspace_terminal_splitter = QSplitter(Qt.Vertical, parent=self._workspace_wrapper)
        self._workspace_terminal_splitter.setProperty("testid", "terminal-workspace-splitter")

        # Child 0 = pyte (T2/Kimi, colapsavel). Child 1 = pyte (T3/Codex).
        # 2026-06-01: os tres terminais (T1/T2/T3) usam o mesmo engine pyte
        # (OutputPanel). T3 difere apenas no canal logico "workspace_xterm"
        # (channel_override) que preserva dot/notify/recovery do listener Codex.
        self._workspace_panel = OutputPanel(parent=self._workspace_terminal_splitter, workspace_mode=True)
        self._workspace_panel.setProperty("testid", "terminal-workspace")
        self._workspace_panel.setProperty("data-engine", "pyte")
        self._workspace_terminal_splitter.addWidget(self._workspace_panel)

        # T3 = terminal Codex, agora pyte (antes XtermOutputPanel/QWebEngine).
        # Fix T020 (BLOCKER 2): testid canonico `terminal-codex-output` e
        # contrato — `_codex_terminal_available()` e MCPPromptButton dependem
        # dele para detectar o T3 e habilitar os botoes Codex. Mantido byte-a-byte.
        self._workspace_panel_xterm = OutputPanel(
            parent=self._workspace_terminal_splitter,
            workspace_mode=True,
            channel_override="workspace_xterm",
        )
        self._workspace_panel_xterm.setProperty("testid", "terminal-codex-output")
        self._workspace_panel_xterm.setProperty("data-engine", "pyte")
        self._workspace_terminal_splitter.addWidget(self._workspace_panel_xterm)
        # Estado inicial fixo: T3 colapsado, T2 ocupa 100% (sem memoria entre
        # sessoes). child 0 = T2, child 1 = T3.
        self._t3_visible = False
        self._workspace_terminal_splitter.setSizes([1, 0])
        self._update_t3_arrow_icon()

        workspace_layout.addWidget(self._workspace_terminal_splitter, stretch=1)
        workspace_layout.addWidget(
            self._build_terminal_notes_footer("terminal-workspace-notes")
        )
        self._terminal_splitter.addWidget(self._workspace_wrapper)

        self._terminal_splitter.setSizes([350, 350])
        output_layout.addWidget(self._terminal_splitter, stretch=1)

        self._splitter.addWidget(self._command_queue)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.addWidget(output_container)
        self._splitter.setStretchFactor(1, 2)

        self._view_stack.addWidget(self._splitter)  # index 0

        # ── Page 1: Comandos (TemplateBuilderWidget, full width) ──────── #
        self._template_builder = TemplateBuilderWidget(parent=self)
        self._template_builder.setProperty("testid", "page-comandos")
        self._view_stack.addWidget(self._template_builder)  # index 1

        # ── Cooperative lock service (T-037) ─────────────────────────── #
        # Instantiated BEFORE the per-module detail view so it can be
        # injected as a constructor arg. API-only for now: no acquire on
        # startup. T-038 drives try_acquire/release from the detail view.
        self._lock_service = LockService(parent=self)
        self._lock_service.lock_lost.connect(self._on_lock_lost)

        # Shared DeliveryReader used by both Kanban and ModuleDetailView.
        self._kanban_reader = DeliveryReader()

        # ── Page 2: Kanban (9 colunas por estado DCP, T-036) ──────────── #
        self._kanban_view = KanbanView(reader=self._kanban_reader, parent=self)
        self._kanban_view.setProperty("testid", "page-kanban")
        self._kanban_view.module_clicked.connect(self._on_kanban_module_clicked)
        self._view_stack.addWidget(self._kanban_view)  # index 2

        # ── Page 3: Module Detail (per-modulo view, T-038) ───────────── #
        self._module_detail_view = ModuleDetailView(
            reader=self._kanban_reader,
            lock_service=self._lock_service,
            parent=self,
        )
        self._module_detail_view.setProperty("testid", "page-module-detail")
        self._module_detail_view.back_requested.connect(
            lambda: self._view_stack.setCurrentIndex(2)
        )
        self._view_stack.addWidget(self._module_detail_view)  # index 3

        root_layout.addWidget(self._view_stack, stretch=1)

        # Toast notification (floating, stacked, level-dependent duration)
        self._toast_notifier = ToastNotifier(central)

        # ModalTest floating button — shown when a QDialog is open
        self._modal_test_btn = QPushButton("ModalTest", central)
        self._modal_test_btn.setProperty("testid", "modal-test-btn")
        self._modal_test_btn.setCheckable(True)
        self._modal_test_btn.setVisible(False)
        self._modal_test_btn.setFixedSize(80, 28)
        self._modal_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._modal_test_btn.setStyleSheet(
            "QPushButton { background-color: #7C3AED; color: #FAFAFA;"
            "  border: 1px solid #6D28D9; border-radius: 6px;"
            "  font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background-color: #6D28D9; }"
            "QPushButton:checked { background-color: #5B21B6; border-color: #5B21B6; }"
        )
        self._modal_test_btn.toggled.connect(self._on_modal_test_toggled)
        self._modal_test_overlays: list = []
        self._active_modal_dialog = None
        self._modal_check_timer = QTimer(self)
        self._modal_check_timer.setInterval(200)
        self._modal_check_timer.timeout.connect(self._check_for_active_modal)
        self._modal_check_timer.start()

    def _build_output_toolbar(self) -> tuple[QWidget, QWidget]:
        """Toolbar acima do dual-terminal splitter, agora reduzido a 2 widgets.

        Refactor 2026-05-15 output-toolbar-left consolidation:
        - output-toolbar-center (right_container) DELETADA inteira.
        - toolbar-prompts-row, output-toolbar-actions-row, output-toolbar-controls-row DELETADAS.
        - Brief/Docs descartados (apenas JSON e WS sobrevivem em actions-tab).
        - Os botoes vivos (4 prompt slots + JSON/WS/mcp-codex/mcp-kimi/double-mcp/asq-user)
          migraram para as tabs Prompts/Actions do CommandQueueHeader via
          populate_prompts_tab() / populate_actions_tab().
        - terminal-route-toggles e toolbar-prompts-config-gear viraram extras
          do tab_bar (attach_tab_bar_extras), posicionados como abas extras.

        Refactor 2026-05-17 power-bi-section:
        - Renomeado `output-toolbar-col1-top` -> `power-bi-section`.
        - queue-progress-ring saiu de DENTRO do listeners-frame e virou IRMAO.
        - bar usa DualStatusSection: progress-section (ring+count) a esquerda e
          listeners-frame a direita em row-mode; empilhados em column-mode.

        Retorna apenas:
        - `bar` (dual-status-section): hospeda progress-section + listeners-frame.
        - `left_top` (output-toolbar-llm-options): hospeda instance-group abaixo.
        """
        from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout

        # Estiliza count_label para exibicao em progress-section (fonte grande,
        # centralizado, mesmo espaco que o ring — ambos com stretch=1).
        _count_lbl = self._metrics_bar._lbl_queue_count
        _count_lbl.setStyleSheet(
            "background: transparent; border: none; color: #FBBF24;"
            " font-size: 22px; font-weight: 700; font-family: monospace;"
        )
        _count_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Coluna direita do progress-section: contador de fila + memória RSS.
        _mem_lbl = self._metrics_bar._lbl_memory
        _mem_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _count_col = QWidget()
        _count_col.setObjectName("QueueCountColumn")
        _count_col.setProperty("testid", "queue-count-column")
        _count_col_layout = QVBoxLayout(_count_col)
        _count_col_layout.setContentsMargins(0, 0, 0, 0)
        _count_col_layout.setSpacing(2)
        _count_col_layout.addStretch(1)
        _count_col_layout.addWidget(_count_lbl)
        _count_col_layout.addWidget(_mem_lbl)
        _count_col_layout.addStretch(1)

        _progress_section = ProgressSection(
            ring=self._metrics_bar._queue_progress_ring,
            count_label=_count_col,
        )
        bar = DualStatusSection(
            progress_section=_progress_section,
            listeners_frame=self._metrics_bar._listeners_frame,
        )

        # left_top: reparenteia instance-group para a coluna esquerda.
        # Posicionado pelo _setup_ui acima de output-toolbar-left.
        left_top = QWidget()
        left_top.setObjectName("OutputToolbarLeftTop")
        left_top.setProperty("testid", "output-toolbar-llm-options")
        left_top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left_top.setStyleSheet(
            "QWidget#OutputToolbarLeftTop { border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        left_top_layout = QVBoxLayout(left_top)
        left_top_layout.setContentsMargins(6, 6, 6, 6)
        left_top_layout.setSpacing(0)
        left_top_layout.addWidget(self._metrics_bar._instance_group)

        # terminal-route-toggles: roteamento T1/T2. Antes em controls_row;
        # agora vira "aba extra" do tab_bar via attach_tab_bar_extras().
        # Estilo espelha queue-div-use-kimi (background, border, radius, indicator).
        _TERMINAL_ROUTE_CHK_STYLE = (
            "QCheckBox { color: #FAFAFA; font-size: 11px; font-weight: 600;"
            "  background: transparent; border: none; padding: 0; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #3B82F6;"
            "  border: 1px solid #3B82F6; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #93C5FD; }"
        )
        self._chk_route_t1 = QCheckBox("T1")
        self._chk_route_t1.setProperty("testid", "terminal-route-t1")
        self._chk_route_t1.setChecked(True)
        self._chk_route_t1.setToolTip(
            "T1: publicar em terminal-interactive (pyte).\n"
            "Combinacoes T1/T2/T3 publicam em todos os marcados.\n"
            "Nenhum = no-op silencioso."
        )
        self._chk_route_t1.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        self._chk_route_t2 = QCheckBox("T2")
        self._chk_route_t2.setProperty("testid", "terminal-route-t2")
        self._chk_route_t2.setChecked(False)
        self._chk_route_t2.setToolTip(
            "T2: publicar em terminal-workspace pyte (colapsavel via arrow).\n"
            "Combinacoes T1/T2/T3 publicam em todos os marcados.\n"
            "Nenhum = no-op silencioso."
        )
        self._chk_route_t2.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        # T3 = terminal Codex (pyte). Por default desligado — o operador
        # expande o T3 pelo arrow no label bar do terminal-workspace-splitter
        # e ativa o route quando quiser scriptar diretamente naquele painel.
        self._chk_route_t3 = QCheckBox("T3")
        self._chk_route_t3.setProperty("testid", "terminal-route-t3")
        self._chk_route_t3.setChecked(False)
        self._chk_route_t3.setEnabled(True)
        self._chk_route_t3.setToolTip(
            "T3: publicar em terminal-codex-output (pyte, Codex).\n"
            "Combinacoes T1/T2/T3 publicam em todos os marcados.\n"
            "Nenhum = no-op silencioso."
        )
        self._chk_route_t3.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        _terminal_route_box = QWidget()
        _terminal_route_box.setProperty("testid", "terminal-route-toggles")
        _terminal_route_box.setFixedHeight(32)
        _terminal_route_box.setStyleSheet(
            "QWidget { background-color: #1C1C1F; border: 1px solid #3F3F46;"
            "  border-radius: 5px; }"
        )
        # Refactor 2026-05-24: T1/T2/T3 + Notes T1/T2 numa unica row horizontal
        # (antes em duas linhas empilhadas).
        _trbl = QHBoxLayout(_terminal_route_box)
        _trbl.setContentsMargins(10, 2, 10, 2)
        _trbl.setSpacing(8)
        _trbl.addWidget(self._chk_route_t1)
        _trbl.addWidget(self._chk_route_t2)
        _trbl.addWidget(self._chk_route_t3)

        # Linha 2: Notes T1/T2 — quando marcados, texto de prompt vai para o
        # campo de notas (staging area abaixo) em vez do terminal, para edicao
        # qualificada antes do envio.
        self._chk_notes_t1 = QCheckBox("T1")
        self._chk_notes_t1.setProperty("testid", "terminal-notes-t1")
        self._chk_notes_t1.setChecked(False)
        self._chk_notes_t1.setToolTip(
            "Notes T1: envia texto para campo de notas T1 (abaixo) em vez do\n"
            "terminal interativo. Edite e use ↑ para enviar ao terminal quando pronto."
        )
        self._chk_notes_t1.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        self._chk_notes_t2 = QCheckBox("T2")
        self._chk_notes_t2.setProperty("testid", "terminal-notes-t2")
        self._chk_notes_t2.setChecked(False)
        self._chk_notes_t2.setToolTip(
            "Notes T2: envia texto para campo de notas T2 (abaixo) em vez do\n"
            "terminal workspace. Edite e use ↑ para enviar ao terminal quando pronto."
        )
        self._chk_notes_t2.setStyleSheet(_TERMINAL_ROUTE_CHK_STYLE)

        _notes_prefix_lbl = QLabel("Notes:")
        _notes_prefix_lbl.setStyleSheet(
            "color: #71717A; font-size: 10px; font-weight: 600; background: transparent;"
            "border: none;"
        )
        _trbl.addWidget(_notes_prefix_lbl)
        _trbl.addWidget(self._chk_notes_t1)
        _trbl.addWidget(self._chk_notes_t2)
        _trbl.addStretch()

        # Inputs de notas removidos da UI — Notes T1/T2 sao apenas checkboxes de
        # roteamento. Quando marcados, _publish_to_terminal copia o texto para o
        # clipboard em vez de publicar diretamente no terminal correspondente.

        _MCP_TEST_PROMPT = (
            "/mcp:codex ping test — verificar se MCP Codex esta ativo. "
            "Apenas responda: \"MCP Codex OK — modelo gpt-5.5, pronto.\" Nada mais.\n"
            "/mcp:kimi ping test — verificar se MCP Kimi esta ativo. "
            "Apenas responda: \"MCP Kimi OK — modelo kimi-code/kimi-for-coding, pronto.\" Nada mais."
        )
        def _prompt_btn(label: str, testid: str, bg: str, hover: str, tooltip: str) -> QPushButton:
            b = QPushButton(label)
            b.setProperty("testid", testid)
            b.setFixedHeight(32)
            b.setMinimumWidth(70)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tooltip)
            b.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {hover}; }}"
            )
            return b

        # Refactor 2026-05-18: substituir _prompt_buttons (modelo prompt inline)
        # por _prompt_entries (modelo label+path; prompt vive em arquivo .md).
        # Paleta de 8 cores para alocacao por roulette.
        _PROMPT_PALETTE = [
            ("#0D9488", "#0F766E"),
            ("#EA580C", "#C2410C"),
            ("#7C3AED", "#6D28D9"),
            ("#0891B2", "#0E7490"),
            ("#10B981", "#059669"),
            ("#F59E0B", "#D97706"),
            ("#EF4444", "#DC2626"),
            ("#8B5CF6", "#7C3AED"),
        ]

        def _slug_label(lbl: str) -> str:
            import re as _re
            return _re.sub(r"[^a-z0-9]+", "-", lbl.lower()).strip("-") or "prompt"

        # Entradas padrão. Usadas se QSettings nao tiver entries.
        _DEFAULT_ENTRIES = [
            {"label": "MCP-test",        "path": "ai-forge/custom-prompts/prompts-subtab/mcp-test.md",
             "description": "Pinga MCP Codex e Kimi para verificar conexão"},
            {"label": "Online Review",   "path": "ai-forge/custom-prompts/prompts-subtab/online-review.md",
             "description": "Auditoria completa do remoto e produção do projeto ativo"},
            {"label": "Next Module",     "path": "ai-forge/custom-prompts/prompts-subtab/next-module.md",
             "description": "Lê regras DCP antes de implantar o próximo módulo"},
            {"label": "Workflow Rules",  "path": "ai-forge/custom-prompts/prompts-subtab/workflow-rules.md",
             "description": "Ensina /clear, /model e /effort no SPECIFIC-FLOW.json"},
            {"label": "Progress",        "path": "ai-forge/custom-prompts/prompts-subtab/progress.md",
             "description": "Loop adversarial: planejamento, execução e revisão via Codex"},
            {"label": "Pending Sweep",   "path": "ai-forge/custom-prompts/prompts-subtab/pending-actions-sweep.md",
             "description": "Varre e resolve pendências do projeto ativo"},
            {"label": "Memory Refresh",  "path": "ai-forge/custom-prompts/prompts-subtab/memory-decay-refresh.md",
             "description": "Manutenção de memória: poda de stale, duplicatas e riscos"},
            {"label": "Zero Audit",      "path": "ai-forge/custom-prompts/prompts-subtab/zero-rules-module-audit.md",
             "description": "Audita módulo ativo contra regras Zero (Orfãos/Silêncio/etc)"},
            {"label": "DCP Triage",      "path": "ai-forge/custom-prompts/prompts-subtab/dcp-coherence-triage.md",
             "description": "Triagem DCP: congruence-check, temporality e meta-completeness"},
            {"label": "Codex Hardening", "path": "ai-forge/custom-prompts/prompts-subtab/codex-hardening.md",
             "description": "Review adversarial via Codex + aplica hardenings nao-destrutivos"},
            {"label": "PDCA",            "path": "ai-forge/custom-prompts/prompts-subtab/pdca-task-recovery.md",
             "description": "Pega o problema do contexto e gira P-D-C-A ate a solucao; sucesso emite o listener verde, falha reabre o ciclo"},
            {"label": "Study Tasks",     "path": "ai-forge/custom-prompts/prompts-subtab/study-tasklist-codex.md",
             "description": "Converte estudo simples em tasklist revisada"},
            {"label": "turn-green",      "path": "ai-forge/custom-prompts/prompts-subtab/turn-green.md",
             "description": "Força o listener deste terminal a ficar verde (idle)"},
            {"label": "Plan vs Loop",    "path": "ai-forge/custom-prompts/prompts-subtab/plan-vs-loop-coverage.md",
             "description": "Compara planejado vs implantado no loop e delega gaps"},
            {"label": "create-agent",    "path": "ai-forge/custom-prompts/prompts-subtab/create-agent.md",
             "description": "Cria persona MCP com pesquisa web, deduplicacao, validacao e botao na sub-aba Agentes"},
        ]

        _pset = QSettings("systemForge", "workflow-app")

        # Migração one-shot: se entries nao existir mas legacy slot_0/label existir,
        # popular entries a partir dos slots antigos (nao deletar chaves legacy).
        _raw_entries = _pset.value("prompts_row/entries")
        if _raw_entries is None:
            _legacy_has_data = any(
                _pset.value(f"prompts_row/slot_{i}/label") for i in range(5)
            )
            if _legacy_has_data:
                _migrated = []
                for _i, _dflt in enumerate(_DEFAULT_ENTRIES):
                    _lbl = _pset.value(f"prompts_row/slot_{_i}/label") or _dflt["label"]
                    _migrated.append({"label": _lbl, "path": _dflt["path"]})
                import json as _json
                _pset.setValue("prompts_row/entries", _json.dumps(_migrated))
                _raw_entries = _json.dumps(_migrated)

        if _raw_entries is not None:
            try:
                import json as _json
                _loaded = _json.loads(_raw_entries)
                if isinstance(_loaded, list):
                    _entries_data = _loaded
                else:
                    _entries_data = _DEFAULT_ENTRIES
            except Exception:
                _entries_data = _DEFAULT_ENTRIES
        else:
            _entries_data = _DEFAULT_ENTRIES

        self._prompt_entries: list[dict] = []
        for _i, _e in enumerate(_entries_data):
            _lbl = _e.get("label", f"Prompt {_i+1}")
            _bg, _hv = _PROMPT_PALETTE[_i % len(_PROMPT_PALETTE)]
            self._prompt_entries.append({
                "label": _lbl,
                "path": _e.get("path", ""),
                "description": _e.get("description", ""),
                "testid": f"output-btn-prompt-{_slug_label(_lbl)}",
                "bg": _bg,
                "hover": _hv,
            })

        # Reconciliacao de boot (2026-06-24): o QFileSystemWatcher so detecta
        # .md novos enquanto o app esta aberto (directoryChanged). Um .md criado
        # com o app fechado — ou shadow de `prompts_row/entries` persistido que
        # nao inclui uma entry default nova — nunca renderizava botao no startup.
        # Aqui varremos o diretorio e anexamos qualquer .md ausente das entries,
        # espelhando _on_prompts_dir_changed mas em init. Persistimos de volta
        # para que o conjunto reconciliado vire o novo baseline.
        import os as _os_rc
        # Resolver cwd-INDEPENDENTE (mesmo de personas/brainstorm via
        # _systemforge_root). O app NAO faz chdir e roda com cwd =
        # ai-forge/workflow-app (Makefile `uv run python -m workflow_app.main`),
        # entao getcwd() NAO e a raiz do repo. Usar getcwd() fazia esta
        # reconciliacao (e o watcher abaixo) observarem um path inexistente
        # (ai-forge/workflow-app/ai-forge/custom-prompts/...) e os botoes de
        # prompt NUNCA apareciam. _systemforge_root() = parents[4] deste modulo.
        _prompts_dir_abs = str(
            self._systemforge_root() / "ai-forge/custom-prompts/prompts-subtab"
        )
        if _os_rc.path.isdir(_prompts_dir_abs):
            _known_paths = {e.get("path", "") for e in self._prompt_entries}
            _appended = False
            for _fname in sorted(_os_rc.listdir(_prompts_dir_abs)):
                if not _fname.endswith(".md") or _fname == "README.md":
                    continue
                _rel = f"ai-forge/custom-prompts/prompts-subtab/{_fname}"
                if _rel in _known_paths:
                    continue
                _fallback_lbl = _fname.replace("-", " ").replace(".md", "").title()
                _lbl = self._prompt_label_for_discovered_file(
                    Path(_prompts_dir_abs) / _fname, _fallback_lbl
                )
                _idx = len(self._prompt_entries)
                _bg, _hv = _PROMPT_PALETTE[_idx % len(_PROMPT_PALETTE)]
                self._prompt_entries.append({
                    "label": _lbl,
                    "path": _rel,
                    "description": "",
                    "testid": f"output-btn-prompt-{_slug_label(_lbl)}",
                    "bg": _bg,
                    "hover": _hv,
                })
                _appended = True
            if _appended:
                import json as _json_rc
                _pset.setValue(
                    "prompts_row/entries",
                    _json_rc.dumps([
                        {"label": e["label"], "path": e["path"],
                         "description": e.get("description", "")}
                        for e in self._prompt_entries
                    ]),
                )

        # Prompt base (persistido em QSettings; editavel no modal)
        _DEFAULT_BASE_PROMPT = (
            "Leia o conteudo completo do arquivo indicado abaixo e execute "
            "exatamente o que ele orienta. Trate o arquivo como a especificacao "
            "integral da tarefa: nao resuma, nao parafraseie, nao adicione perguntas "
            "se o arquivo ja for auto-suficiente. Caminho:"
        )
        _saved_base = _pset.value("prompts_row/base_prompt")
        self._prompt_base: str = _saved_base if isinstance(_saved_base, str) else _DEFAULT_BASE_PROMPT

        gear_btn = QPushButton("")
        gear_btn.setProperty("testid", "toolbar-prompts-config-gear")
        gear_btn.setFixedSize(32, 32)
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gear_btn.setToolTip("Configurar prompts da sub-aba (label, path, prompt base)")
        gear_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46;"
            "  border: 1px solid #52525B; border-radius: 5px; padding: 0; }"
            "QPushButton:hover { background-color: #52525B; border-color: #71717A; }"
            "QPushButton:pressed { background-color: #FBBF24; }"
            "QPushButton:pressed QLabel { color: #18181B; }"
        )
        _gear_lbl = QLabel("⚙", gear_btn)
        _gear_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        _gear_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _gear_lbl.setStyleSheet("color: #FAFAFA; font-size: 16px; background: transparent; border: none;")
        _gear_layout = QHBoxLayout(gear_btn)
        _gear_layout.setContentsMargins(0, 0, 0, 0)
        _gear_layout.setSpacing(0)
        _gear_layout.addWidget(_gear_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        gear_btn.clicked.connect(self._open_prompts_config_dialog)
        # 2026-06-22: o gear de prompts deixa de ser cornerWidget compartilhado
        # (aparecia em TODAS as sub-abas e confundia) e passa a viver DENTRO da
        # sub-aba PROMPTS — so renderiza com ela aberta. Ref guardado para os
        # rebuilds da sub-aba (_open_prompts_config_dialog, _on_prompts_dir_changed).
        self._prompts_config_gear = gear_btn

        # Watcher para auto-detectar novos .md criados em prompts-subtab
        import os as _os_w

        from PySide6.QtCore import QFileSystemWatcher as _FSWatcher
        # Resolver cwd-INDEPENDENTE (ver reconciliacao de boot acima): o app
        # roda com cwd != raiz do repo, entao getcwd() observava um path
        # inexistente e o watcher nunca disparava em .md novos.
        _watcher_abs = str(
            self._systemforge_root() / "ai-forge/custom-prompts/prompts-subtab"
        )
        self._prompts_file_watcher = _FSWatcher(
            [_watcher_abs] if _os_w.path.isdir(_watcher_abs) else [], self
        )
        self._prompts_file_watcher.directoryChanged.connect(self._on_prompts_dir_changed)

        _TOGGLE_BTN_STYLE = (
            "QPushButton { background-color: #27272A; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 15px; padding: 0; text-align: center; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA;"
            "  border-color: #71717A; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )

        # Task 5 (loop 05-13-workflow-app-layout-2): toggles movidos de
        # controls_row (output-toolbar-center) para queue_count_toggles_row
        # (output-toolbar-col1-top, abaixo de queue-count-label). Largura
        # reduzida 44->42 para que 42 + 4 (spacing) + 42 = 88 = largura
        # de queue-count-label. O espaco vacado em controls_row sera
        # consumido pela Task 6 (checkbox T1/T2).
        from PySide6.QtCore import QSize as _QSize
        self._layout_icon_stacked = QIcon(
            str(Path(_WORKFLOW_APP_DIR) / "assets" / "layout-stacked.svg")
        )
        self._layout_icon_side = QIcon(
            str(Path(_WORKFLOW_APP_DIR) / "assets" / "layout-side-by-side.svg")
        )
        self._layout_toggle_btn = QPushButton()
        self._layout_toggle_btn.setProperty("testid", "terminal-layout-toggle")
        self._layout_toggle_btn.setToolTip("Layout: lado a lado. Clique para empilhar")
        self._layout_toggle_btn.setFixedSize(56, 32)
        self._layout_toggle_btn.setIconSize(_QSize(20, 20))
        # Estado inicial: lado a lado -> clique vai empilhar -> mostra icone "stacked".
        self._layout_toggle_btn.setIcon(self._layout_icon_stacked)
        self._layout_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout_toggle_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        self._layout_toggle_btn.clicked.connect(self._toggle_terminal_layout)
        self._metrics_bar._queue_count_toggles_layout.addWidget(
            self._layout_toggle_btn
        )

        self._collapse_chevron = QPushButton("\u25BA")
        self._collapse_chevron.setProperty("testid", "terminal-workspace-collapse")
        self._collapse_chevron.setToolTip("Colapsar terminal Workspace")
        self._collapse_chevron.setFixedSize(56, 32)
        self._collapse_chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_chevron.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #FFFFFF;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 15px; padding: 0; text-align: center; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FFFFFF;"
            "  border-color: #71717A; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )
        self._collapse_chevron.clicked.connect(self._toggle_workspace_collapse)
        self._metrics_bar._queue_count_toggles_layout.addWidget(
            self._collapse_chevron
        )

        # 2026-05-19: engine-toggle ("1-pyte") removido. T3 (terminal Codex
        # colapsavel) e controlado pelo arrow em terminal-workspace-splitter
        # label bar; T2 (Kimi) permanece sempre visivel. 2026-06-01: T3 passou
        # de xterm para pyte (todos os terminais usam OutputPanel).
        # Task 3 (loop 05-13-workflow-app-layout-2): _btn_datatest movido para a nova
        # coluna `output-toolbar-test-mode` (4o sibling de _toolbar_row).

        # Refactor 2026-05-15 output-toolbar-left consolidation:
        # output-toolbar-center deletada. Os botoes vivos sao roteados para
        # as novas tabs Prompts/Actions do CommandQueueHeader.
        # Refactor 2026-05-18: particionar botões nas 4 sub-abas semânticas.
        action_widgets = self._populate_header_actions()
        workflow_app_widgets = self._populate_header_workflow_app()
        paths_extras = self._populate_header_paths_extras()

        # paths & IDs: JSON, WS, Loop, Brainstorm, Workflow App + 6 campos basic_flow
        _paths_btns = [
            action_widgets[0],
            action_widgets[1],
            action_widgets[2],
            action_widgets[3],
            workflow_app_widgets[0],
        ] + paths_extras
        # MCP column (output-toolbar-mcp): os 9 botoes legados continuam sendo
        # criados para preservar o contrato de action_widgets, mas a aba MCPs
        # renderiza radio Claude/Kimi/Codex + 3 acoes.
        self._mcp_column_btns = action_widgets[4:13]
        # rules: dcp+meta-feeding+cmd+terminal+listeners+cascade-bug+indicators+prompt+add-rules
        _rules_btns = workflow_app_widgets[1:]
        # prompts: entries .md + gear de configuracao (ultimo widget do flow).
        # 2026-06-22: asq-user migrou daqui para a sub-aba CMD (ver _cmd_btns).
        self._asq_user_btn = action_widgets[13]
        _prompts_btns = (
            self._populate_header_prompts_subtab()
            + [self._prompts_config_gear]
        )

        # Linha de baixo da sub-aba paths & IDs: botao 'repo rules'.
        _paths_row2_btns = [self._build_repo_rules_button()]

        # Padding das sub-abas ja definido em 4px 8px nas funcoes de criacao.

        # cmd: comandos avulsos (slash-commands pontuais fora de pipeline).
        # asq-user (output-btn-asq-user) vive aqui desde 2026-06-22 (migrado de PROMPTS).
        _cmd_btns = [self._asq_user_btn] + self._populate_header_cmd_subtab()

        # auto-improove: melhoria continua de assets SystemForge.
        _auto_improove_btns = self._populate_header_auto_improove_subtab()

        # personal: comandos pessoais (curriculum, imbound, mkt).
        _personal_btns = self._populate_header_personal_subtab()

        # personas: arquivos .md de ai-forge/MCP/agents/.
        _personas_btns = self._populate_header_personas_subtab()

        self._command_queue.populate_paths_subtab(_paths_btns, _paths_row2_btns)
        self._command_queue.populate_prompts_subtab(_prompts_btns)
        self._command_queue.populate_rules_subtab(_rules_btns)
        self._command_queue.populate_cmd_subtab(_cmd_btns)
        self._command_queue.populate_auto_improove_subtab(_auto_improove_btns)
        self._command_queue.populate_personal_subtab(_personal_btns)
        self._command_queue.populate_personas_subtab(_personas_btns)
        self._command_queue.attach_tab_bar_extras(_terminal_route_box)
        # Refactor 2026-06-22: o gear de prompts NAO e mais cornerWidget (vivia
        # no canto compartilhado de todas as sub-abas). Agora entra como ultimo
        # widget do flow da sub-aba PROMPTS (ver _prompts_btns acima), so visivel
        # com ela aberta.

        # queue-count-label vive em progress-section (refactor 2026-05-18).
        # attach_count_label nao e mais chamado — o label ja esta em ProgressSection.
        # P4: rastreia clicks em pipelines/workflow/auxiliar para atualizar
        # queue-template-label com o testid do ultimo botao clicado.
        self._command_queue.install_template_tracker()

        return bar, left_top

    # Aba `brainstorm`: grade seed-driven (T2 loop
    # 05-21-implantation-tasklist-aba-brainstorm). Botoes MCPPromptButton
    # carregados de blacksmith/brainstorm-mcp/NN-*.md.
    # Constantes legacy (hardcoded col styles, row labels, agents map,
    # agents prompt dir, slot por cor) removidas em T2.

    _BRAINSTORM_SEEDS_RELDIR = "blacksmith/brainstorm-mcp"
    _BRAINSTORM_SEED_COUNT = 24
    _BRAINSTORM_GRID_COLUMNS = 4

    @staticmethod
    def _systemforge_root() -> Path:
        """Raiz do repositorio SystemForge — cwd canonico do terminal.

        Este modulo vive sempre em
        `ai-forge/workflow-app/src/workflow_app/main_window.py`, logo
        `parents[4]` aponta deterministicamente para a raiz do repo.
        """
        return Path(__file__).resolve().parents[4]

    def _brainstorm_seeds_dir(self) -> Path:
        """Diretorio absoluto dos seeds da grade brainstorm."""
        return self._systemforge_root() / self._BRAINSTORM_SEEDS_RELDIR

    def _load_brainstorm_seeds(self) -> list[dict]:
        """Carrega e valida os seeds da grade brainstorm.

        Glob `blacksmith/brainstorm-mcp/NN-*.md`, parse yaml frontmatter,
        valida schema fechado + resolvability de agent_path (gate G6),
        retorna lista ordenada por nome de arquivo.

        Raise `_BrainstormSeedError` em qualquer falha (fail-fast all-or-nothing).
        Caller (`_build_brainstorm_page`) e responsavel pelo toast.
        """
        root = self._systemforge_root().resolve()
        seeds_dir = self._brainstorm_seeds_dir()
        if not seeds_dir.is_dir():
            raise _BrainstormSeedError(
                f"diretorio inexistente: {self._BRAINSTORM_SEEDS_RELDIR}"
            )

        # Hardening 2026-05-24: o diretorio brainstorm-mcp/ tambem hospeda os
        # OUTPUTS da acao "Criar arquivo" (ex: 05-24-foot-stock-....md). O
        # prefixo de data MM- colide com o glob NN-*.md e inflava len(paths)
        # acima do esperado -> a politica fail-fast all-or-nothing fazia a grade INTEIRA
        # sumir (root cause das duas sumiços observadas em 2026-05-24). Defesa:
        # exigir slug ALFABETICO logo apos o prefixo NN- (^[0-9]{2}-[a-z]...), o que
        # exclui nomes com data (NN-NN-...) sem tocar nos seeds reais (todos
        # kebab-alpha: criar-md, search-in, controversial, ...).
        _seed_name_re = re.compile(r"^[0-9]{2}-[a-z][a-z0-9-]*\.md$")
        _all_numeric = sorted(seeds_dir.glob("[0-9][0-9]-*.md"))
        paths = [p for p in _all_numeric if _seed_name_re.match(p.name)]
        seed_count = getattr(
            self, "_BRAINSTORM_SEED_COUNT", MainWindow._BRAINSTORM_SEED_COUNT,
        )
        if len(paths) != seed_count:
            _ignored = [p.name for p in _all_numeric if p not in paths]
            _hint = (
                f"; ignorados por nao casarem NN-<slug-alpha>.md (provaveis "
                f"outputs de 'Criar arquivo'): {_ignored}"
                if _ignored
                else ""
            )
            raise _BrainstormSeedError(
                f"esperado exatamente {seed_count} seeds canonicos "
                f"(NN-<slug>.md), "
                f"encontrado {len(paths)}{_hint}"
            )
        expected_prefixes = [f"{i:02d}" for i in range(1, seed_count + 1)]
        actual_prefixes = [p.name[:2] for p in paths]
        if actual_prefixes != expected_prefixes:
            raise _BrainstormSeedError(
                f"esperado exatamente {seed_count} seeds canonicos "
                f"com prefixos {expected_prefixes}; encontrado {actual_prefixes}"
            )

        loaded: list[dict] = []
        for p in paths:
            try:
                if p.stat().st_size > _SEED_MAX_BYTES:
                    raise _BrainstormSeedError(
                        f"{p.name}: tamanho > {_SEED_MAX_BYTES} bytes"
                    )
                text = p.read_text(encoding="utf-8-sig")
                m = re.match(r"^\s*---\n(.*?)\n---\n?", text, re.S)
                raw = m.group(1) if m else text
                data = yaml.safe_load(raw) or {}
                if not isinstance(data, dict):
                    raise _BrainstormSeedError(
                        f"{p.name}: root yaml nao e mapping"
                    )
            except yaml.YAMLError as exc:
                raise _BrainstormSeedError(f"{p.name}: yaml malformado: {exc}") from exc
            except OSError as exc:
                raise _BrainstormSeedError(f"{p.name}: erro de leitura: {exc}") from exc

            missing = _SEED_REQUIRED_KEYS - data.keys()
            if missing:
                raise _BrainstormSeedError(
                    f"{p.name}: campos obrigatorios ausentes: {sorted(missing)}"
                )

            slug = str(data["slug"]).strip()
            button_type = str(data["button_type"]).strip()
            action = str(data["action"]).strip()
            agent_name = str(data["agent_name"]).strip()
            agent_path = str(data["agent_path"]).strip()

            # Compat layer target_path: bool (seed) -> target_path_edit_inplace
            #                          + target_terminal (string) -> terminal widget.
            target_path_raw = data["target_path"]
            target_path_edit_inplace = bool(target_path_raw) if isinstance(
                target_path_raw, bool
            ) else str(target_path_raw).strip().lower() in ("true", "1", "yes")

            target_terminal = data.get("target_terminal")
            if target_terminal == _SEED_TARGET_TERMINAL_RUNTIME_SENTINEL:
                # Resolvido em runtime pelo radio (T3). Default Claude->T1.
                target_terminal_resolved: str | None = None
            else:
                target_terminal_resolved = (
                    str(target_terminal).strip() if target_terminal else None
                )

            if button_type not in VALID_BUTTON_TYPES:
                raise _BrainstormSeedError(
                    f"{p.name}: button_type invalido: {button_type!r}"
                )
            if action not in VALID_ACTIONS:
                raise _BrainstormSeedError(
                    f"{p.name}: action invalida: {action!r}"
                )
            if (
                target_terminal_resolved is not None
                and target_terminal_resolved not in VALID_TERMINALS
            ):
                raise _BrainstormSeedError(
                    f"{p.name}: target_terminal invalido: {target_terminal_resolved!r}"
                )

            # G6: agent_path obrigatorio, sem TODO, resolvivel e dentro do repo.
            if "TODO" in agent_path or "TODO" in agent_name:
                raise _BrainstormSeedError(
                    f"{p.name}: G6 violado: TODO em agent_name/agent_path"
                )
            agent_abs = (root / agent_path).resolve()
            if not agent_abs.is_file():
                raise _BrainstormSeedError(
                    f"{p.name}: G6 violado: agent_path {agent_path} inexistente"
                )
            try:
                agent_abs.relative_to(root)
            except ValueError as exc:
                raise _BrainstormSeedError(
                    f"{p.name}: G6 violado: agent_path {agent_path} fora do repo"
                ) from exc

            # Label canonico. Precedencia: campo `label` explicito (editavel
            # pelo gear `brainstorm-mcp-config-dialog`) quando preenchido;
            # senao deriva do `title` removendo o prefixo "Seed - Botao N - "
            # (fix T021, regex que tolera espacos extras), conforme
            # mcp-flow-implantation-base-archive.md §4 (labels: "Criar md",
            # "search-in", "search-out", etc. - sem numero prefixo). O fallback
            # tambem limpa labels legados que guardaram o title inteiro.
            explicit_label = re.sub(
                r"^Seed\s*-\s*Botao\s*\d+\s*-\s*", "",
                str(data.get("label") or "").strip(),
            ).strip()
            if explicit_label:
                canonical_label = explicit_label
            else:
                raw_title = str(data.get("title") or slug).strip()
                canonical_label = re.sub(
                    r"^Seed\s*-\s*Botao\s*\d+\s*-\s*", "", raw_title
                ).strip() or slug

            loaded.append({
                "slug": slug,
                "label": canonical_label,
                "button_type": button_type,
                "action": action,
                "agent_name": agent_name,
                "agent_path": agent_path,
                "target_terminal": target_terminal_resolved,
                "target_path_edit_inplace": target_path_edit_inplace,
                "seed_path": p,
            })

        # Garantia final: slugs unicos.
        slugs = [s["slug"] for s in loaded]
        if len(set(slugs)) != seed_count:
            raise _BrainstormSeedError(
                f"slugs nao unicos: {slugs}"
            )
        return loaded

    def _rel_to_root(self, abs_path: str) -> str:
        """Converte um path absoluto para relativo a raiz do SystemForge.

        Arquivo fora do repo: devolve o path absoluto inalterado — o terminal
        na raiz ainda resolve um path absoluto (Zero Estados Indefinidos).
        """
        try:
            return str(
                Path(abs_path).resolve().relative_to(self._systemforge_root())
            )
        except ValueError:
            return abs_path

    def _build_mcp_column(self, mcp_btns: list[QPushButton]) -> QWidget:
        """Coluna entre output-toolbar-left e output-toolbar-progress-boxes.

        2 tabs + stacked pages:
        - Tab `MCPs`: radio Claude/Kimi/Codex + 3 botoes Main MCP/Parallel/Dual.
          A combinacao substitui a antiga matriz 3x3:
          Claude -> T1/linha laranja, Kimi -> T2/linha azul, Codex -> T3/linha roxa.
        - Tab `brainstorm`: picker de .md + grade 3x3 de botoes que publicam
          "<label> <path-do-md>" no terminal roteado (T1/T2/T3).

        `mcp_btns` na ordem fixa retornada por `_populate_header_actions`:
        [mcp-codex, mcp-kimi, double-mcp, kimi-claude, kimi-codex, kimi-dual,
         skill-claude, skill-kimi, skill-dual].
        """
        if len(mcp_btns) != 9:
            raise ValueError(
                f"_build_mcp_column espera exatamente 9 botoes MCP, "
                f"recebeu {len(mcp_btns)}. Verifique _populate_header_actions."
            )
        from PySide6.QtWidgets import (
            QButtonGroup,
            QFileDialog,
            QGridLayout,
            QHBoxLayout,
            QRadioButton,
            QStackedWidget,
            QVBoxLayout,
        )

        column = QWidget()
        column.setObjectName("OutputToolbarMcp")
        column.setProperty("testid", "output-toolbar-mcp")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(
            "QWidget#OutputToolbarMcp { background-color: #1C1C1F;"
            "  border: 1px solid #3F3F46; border-radius: 6px; }"
        )
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(8, 6, 8, 6)
        col_layout.setSpacing(4)

        # Tab bar com 2 tabs: MCPs / brainstorm
        tab_bar = QWidget()
        tab_bar.setProperty("testid", "output-progress-tabbar")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(3)

        self._mcp_tab_buttons: list[QPushButton] = []
        for label, slug in (("MCPs", "mcps"), ("Brainstorm (md)", "brainstorm")):
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("testid", f"output-mcp-tab-{slug}")
            tab_bar_layout.addWidget(btn, stretch=1)
            self._mcp_tab_buttons.append(btn)

        col_layout.addWidget(tab_bar)

        # Page 0 - MCPs: radio de provider + 3 acoes. Os 9 botoes legados
        # ficam parented em holder oculto para evitar coleta prematura pelo Qt.
        mcps_page = QWidget()
        mcps_layout = QVBoxLayout(mcps_page)
        mcps_layout.setContentsMargins(0, 0, 0, 0)
        mcps_layout.setSpacing(4)

        legacy_holder = QWidget(mcps_page)
        legacy_holder.setProperty("testid", "output-mcp-legacy-buttons-holder")
        legacy_holder.hide()
        for btn in mcp_btns:
            try:
                btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            btn.setParent(legacy_holder)
            btn.hide()
        self._mcp_legacy_buttons_holder = legacy_holder

        mcp_commands: dict[str, dict[str, tuple[str, int]]] = {
            "claude": {
                "main": ("/mcp:codex", 1),
                "parallel": ("/mcp:kimi", 1),
                "dual": ("/mcp:dual", 1),
            },
            "kimi": {
                "main": ("/skill:claude", 2),
                "parallel": ("/skill:codex", 2),
                "dual": ("/skill:dual", 2),
            },
            "codex": {
                "main": ("Use skill-claude. Output JSON. Prompt: ", 3),
                "parallel": ("Use skill-kimi. Output JSON. Prompt: ", 3),
                "dual": ("Use skill-dual. Output JSON. Mode: stereo. Prompt: ", 3),
            },
        }
        self._mcp_toolbar_commands = mcp_commands
        self._mcp_toolbar_provider = getattr(self, "_mcp_toolbar_provider", "claude")
        if self._mcp_toolbar_provider not in mcp_commands:
            self._mcp_toolbar_provider = "claude"

        existing_group = getattr(self, "_mcp_toolbar_provider_group", None)
        if existing_group is not None:
            try:
                existing_group.buttonToggled.disconnect()
            except (RuntimeError, TypeError):
                pass
            existing_group.deleteLater()

        provider_row = QWidget()
        provider_row.setObjectName("McpProviderRow")
        provider_row.setProperty("testid", "output-mcp-provider-radio-input")
        provider_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        provider_row.setStyleSheet(
            "QWidget#McpProviderRow { background-color: #27272A;"
            "  border: 1px solid #3F3F46; border-radius: 5px; }"
        )
        provider_layout = QHBoxLayout(provider_row)
        provider_layout.setContentsMargins(8, 0, 8, 0)
        provider_layout.setSpacing(8)
        provider_row.setFixedHeight(26)

        self._mcp_toolbar_provider_group = QButtonGroup(self)
        self._mcp_toolbar_provider_group.setExclusive(True)
        radio_style = (
            "QRadioButton { color: #FAFAFA; font-size: 11px;"
            "  font-weight: 700; background: transparent; border: none; }"
            "QRadioButton::indicator { width: 12px; height: 12px; }"
            "QRadioButton::indicator:unchecked { background-color: #18181B;"
            "  border: 1px solid #52525B; border-radius: 6px; }"
            "QRadioButton::indicator:checked { background-color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 6px; }"
            "QRadioButton::indicator:hover { border-color: #FDE68A; }"
        )

        for label, provider_id in (
            ("Claude", "claude"),
            ("Kimi", "kimi"),
            ("Codex", "codex"),
        ):
            rb = QRadioButton(label)
            rb.setProperty("provider_id", provider_id)
            rb.setProperty("testid", f"output-mcp-provider-{provider_id}")
            rb.setAccessibleName(f"Selecionar provider MCP {label}")
            rb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            rb.setStyleSheet(radio_style)
            rb.setChecked(provider_id == self._mcp_toolbar_provider)
            self._mcp_toolbar_provider_group.addButton(rb)
            provider_layout.addWidget(rb)
        provider_layout.addStretch(1)

        def _on_mcp_provider_changed(button, checked: bool) -> None:
            if not checked:
                return
            provider_id = button.property("provider_id")
            provider = str(provider_id or "").strip().lower()
            self._mcp_toolbar_provider = provider if provider in mcp_commands else "claude"

        self._mcp_toolbar_provider_group.buttonToggled.connect(
            _on_mcp_provider_changed
        )
        # provider_row NAO entra mais em mcps_layout: e reparenteado para o
        # queue-div-llm-routing (linha 1 da OutputToolbar) via
        # append_llm_routing_section, com label 'MCP'. Ref guardada para o
        # MainWindow dobrar apos o build do bottom row.
        self._mcp_provider_radio_input = provider_row

        # Personas/agentes (output-mcp-persona-checkboxes*): grade de 4 por linha
        # x 4 linhas (16 agentes). Os checkboxes marcados tem seus prompts
        # anexados ao comando MCP via _compose_mcp_text na ORDEM da UI (row-major).
        # A familia de pesquisa (search-in/search-out/search-forge) ocupa as 3
        # primeiras posicoes da Linha 1. exec-slash foi removido desta grade de
        # output para abrir espaco a search-forge na composicao original (continua
        # disponivel em queue-subtab-insertions-personas, que auto-descobre).
        persona_specs = (
            # Linha 1 — pesquisa + analise
            ("search-in", "output-mcp-persona-search-in",
             "no papel de search-in, conforme regras em "
             "ai-forge/MCP/agents/search-in-rules.md"),
            ("search-out", "output-mcp-persona-search-out",
             "no papel de search-out, conforme regras em "
             "ai-forge/MCP/agents/search-out-rules.md"),
            ("search-forge", "output-mcp-persona-search-forge",
             "no papel de search-forge, conforme regras em "
             "ai-forge/MCP/agents/search-forge-rules.md"),
            ("controversial", "output-mcp-persona-controversial",
             "no papel de controversial, conforme regras em "
             "ai-forge/MCP/agents/controversial-devils-advocate-rules.md"),
            # Linha 2 — robustez + ciclo de task
            ("hardening", "output-mcp-persona-hardening",
             "no papel de engenheiro de hardening, conforme regras em "
             "ai-forge/MCP/agents/hardening-engineer-rules.md"),
            ("criar-task", "output-mcp-persona-criar-task",
             "no papel de criador de tasks, conforme regras em "
             "ai-forge/MCP/agents/criar-task-rules.md"),
            ("revisar-task", "output-mcp-persona-revisar-task",
             "no papel de revisor de tasks criadas, conforme regras em "
             "ai-forge/MCP/agents/revisar-task-rules.md"),
            ("executor", "output-mcp-persona-executor",
             "no papel de executor de tasks, conforme regras em "
             "ai-forge/MCP/agents/executar-task-rules.md"),
            # Linha 3 — execucao + especializados
            ("rev-exec", "output-mcp-persona-rev-exec",
             "no papel de revisor de execucao, conforme regras em "
             "ai-forge/MCP/agents/revisar-execucao-rules.md"),
            ("revisar-qa", "output-mcp-persona-revisar-qa",
             "no papel de revisor de QA, conforme regras em "
             "ai-forge/MCP/agents/revisar-qa-rules.md"),
            ("code-debugger", "output-mcp-persona-code-debugger",
             "no papel de code-debugger, conforme regras em "
             "ai-forge/MCP/agents/code-debugger.md"),
            ("delegador", "output-mcp-persona-delegador",
             "no papel de analista-delegador, conforme regras em "
             "ai-forge/MCP/agents/analista-delegador-rules.md"),
            # Linha 4 — novos agentes de catalogo, clareza, UX e performance
            ("scaffold-update", "output-mcp-persona-scaffolds-blueprints-updater",
             "no papel de atualizador de scaffolds e blueprints, conforme regras em "
             "ai-forge/MCP/agents/scaffolds-blueprints-updater.md"),
            ("questionador", "output-mcp-persona-questioner",
             "no papel de questionador, conforme regras em "
             "ai-forge/MCP/agents/questioner-rules.md"),
            ("UX/UI", "output-mcp-persona-ux-ui",
             "no papel de especialista UX/UI, conforme regras em "
             "ai-forge/MCP/agents/ux-ui-specialist.md"),
            ("performance", "output-mcp-persona-performance-engineer",
             "no papel de performance engineer, conforme regras em "
             "ai-forge/MCP/agents/performance-engineer.md"),
        )
        checkbox_style = (
            "QCheckBox { color: #D4D4D8; font-size: 10px;"
            "  font-weight: 700; background: transparent; border: none; }"
            "QCheckBox::indicator { width: 11px; height: 11px; }"
            "QCheckBox::indicator:unchecked { background-color: #18181B;"
            "  border: 1px solid #52525B; border-radius: 3px; }"
            "QCheckBox::indicator:checked { background-color: #22C55E;"
            "  border: 1px solid #22C55E; border-radius: 3px; }"
            "QCheckBox::indicator:hover { border-color: #86EFAC; }"
        )
        self._mcp_persona_checkboxes: list[QCheckBox] = []
        # 4 checkboxes por linha (stretch igual); testids das linhas estaveis
        # (output-mcp-persona-checkboxes, -2, -3, -4).
        _persona_rows = [persona_specs[i:i + 4] for i in range(0, len(persona_specs), 4)]
        for _row_idx, _row_specs in enumerate(_persona_rows):
            _suffix = "" if _row_idx == 0 else f"-{_row_idx + 1}"
            _obj = "McpPersonaRow" if _row_idx == 0 else f"McpPersonaRow{_row_idx + 1}"
            row = QWidget()
            row.setObjectName(_obj)
            row.setProperty("testid", f"output-mcp-persona-checkboxes{_suffix}")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setStyleSheet(
                f"QWidget#{_obj} {{ background-color: #202027;"
                "  border: 1px solid #3F3F46; border-radius: 5px; }"
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 0, 8, 0)
            row_layout.setSpacing(7)
            row.setFixedHeight(26)
            for label, testid, prompt in _row_specs:
                chk = QCheckBox(label)
                chk.setProperty("testid", testid)
                chk.setProperty("persona_prompt", prompt)
                chk.setToolTip(prompt)
                chk.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                chk.setStyleSheet(checkbox_style)
                row_layout.addWidget(chk, stretch=1)
                self._mcp_persona_checkboxes.append(chk)
            mcps_layout.addWidget(row)

        def _compose_mcp_text(base_text: str) -> str:
            prompts = [
                str(chk.property("persona_prompt"))
                for chk in self._mcp_persona_checkboxes
                if chk.isChecked()
            ]
            if not prompts:
                return base_text
            return f"{base_text.rstrip()} {'; e depois disso '.join(prompts)}"

        action_row = QWidget()
        action_row.setProperty("testid", "output-mcp-action-row")
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)

        def _make_mcp_action_btn(label: str, action_id: str) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", f"output-mcp-action-{action_id}")
            btn.setFixedHeight(28)
            btn.setMinimumWidth(76)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                "Publica a acao MCP do provider selecionado nos terminais "
                "marcados em terminal-route-toggles (T1/T2/T3). O radio de "
                "provider escolhe APENAS o comando, nao o terminal."
            )
            btn.setStyleSheet(
                "QPushButton { background-color: #334155; color: #FAFAFA;"
                "  border: 1px solid #475569; border-radius: 5px;"
                "  font-size: 10px; font-weight: 800; padding: 0 8px; }"
                "QPushButton:hover { background-color: #3F4F66; border-color: #64748B; }"
                "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
                "  border-color: #FBBF24; }"
            )
            return btn

        def _on_mcp_action(action_id: str) -> None:
            # O radio de provider escolhe APENAS o comando (base_text). O terminal
            # de destino e decidido por terminal-route-toggles (T1/T2/T3), via
            # _publish_to_terminal (refactor 2026-05-24). O 2o elemento da tupla
            # (terminal fixo legado) e ignorado de proposito.
            provider = getattr(self, "_mcp_toolbar_provider", "claude")
            if provider not in mcp_commands:
                provider = "claude"
                self._mcp_toolbar_provider = provider
            base_text, _legacy_terminal = mcp_commands[provider][action_id]
            self._publish_to_terminal(_compose_mcp_text(base_text))

        for label, action_id in (
            ("Main MCP", "main"),
            ("Parallel", "parallel"),
            ("Dual", "dual"),
        ):
            btn = _make_mcp_action_btn(label, action_id)
            btn.clicked.connect(
                lambda _checked=False, aid=action_id: _on_mcp_action(aid)
            )
            action_layout.addWidget(btn, stretch=1)
        mcps_layout.addWidget(action_row)
        mcps_layout.addStretch(1)

        # Page 1 — brainstorm: picker .md + grade 3x3.
        brainstorm_page = self._build_brainstorm_page(QFileDialog, QGridLayout)

        stack = QStackedWidget()
        stack.addWidget(mcps_page)       # page 0
        stack.addWidget(brainstorm_page) # page 1
        col_layout.addWidget(stack, stretch=1)

        # Conectar tabs ao stack
        def _switch_mcp_tab(idx: int) -> None:
            stack.setCurrentIndex(idx)
            for i, b in enumerate(self._mcp_tab_buttons):
                b.setStyleSheet(
                    self._PROGRESS_TAB_ACTIVE_STYLE if i == idx else self._PROGRESS_TAB_INACTIVE_STYLE
                )

        for i, btn in enumerate(self._mcp_tab_buttons):
            btn.clicked.connect(lambda _ch=False, idx=i: _switch_mcp_tab(idx))

        _switch_mcp_tab(0)

        return column

    def _codex_terminal_available(self) -> bool:
        """True quando existe um widget canonico T3 com testid
        `terminal-codex-output` ativo: ou QPlainTextEdit/QTextEdit (legacy)
        ou widget xterm-duck (atributo `_shell.send_raw` callable).

        Pre-requisito do Gate G4 do mcp-flow-implantation.md §10.3
        (T3 da task-004 do loop 05-21-implantation-tasklist-aba-brainstorm).
        Usado tanto pelo radio (para desabilitar `rb_codex` quando o
        terminal Codex nao existe) quanto pelo `_on_mcp_prompt_requested`
        (para bloquear publicacao silenciosa).

        Hardening T026 (2026-05-22 — Codex adversarial pass 2): predicado
        funcional EQUIVALENTE ao de `MCPPromptButton._codex_target_alive()`
        em `widgets/mcp_prompt_button.py:530-580`. Antes este aceitava
        qualquer QWidget com o testid, permitindo que um placeholder
        QLabel emitisse `codex_availability_changed(True)` e envenenasse
        o cache do botao (`_on_codex_availability_changed` escreve direto
        em `_codex_alive_cache`). Agora gate e cache convergem.
        """
        for w in self.findChildren(QWidget):
            if w.property("testid") != "terminal-codex-output":
                continue
            if isinstance(w, (QPlainTextEdit, QTextEdit)):
                return True
            shell = getattr(w, "_shell", None)
            if shell is not None and callable(getattr(shell, "send_raw", None)):
                return True
        return False

    def _get_brainstorm_runtime_provider(self) -> str:
        """Getter canonico do provider runtime do radio brainstorm (T7).

        Retorna nome capitalizado ("Claude"/"Kimi"/"Codex") que bate com
        o contrato esperado por `MCPPromptButton._resolve_provider` para
        botoes button_type=type-selector-radio-input. Default "Claude"
        quando atributo ausente (defensive).
        """
        slug = (getattr(self, "_brainstorm_runtime_type", None) or "claude")
        slug_norm = str(slug).strip().lower()
        if slug_norm in _BRAINSTORM_PROVIDER_LABELS:
            return _BRAINSTORM_PROVIDER_LABELS[slug_norm]
        return "Claude"

    def _on_brainstorm_type_changed(self, button, checked: bool) -> None:
        """Slot do `_brainstorm_type_group.buttonToggled`.

        Atualiza `self._brainstorm_runtime_type` com o slug canonico
        lowercase do provider (lido via property `provider_id`, NUNCA
        via `button.text()` - hardening §1 da task-004 do loop
        05-21-implantation-tasklist-aba-brainstorm). Guard clause
        ignora a metade `checked=False` que o `buttonToggled` dispara
        em cada troca (hardening §4).
        """
        if not checked:
            return
        provider_id = button.property("provider_id")
        if provider_id in _BRAINSTORM_PROVIDER_SLUGS:
            self._brainstorm_runtime_type = provider_id

    def _build_brainstorm_page(self, q_file_dialog, q_grid_layout) -> QWidget:
        """Page da aba `brainstorm` da coluna MCP.

        Topo: botao picker de .md (abre QFileDialog, igual metrics-project-pill).
        O caminho selecionado fica em `self._brainstorm_md_path` e o proprio
        botao passa a exibir o nome do arquivo.

        Abaixo: grade seed-driven 4x6 (24 botoes), em ordem row-major. Cada
        botao monta o prompt da persona e publica no terminal selecionado.
        """
        from PySide6.QtWidgets import (
            QButtonGroup,
            QPushButton,
            QRadioButton,
            QVBoxLayout,
        )

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(4)

        # Picker de .md — guarda o path para os 24 botoes da grade.
        self._brainstorm_md_path: str | None = None
        md_btn = QPushButton("Selecionar .md")
        md_btn.setProperty("testid", "brainstorm-md-picker")
        md_btn.setFixedHeight(24)
        md_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        md_btn.setToolTip(
            "Abrir e selecionar um arquivo .md para os botoes de brainstorm"
        )
        md_btn.setStyleSheet(
            "QPushButton { background-color: #27272A; color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 5px;"
            "  font-size: 11px; font-weight: 700; padding: 0 10px; }"
            "QPushButton:hover { background-color: #3F3F46; border-color: #FDE68A; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )
        self._brainstorm_md_btn = md_btn

        def _pick_md(_checked: bool = False) -> None:
            # Diretorio canonico: blacksmith/brainstorm-mcp/ relativo a raiz
            # do SystemForge. Fallback: blacksmith/ (cf. mcp-flow-implantation.md
            # §7.5 + §10.3 item #1; T1 do loop 05-21-implantation-...).
            root = self._systemforge_root().resolve()
            canonical = root / "blacksmith" / "brainstorm-mcp"
            initial_dir = canonical
            created_now = False
            try:
                canonical.mkdir(parents=True, exist_ok=False)
                created_now = True
            except FileExistsError:
                pass  # canonico ja existe -> initial_dir = canonical mantido
            except (PermissionError, OSError) as exc:
                initial_dir = root / "blacksmith"
                if not self._brainstorm_toasts["mkdir_failed"]:
                    signal_bus.toast_requested.emit(
                        f"Diretorio canonico indisponivel: {exc.strerror or exc}",
                        "warning",
                    )
                    self._brainstorm_toasts["mkdir_failed"] = True
            if created_now and not self._brainstorm_toasts["created"]:
                signal_bus.toast_requested.emit(
                    "Diretorio criado: blacksmith/brainstorm-mcp/",
                    "info",
                )
                self._brainstorm_toasts["created"] = True

            path, _ = q_file_dialog.getOpenFileName(
                self, "Selecionar arquivo .md", str(initial_dir),
                "Markdown (*.md);;All Files (*)",
            )
            if not path:
                return  # cancelamento preserva estado anterior intacto
            # Symlink hardening: resolve() em ambos os lados antes de relative_to.
            candidate = Path(path).resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError:
                if self._brainstorm_toasts["outside_repo"] != str(candidate):
                    signal_bus.toast_requested.emit(
                        "Arquivo fora do repositorio SystemForge - selecao rejeitada.",
                        "warning",
                    )
                    self._brainstorm_toasts["outside_repo"] = str(candidate)
                return
            # Atomicidade: atribuir somente apos TODAS as validacoes passarem.
            self._brainstorm_md_path = path
            md_btn.setText(Path(path).name)
            md_btn.setToolTip(path)

        md_btn.clicked.connect(_pick_md)

        def _copy_selected_md_path() -> None:
            selected_path = (self._brainstorm_md_path or "").strip()
            if not selected_path:
                signal_bus.toast_requested.emit(
                    "Nenhum arquivo .md selecionado para copiar.", "warning"
                )
                return
            QApplication.clipboard().setText(selected_path)
            signal_bus.toast_requested.emit(
                "Path do .md copiado para a area de transferencia.", "info"
            )

        def _open_selected_md_reader() -> None:
            self._open_brainstorm_md_reader_dialog()

        # T4 (loop 05-21-implantation-tasklist-aba-brainstorm): row container
        # com `md_btn` (stretch=1) + copy path button + eye reader button +
        # `gear_btn_brainstorm` (24x24, _GearButton extraido). Testid canonico
        # `brainstorm-mcp-config-gear`. Clique abre
        # BrainstormMcpConfigDialog (modulo separado, import sob demanda no
        # handler para nao impactar cold start).
        row_container = QWidget()
        row_container.setProperty("testid", "brainstorm-md-picker-row")
        row_container.setStyleSheet("background: transparent; border: none;")
        row_layout = QHBoxLayout(row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        row_layout.addWidget(md_btn, stretch=1)
        copy_md_path_btn = QPushButton()
        copy_md_path_btn.setProperty("testid", "brainstorm-md-copy-path")
        copy_md_path_btn.setFixedSize(24, 24)
        copy_md_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_md_path_btn.setToolTip("Copiar path do arquivo .md selecionado")
        copy_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "copy.svg"
        copy_icon = self._load_tinted_svg_icon(copy_icon_path, "#FAFAFA")
        if copy_icon is not None:
            copy_md_path_btn.setIcon(copy_icon)
            copy_md_path_btn.setIconSize(QSize(12, 12))
        else:
            copy_md_path_btn.setText("⎘")
        copy_md_path_btn.setStyleSheet(_GEAR_QSS)
        copy_md_path_btn.clicked.connect(_copy_selected_md_path)
        self._brainstorm_md_copy_path_btn = copy_md_path_btn
        row_layout.addWidget(copy_md_path_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        eye_md_reader_btn = QPushButton()
        eye_md_reader_btn.setProperty("testid", "brainstorm-md-reader-open")
        eye_md_reader_btn.setFixedSize(24, 24)
        eye_md_reader_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        eye_md_reader_btn.setToolTip("Abrir leitor/editor do arquivo .md selecionado")
        eye_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "eye.svg"
        eye_icon = self._load_tinted_svg_icon(eye_icon_path, "#FAFAFA")
        if eye_icon is not None:
            eye_md_reader_btn.setIcon(eye_icon)
            eye_md_reader_btn.setIconSize(QSize(13, 13))
        else:
            eye_md_reader_btn.setText("1:1")
        eye_md_reader_btn.setStyleSheet(_GEAR_QSS)
        eye_md_reader_btn.clicked.connect(_open_selected_md_reader)
        self._brainstorm_md_reader_btn = eye_md_reader_btn
        row_layout.addWidget(eye_md_reader_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        gear_btn_brainstorm = _GearButton(
            testid="brainstorm-mcp-config-gear",
            tooltip="Configurar seeds brainstorm-mcp (label, prompt, agent, action, target)",
        )
        gear_btn_brainstorm.clicked.connect(self._open_brainstorm_mcp_config_dialog)
        self._brainstorm_mcp_config_gear = gear_btn_brainstorm
        row_layout.addWidget(gear_btn_brainstorm, 0, Qt.AlignmentFlag.AlignVCenter)
        # D2: o picker .md pertence ao bloco visual de anexos project/loop/brainstorm.
        # A pagina Brainstorm continua dona dos botoes e do estado; apenas o row
        # do picker e reparenteado para o bloco semantico de anexos.
        brainstorm_attachment_row = getattr(self, "_attachments_brainstorm_row", None)
        if brainstorm_attachment_row is not None and brainstorm_attachment_row.layout() is not None:
            brainstorm_attachment_row.layout().addWidget(row_container)
        else:
            page_layout.addWidget(row_container)

        # Cache do handle do page para rebuild via signal (T4 hardening §9).
        # Conexao defensiva (`UniqueConnection` impede duplicate em rebuild).
        self._brainstorm_page = page
        self._brainstorm_q_file_dialog = q_file_dialog
        self._brainstorm_q_grid_layout = q_grid_layout
        try:
            self._brainstorm_grid_invalidated.connect(
                self._rebuild_brainstorm_grid,
                Qt.ConnectionType.UniqueConnection,
            )
        except (RuntimeError, TypeError):
            pass  # ja conectado em rebuild anterior - idempotente.

        # Radio row dedicada de provider runtime (T3 do loop
        # 05-21-implantation-tasklist-aba-brainstorm). Consumida por
        # _on_mcp_prompt_requested apenas quando o botao clicado tem
        # button_type=type-selector-radio-input. Botoes button_type fixo
        # (Claude/Kimi/Codex) IGNORAM o radio. Source-of-truth via
        # property `provider_id` (slug lowercase), NUNCA via button.text().
        # Cleanup explicito de QButtonGroup antigo evita signals
        # duplicados em rebuild (hardening §6).
        existing_group = getattr(self, "_brainstorm_type_group", None)
        if existing_group is not None:
            try:
                existing_group.buttonToggled.disconnect()
            except (RuntimeError, TypeError):
                pass
            existing_group.deleteLater()
            self._brainstorm_type_group = None

        radio_row = QWidget()
        radio_row.setObjectName("BrainstormProviderRow")
        radio_row.setProperty("testid", "type-selector-radio-input")
        radio_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        radio_row.setStyleSheet(
            "QWidget#BrainstormProviderRow { background-color: #27272A;"
            "  border: 1px solid #3F3F46; border-radius: 5px; }"
        )
        radio_row_layout = QHBoxLayout(radio_row)
        radio_row_layout.setContentsMargins(8, 0, 8, 0)
        radio_row_layout.setSpacing(8)
        radio_row.setFixedHeight(26)

        rb_claude = QRadioButton("Claude")
        rb_kimi = QRadioButton("Kimi")
        rb_codex = QRadioButton("Codex")

        codex_available = self._codex_terminal_available()
        # Cache do estado de T3 para emit cross-widget apos a montagem do
        # radio (T7 task-008): MCPPromptButton instancias antigas sincronizam
        # via signal codex_availability_changed.
        self._brainstorm_codex_available = codex_available
        radio_specs = (
            (rb_claude, "claude", "Selecionar provedor Claude", True),
            (rb_kimi, "kimi", "Selecionar provedor Kimi", True),
            # Codex sempre selecionavel no radio: fallback de runtime
            # garante T3->T2 quando o xterm nao estiver disponivel.
            (rb_codex, "codex", "Selecionar provedor Codex", True),
        )

        self._brainstorm_type_group = QButtonGroup(self)
        self._brainstorm_type_group.setExclusive(True)

        for rb, provider_id, accessible_name, enabled in radio_specs:
            rb.setProperty("provider_id", provider_id)
            rb.setProperty("testid", f"type-selector-radio-{provider_id}")
            rb.setAccessibleName(accessible_name)
            rb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            rb.setStyleSheet(
                "QRadioButton { color: #FAFAFA; font-size: 11px;"
                "  font-weight: 600; background: transparent; border: none; }"
                "QRadioButton::indicator { width: 12px; height: 12px; }"
                "QRadioButton::indicator:unchecked { background-color: #18181B;"
                "  border: 1px solid #52525B; border-radius: 6px; }"
                "QRadioButton::indicator:checked { background-color: #FBBF24;"
                "  border: 1px solid #FBBF24; border-radius: 6px; }"
                "QRadioButton::indicator:hover { border-color: #FDE68A; }"
                "QRadioButton:disabled { color: #52525B; }"
                "QRadioButton::indicator:disabled { background-color: #27272A;"
                "  border-color: #3F3F46; }"
            )
            rb.setEnabled(enabled)
            self._brainstorm_type_group.addButton(rb)
            radio_row_layout.addWidget(rb)

        if not codex_available:
            rb_codex.setToolTip(
                "Terminal Codex (T3) indisponivel no momento: envios Codex "
                "farao fallback automatico para T2."
            )

        radio_row_layout.addStretch(1)

        # Ordem de sinais (hardening §5): conectar slot ANTES do setChecked
        # inicial, mas com blockSignals para nao disparar callback espurio.
        self._brainstorm_type_group.buttonToggled.connect(
            self._on_brainstorm_type_changed
        )
        rb_claude.blockSignals(True)
        rb_claude.setChecked(True)
        rb_claude.blockSignals(False)
        # Inicializacao deterministica do atributo runtime (hardening §3):
        # garante valor canonico mesmo se buttonToggled nao disparar.
        self._brainstorm_runtime_type = "claude"

        # radio_row NAO entra mais em page_layout: e reparenteado para o
        # queue-div-llm-routing (linha 1 da OutputToolbar) via
        # append_llm_routing_section, com label 'brainstorm'. Ref guardada para
        # o MainWindow dobrar apos o build do bottom row. O radio_state_getter
        # (self._brainstorm_runtime_type) e os signals seguem intactos.
        self._brainstorm_type_selector_row = radio_row

        # Grade seed-driven (T2 loop 05-21-implantation-tasklist-aba-brainstorm).
        # 1 MCPPromptButton por seed em blacksmith/brainstorm-mcp/NN-*.md,
        # ordem deterministica por nome de arquivo.
        grid_widget = QWidget()
        grid_widget.setObjectName("BrainstormGrid")
        grid_widget.setProperty("testid", "brainstorm-buttons-grid")
        grid_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        grid_widget.setStyleSheet(
            "QWidget#BrainstormGrid { background-color: #18181B;"
            "  border: 1px solid #3F3F46; border-radius: 5px; }"
        )
        grid = q_grid_layout(grid_widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        self._brainstorm_mcp_btns = []
        try:
            seeds = self._load_brainstorm_seeds()
        except _BrainstormSeedError as exc:
            signal_bus.toast_requested.emit(
                f"Grade brainstorm bloqueada: {exc}",
                "error",
            )
            page_layout.addWidget(grid_widget)
            page_layout.addStretch(1)
            return page

        # Atomic widget construction: ou os 24 sobem, ou nenhum.
        built: list[MCPPromptButton] = []
        try:
            for seed in seeds:
                target_terminal = (
                    seed["target_terminal"] or "terminal-interactive-output"
                )
                # Codex exige terminal-codex-output (regra do widget).
                if seed["button_type"] == "Codex":
                    target_terminal = "terminal-codex-output"
                btn = MCPPromptButton(
                    label=seed["label"],
                    button_type=seed["button_type"],
                    prompt=seed["seed_path"],
                    agent_name=seed["agent_name"],
                    agent_path=seed["agent_path"],
                    action=seed["action"],
                    target_path=target_terminal,
                    testid_slug=seed["slug"],
                    target_path_edit_inplace=seed["target_path_edit_inplace"],
                    radio_state_getter=self._get_brainstorm_runtime_provider,
                )
                btn.setFixedHeight(22)
                btn.setMinimumWidth(60)
                btn.prompt_requested.connect(self._on_mcp_prompt_requested)
                built.append(btn)
        except Exception as exc:  # noqa: BLE001
            for w in built:
                w.deleteLater()
            signal_bus.toast_requested.emit(
                f"Grade brainstorm falhou: {exc}",
                "error",
            )
            page_layout.addWidget(grid_widget)
            page_layout.addStretch(1)
            return page

        cols = getattr(
            self,
            "_BRAINSTORM_GRID_COLUMNS",
            MainWindow._BRAINSTORM_GRID_COLUMNS,
        )
        for i, btn in enumerate(built):
            grid.addWidget(btn, i // cols, i % cols)
        self._brainstorm_mcp_btns = built
        # Cache refs para rebuild via _rebuild_brainstorm_grid (T4 hardening §9).
        self._brainstorm_grid_widget = grid_widget
        self._brainstorm_grid_layout = grid

        page_layout.addWidget(grid_widget)
        page_layout.addStretch(1)
        # T7 (task-008): publica estado inicial de T3 para que botoes Codex
        # fixos sincronizem o cache via signal logo apos a montagem da grade.
        signal_bus.codex_availability_changed.emit(self._codex_terminal_available())
        return page

    def _open_brainstorm_md_reader_dialog(self) -> None:
        selected_path_raw = (self._brainstorm_md_path or "").strip()
        if not selected_path_raw:
            signal_bus.toast_requested.emit(
                "Nenhum arquivo .md selecionado para abrir no leitor.", "warning"
            )
            return
        selected_path = Path(selected_path_raw)
        if not selected_path.is_file():
            signal_bus.toast_requested.emit(
                "Arquivo .md selecionado nao existe mais.", "warning"
            )
            return
        if selected_path.suffix.lower() not in {".md", ".markdown"}:
            signal_bus.toast_requested.emit(
                "O leitor brainstorm aceita apenas arquivos Markdown.", "warning"
            )
            return
        from workflow_app.widgets.brainstorm_md_reader_dialog import (
            BrainstormMdReaderDialog,
        )

        dlg = BrainstormMdReaderDialog(selected_path, self)
        dlg.exec()

    def _open_brainstorm_mcp_config_dialog(self) -> None:
        """Abre o modal de configuracao dos seeds brainstorm-mcp (T4).

        Lifecycle hardened (cf. hardening §5 task-005 loop
        05-21-implantation-tasklist-aba-brainstorm):
        - Single-open guard: se ja visivel, raise+activate e retorna.
        - `WA_DeleteOnClose` libera memoria ao fechar.
        - `repo_root` injetado no construtor (resolve falha de validacao
          contra `Path.cwd()` quando o app roda em outro diretorio).
        - Import sob demanda do dialog (modulo separado) para nao
          impactar cold start do main_window.
        """
        dlg = getattr(self, "_brainstorm_mcp_dialog", None)
        if dlg is not None:
            try:
                if dlg.isVisible():
                    dlg.raise_()
                    dlg.activateWindow()
                    return
            except RuntimeError:
                # Widget ja deletado pelo Qt; segue para criar um novo.
                self._brainstorm_mcp_dialog = None

        from workflow_app.widgets.brainstorm_mcp_config_dialog import (
            BrainstormMcpConfigDialog,
        )

        repo_root = self._systemforge_root().resolve()
        dlg = BrainstormMcpConfigDialog(self, repo_root=repo_root)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.finished.connect(
            lambda _result: setattr(self, "_brainstorm_mcp_dialog", None),
        )
        dlg.saved.connect(self._brainstorm_grid_invalidated.emit)
        self._brainstorm_mcp_dialog = dlg
        dlg.open()

    def _rebuild_brainstorm_grid(self) -> None:
        """Reconstroi a grade 4x6 apos save do modal de config (T4).

        Atomic: ou os 24 botoes sobem, ou a grade fica vazia com toast erro
        (mesma politica do build inicial em `_build_brainstorm_page`).
        Desconecta signals e chama `deleteLater()` em cada botao antigo
        para evitar slots disparando em widgets em destruicao.
        """
        grid = getattr(self, "_brainstorm_grid_layout", None)
        if grid is None:
            return

        # 1) Tear down dos botoes antigos.
        for btn in list(getattr(self, "_brainstorm_mcp_btns", []) or []):
            try:
                btn.prompt_requested.disconnect(self._on_mcp_prompt_requested)
            except (RuntimeError, TypeError):
                pass
            try:
                grid.removeWidget(btn)
            except Exception:  # noqa: BLE001
                pass
            btn.deleteLater()
        self._brainstorm_mcp_btns = []

        # 2) Reload seeds (fail-fast all-or-nothing).
        try:
            seeds = self._load_brainstorm_seeds()
        except _BrainstormSeedError as exc:
            signal_bus.toast_requested.emit(
                f"Grade brainstorm bloqueada apos save: {exc}",
                "error",
            )
            return

        built: list[MCPPromptButton] = []
        try:
            for seed in seeds:
                target_terminal = (
                    seed["target_terminal"] or "terminal-interactive-output"
                )
                if seed["button_type"] == "Codex":
                    target_terminal = "terminal-codex-output"
                btn = MCPPromptButton(
                    label=seed["label"],
                    button_type=seed["button_type"],
                    prompt=seed["seed_path"],
                    agent_name=seed["agent_name"],
                    agent_path=seed["agent_path"],
                    action=seed["action"],
                    target_path=target_terminal,
                    testid_slug=seed["slug"],
                    target_path_edit_inplace=seed["target_path_edit_inplace"],
                    radio_state_getter=self._get_brainstorm_runtime_provider,
                )
                btn.setFixedHeight(22)
                btn.setMinimumWidth(60)
                btn.prompt_requested.connect(self._on_mcp_prompt_requested)
                built.append(btn)
        except Exception as exc:  # noqa: BLE001
            for w in built:
                w.deleteLater()
            signal_bus.toast_requested.emit(
                f"Grade brainstorm falhou apos save: {exc}",
                "error",
            )
            return

        cols = getattr(
            self,
            "_BRAINSTORM_GRID_COLUMNS",
            MainWindow._BRAINSTORM_GRID_COLUMNS,
        )
        for i, btn in enumerate(built):
            grid.addWidget(btn, i // cols, i % cols)
        self._brainstorm_mcp_btns = built
        # T7 (task-008): publica estado de T3 apos rebuild para resync de
        # cache em botoes Codex fixos recem-criados.
        signal_bus.codex_availability_changed.emit(self._codex_terminal_available())
        signal_bus.toast_requested.emit(
            "Seeds brainstorm-mcp atualizados.", "info",
        )

    def _on_mcp_prompt_requested(self, payload: dict) -> None:
        """Slot canonico para clicks em MCPPromptButton da grade brainstorm.

        Monta o template hardened (§6.5 task-008 do mcp-flow-implantation.md
        linhas 719-728) e publica no terminal canonico segundo o `target_path`
        do payload. Debounce de 300ms (anti double-click).

        Gate Zero Silencio: se `target_path_edit_inplace` e nao ha .md
        selecionado pelo picker, emite toast warning e aborta.
        """
        if getattr(self, "_prompt_in_flight", False):
            return
        self._prompt_in_flight = True
        # button_id propagado por MCPPromptButton.payload() (T7); usado
        # para direcionar signal_bus.dispatch_result ao widget de origem.
        # Fallback "" filtra sem efeito caso payload legado nao traga.
        button_id = str(payload.get("button_id") or "")
        try:
            edit_inplace = bool(payload.get("target_path_edit_inplace"))
            md_path = (getattr(self, "_brainstorm_md_path", None) or "").strip()
            if edit_inplace and not md_path:
                signal_bus.toast_requested.emit(
                    "Selecione .md primeiro",
                    "warning",
                )
                signal_bus.dispatch_result.emit(button_id, False)
                return

            action = str(payload.get("action", ""))
            agent_name = str(payload.get("agent_name") or "")
            agent_path = str(payload.get("agent_path") or "")
            button_type = str(payload.get("button_type", "Claude"))

            # Runtime resolution: button_type=type-selector-radio-input
            # consulta self._brainstorm_runtime_type instalado pelo radio
            # de T3. Snapshot local imediato (hardening §9 da task-004 do
            # loop 05-21-implantation-tasklist-aba-brainstorm) protege
            # contra mutacao concorrente durante a montagem do prompt.
            if button_type == "type-selector-radio-input":
                runtime_snapshot = getattr(
                    self, "_brainstorm_runtime_type", "claude"
                ) or "claude"
                resolved_slug = str(runtime_snapshot).lower()
            else:
                resolved_slug = str(button_type).lower()

            resolved_type = _BRAINSTORM_PROVIDER_LABELS.get(
                resolved_slug, str(button_type)
            )

            # "Criar arquivo" (botao 1 / Criar md) cria um MD NOVO a partir
            # do T1. Ele nunca deve ler, anexar ou renderizar o .md selecionado
            # no brainstorm-md-picker-row, mesmo que exista um path ativo.
            md_ref = (
                None
                if action == "Criar arquivo"
                else self._rel_to_root(md_path) if md_path else None
            )
            seed_meta: dict[str, object] = {
                "agent_name": agent_name,
                "agent_path": agent_path,
                "action": action,
                "target_path": edit_inplace,
            }
            for k in ("agent2_name", "agent2_path", "action2"):
                v = payload.get(k)
                if v:
                    seed_meta[k] = v
            seed_meta = append_public_context(
                seed_meta,
                project=app_state.project_config,
                loop=app_state.loop_config,
            )

            try:
                repo_root = self._systemforge_root().resolve()
                prompt_final = build_prompt(seed_meta, md_ref, repo_root)
            except ValueError as exc:
                signal_bus.toast_requested.emit(str(exc), "warning")
                signal_bus.dispatch_result.emit(button_id, False)
                return
            except TypeError as exc:
                signal_bus.toast_requested.emit(
                    f"Erro montando prompt: {exc}", "error"
                )
                signal_bus.dispatch_result.emit(button_id, False)
                return

            # Roteamento: target_path do payload mapeia para terminal index.
            terminal_map = {
                "terminal-interactive-output": 1,
                "terminal-workspace-output": 2,
                "terminal-codex-output": 3,
            }
            # Contrato canonico (mesmo dos comandos da toolbar): os toggles
            # T1/T2/T3 de `output-toolbar-left-insertions-controls` decidem o
            # terminal; o radio `type-selector-radio-input` escolhe o comando,
            # NAO o terminal. Antes o terminal era derivado do provider
            # (codex->T3) ignorando os toggles, o que publicava no terminal
            # errado mesmo com T3 marcado.
            route_t1 = (
                bool(self._chk_route_t1.isChecked())
                if hasattr(self, "_chk_route_t1") else False
            )
            route_t2 = (
                bool(self._chk_route_t2.isChecked())
                if hasattr(self, "_chk_route_t2") else False
            )
            route_t3 = (
                bool(self._chk_route_t3.isChecked())
                if hasattr(self, "_chk_route_t3") else False
            )
            targets: list[int] = []
            if route_t1 or route_t2 or route_t3:
                if route_t1:
                    targets.append(1)
                if route_t2:
                    targets.append(2)
                if route_t3:
                    targets.append(3)
            else:
                # Fallback (toggles ausentes/desmarcados): preserva o
                # comportamento legado baseado no target_path do payload.
                target_terminal = payload.get("target_path")
                if button_type == "type-selector-radio-input":
                    target_terminal = {
                        "claude": "terminal-interactive-output",
                        "kimi": "terminal-workspace-output",
                        "codex": "terminal-codex-output",
                    }.get(resolved_slug, "terminal-interactive-output")
                elif not target_terminal:
                    target_terminal = (
                        "terminal-interactive-output"
                        if resolved_type == "Claude"
                        else "terminal-workspace-output"
                    )
                targets.append(terminal_map.get(target_terminal, 1))
            # Fallback operacional: se T3 e alvo mas o terminal Codex nao
            # esta disponivel, redireciona para T2 (dedup preservando ordem).
            if 3 in targets and not self._codex_terminal_available():
                targets = [2 if t == 3 else t for t in targets]
                targets = list(dict.fromkeys(targets))
                signal_bus.toast_requested.emit(
                    "Codex selecionado, mas T3 indisponivel. Prompt enviado no T2.",
                    "warning",
                )
            terminal_idx = targets[-1] if targets else 1
            try:
                published_ok = True
                for _idx in targets:
                    if not self._publish_to_specific_terminal(prompt_final, _idx):
                        published_ok = False
                        terminal_idx = _idx
            except Exception as exc:  # noqa: BLE001
                signal_bus.toast_requested.emit(
                    f"Falha ao publicar prompt: {exc}", "error"
                )
                signal_bus.dispatch_result.emit(button_id, False)
                return
            # Fix T020 (BLOCKER 1): antes, T3 com falha silenciosa
            # (shell nao iniciado, send_raw exception) emitia
            # dispatch_result(True) mascarando incidente. Agora o
            # caller propaga toast de erro e dispatch_result(False) quando
            # `_publish_to_specific_terminal` retorna False (apenas T3 pode
            # falhar — T1/T2 sao fire-and-forget e sempre retornam True).
            if not published_ok:
                canonical_t3_err = (
                    "Falha ao injetar prompt no terminal Codex (T3): shell "
                    "nao iniciado. Publicacao abortada para evitar perda "
                    "silenciosa do prompt. Verifique se o terminal "
                    "terminal-codex-output (pyte) esta ativo."
                )
                signal_bus.toast_requested.emit(canonical_t3_err, "error")
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "t3_publish_failed",
                    extra={
                        "button_id": button_id or "unknown",
                        "seed_slug": str(payload.get("testid_slug") or ""),
                        "terminal_idx": terminal_idx,
                        "reason": "xterm_inject_returned_false",
                    },
                )
                signal_bus.dispatch_result.emit(button_id, False)
                return
            # Sucesso real: marca checkbox do botao de origem via signal_bus.
            signal_bus.dispatch_result.emit(button_id, True)
        finally:
            QTimer.singleShot(300, lambda: setattr(self, "_prompt_in_flight", False))

    def _publish_to_specific_terminal(self, text: str, terminal: int) -> bool:
        """Publica `text` num terminal especifico (1/2/3), ignorando T1/T2/T3.

        Retorna True quando a publicacao foi confirmada, False quando o sink
        nao recebeu os bytes (apenas T3: shell nao iniciado, send_raw falhou).
        T1 e T2 sao fire-and-forget via signal_bus, retornam True
        incondicionalmente (semantica historica preservada).

        Espelha o mapping de `_publish_to_terminal` sem consultar os
        checkboxes `terminal-route-toggles`:
        - 1 -> terminal-interactive (pyte) via paste_text_in_terminal.
        - 2 -> terminal-workspace (pyte) via paste_text_in_workspace_terminal.
        - 3 -> terminal-codex-output (pyte) via _xterm_inject_text (retorna bool).

        Fix T020 (BLOCKER 1) loop 05-21-implantation-tasklist-aba-brainstorm:
        antes, T3 com falha (shell nao iniciado) emitia sucesso fantasma;
        caller agora propaga toast de erro quando falha.
        """
        if terminal == 1:
            signal_bus.paste_text_in_terminal.emit(text)
            signal_bus.focus_interactive_terminal.emit()
            return True
        elif terminal == 2:
            signal_bus.paste_text_in_workspace_terminal.emit(text)
            try:
                self._workspace_panel._terminal.setFocus()
            except AttributeError:
                pass
            return True
        elif terminal == 3:
            ok = self._xterm_inject_text(text, with_enter=False)
            if hasattr(self, "_workspace_panel_xterm"):
                try:
                    self._workspace_panel_xterm._terminal.setFocus()
                except AttributeError:
                    pass
            return bool(ok)
        return False

    _PX_RULER_WIDTHS = (10, 50, 100)
    _DATATEST_LAUNCHER_STYLE = (
        "QPushButton { background-color: #27272A; color: #FAFAFA;"
        "  border: 1px solid #52525B; border-radius: 6px;"
        "  font-size: 11px; font-weight: 700; padding: 0 8px; }"
        "QPushButton:hover { background-color: #3F3F46; border-color: #71717A; }"
        "QPushButton:checked { background-color: #FBBF24; color: #18181B;"
        "  border-color: #FBBF24; }"
    )
    _TEST_MODE_BTN_STYLE_MAIN = (
        "QPushButton { background-color: transparent; color: #4ADE80;"
        "  border: 1px solid #16A34A; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 8px; }"
        "QPushButton:hover { color: #FAFAFA; background-color: #166534;"
        "  border-color: #22C55E; }"
        "QPushButton:checked { background-color: #16A34A; color: #FAFAFA;"
        "  border-color: #16A34A; font-weight: 700; }"
    )
    _TEST_MODE_BTN_STYLE_BODY = (
        "QPushButton { background-color: transparent; color: #F87171;"
        "  border: 1px solid #DC2626; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 8px; }"
        "QPushButton:hover { color: #FAFAFA; background-color: #7F1D1D;"
        "  border-color: #EF4444; }"
        "QPushButton:checked { background-color: #DC2626; color: #FAFAFA;"
        "  border-color: #DC2626; font-weight: 700; }"
    )
    _TEST_MODE_BTN_STYLE_BTN = (
        "QPushButton { background-color: transparent; color: #60A5FA;"
        "  border: 1px solid #2563EB; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 8px; }"
        "QPushButton:hover { color: #FAFAFA; background-color: #1E3A8A;"
        "  border-color: #3B82F6; }"
        "QPushButton:checked { background-color: #2563EB; color: #FAFAFA;"
        "  border-color: #2563EB; font-weight: 700; }"
    )
    _TEST_MODE_BTN_STYLE_PX = (
        "QPushButton { background-color: transparent; color: #FBBF24;"
        "  border: 1px solid #D97706; border-radius: 6px;"
        "  font-size: 11px; font-weight: 600; padding: 0 8px; }"
        "QPushButton:hover { color: #18181B; background-color: #F59E0B;"
        "  border-color: #FBBF24; }"
        "QPushButton:checked { background-color: #FBBF24; color: #18181B;"
        "  border-color: #FBBF24; font-weight: 700; }"
    )

    def _build_test_mode_column(self) -> QWidget:
        """Coluna compacta: apenas o launcher DataTest da janela flutuante."""

        column = QWidget()
        column.setObjectName("OutputToolbarTestMode")
        column.setProperty("testid", "output-toolbar-test-mode")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(
            "QWidget#OutputToolbarTestMode { background-color: transparent;"
            "  border: none; }"
        )
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(6, 6, 6, 6)
        col_layout.setSpacing(0)

        self._build_datatest_floating_panel()
        btn = QPushButton("DataTest")
        btn.setProperty("testid", "output-toolbar-datatest-toggle")
        btn.setFixedSize(74, 32)
        btn.setCheckable(True)
        btn.setToolTip("Abrir controles DataTest")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(self._DATATEST_LAUNCHER_STYLE)
        btn.toggled.connect(self._toggle_datatest_panel)
        self._datatest_panel_button = btn
        col_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        return column

    def _build_datatest_floating_panel(self) -> None:
        if self._datatest_panel is not None:
            return
        from PySide6.QtWidgets import QButtonGroup

        parent = self.centralWidget()
        panel = _DraggableFloatingPanel(parent)
        panel.setObjectName("DataTestFloatingPanel")
        panel.setProperty("testid", "datatest-floating-panel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedHeight(52)
        panel.setStyleSheet(
            "QWidget#DataTestFloatingPanel { background-color: #1C1C1F;"
            "  border: 1px solid #52525B; border-radius: 8px; }"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        terminal_checkbox = QCheckBox(panel)
        terminal_checkbox.setObjectName("DataTestTerminalWriteToggle")
        terminal_checkbox.setProperty("testid", "datatest-terminal-write-toggle")
        terminal_checkbox.setFixedSize(18, 32)
        terminal_checkbox.setToolTip(
            "Ao clicar no overlay, envia o seletor para o terminal roteado"
        )
        terminal_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        terminal_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 12px; height: 12px; border-radius: 3px;"
            " border: 1px solid #9CA3AF; background-color: #27272A; }"
            "QCheckBox::indicator:checked {"
            " border: 1px solid #FBBF24; background-color: #FBBF24; }"
        )
        terminal_checkbox.toggled.connect(self._set_datatest_terminal_write_enabled)
        layout.addWidget(terminal_checkbox, alignment=Qt.AlignmentFlag.AlignVCenter)

        btn_main = QPushButton("Main", panel)
        btn_main.setFixedSize(64, 32)
        btn_main.setCheckable(True)
        btn_main.setToolTip("Exibir apenas os principais blocos do app")
        btn_main.setStyleSheet(self._TEST_MODE_BTN_STYLE_MAIN)
        btn_main.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_body = QPushButton("Body", panel)
        btn_body.setFixedSize(64, 32)
        btn_body.setCheckable(True)
        btn_body.setToolTip("Exibir data-testid EXCETO em botoes")
        btn_body.setStyleSheet(self._TEST_MODE_BTN_STYLE_BODY)
        btn_body.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_btn = QPushButton("Btn", panel)
        btn_btn.setFixedSize(64, 32)
        btn_btn.setCheckable(True)
        btn_btn.setToolTip("Exibir data-testid APENAS em botoes")
        btn_btn.setStyleSheet(self._TEST_MODE_BTN_STYLE_BTN)
        btn_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_px = QPushButton("px ruler", panel)
        btn_px.setProperty("testid", "datatest-px-ruler-toggle")
        btn_px.setFixedSize(76, 32)
        btn_px.setCheckable(True)
        btn_px.setToolTip("Mostrar regua de largura em pixels")
        btn_px.setStyleSheet(self._TEST_MODE_BTN_STYLE_PX)
        btn_px.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_px.toggled.connect(self._toggle_px_ruler)

        for btn in (btn_main, btn_body, btn_btn, btn_px):
            layout.addWidget(btn)

        self._test_mode_group = QButtonGroup(self)
        self._test_mode_group.setExclusive(False)
        for btn in (btn_main, btn_body, btn_btn):
            self._test_mode_group.addButton(btn)

        self._test_mode_buttons = {
            "main": btn_main,
            "body": btn_body,
            "buttons": btn_btn,
        }
        self._test_mode_syncing = False
        for btn in self._test_mode_buttons.values():
            btn.toggled.connect(self._on_test_mode_button_toggled)

        panel.hide()
        self._datatest_panel = panel
        self._position_datatest_panel()

    def _toggle_datatest_panel(self, checked: bool) -> None:
        panel = self._datatest_panel
        if panel is None:
            return
        if checked:
            self._position_datatest_panel()
            panel.show()
            panel.raise_()
        else:
            panel.hide()

    def _position_datatest_panel(self) -> None:
        panel = self._datatest_panel
        parent = self.centralWidget()
        if panel is None or parent is None:
            return
        panel.adjustSize()
        margin = 12
        if not panel.was_dragged:
            panel.move(
                max(margin, parent.width() - panel.width() - margin),
                max(margin, parent.height() - panel.height() - margin),
            )
            return
        panel.move(
            min(max(0, panel.x()), max(0, parent.width() - panel.width())),
            min(max(0, panel.y()), max(0, parent.height() - panel.height())),
        )

    def _set_datatest_terminal_write_enabled(self, enabled: bool) -> None:
        self._datatest_terminal_write_enabled = bool(enabled)

    def _toggle_px_ruler(self, checked: bool) -> None:
        if checked:
            self._show_px_ruler_toasts()
        else:
            self._hide_px_ruler_toasts()

    def _show_px_ruler_toasts(self) -> None:
        host = self.centralWidget()
        if host is None:
            return
        self._hide_px_ruler_toasts()
        for width_px in self._PX_RULER_WIDTHS:
            toast = QLabel(f"{width_px}px", host)
            toast.setObjectName(f"WorkflowPxRulerToast{width_px}")
            toast.setProperty("testid", f"px-ruler-toast-{width_px}")
            toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
            toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            toast.setFixedWidth(width_px)
            toast.setFixedHeight(20)
            toast.setStyleSheet(
                "background-color: rgba(34, 197, 94, 0.95);"
                "color: #FFFFFF;"
                "font-size: 10px;"
                "font-weight: 700;"
                "border-radius: 3px;"
            )
            toast.show()
            toast.raise_()
            self._px_ruler_toasts.append(toast)
        self._ensure_px_ruler_resize_filter(host)
        self._reposition_px_ruler_toasts()

    def _hide_px_ruler_toasts(self) -> None:
        for toast in self._px_ruler_toasts:
            toast.hide()
            toast.deleteLater()
        self._px_ruler_toasts.clear()
        self._remove_px_ruler_resize_filter()

    def _reposition_px_ruler_toasts(self) -> None:
        if not self._px_ruler_toasts:
            return
        host = self._px_ruler_toasts[0].parentWidget()
        if host is None:
            return
        margin = 12
        gap = 6
        y = host.height() - margin
        for toast in reversed(self._px_ruler_toasts):
            y -= toast.height()
            toast.move(margin, max(0, y))
            toast.raise_()
            y -= gap

    def _ensure_px_ruler_resize_filter(self, host: QWidget) -> None:
        class _ResizeFilter(QObject):
            def __init__(self, owner: MainWindow, parent: QObject | None = None) -> None:
                super().__init__(parent)
                self._owner = owner

            def eventFilter(self, watched: QObject, event: QEvent) -> bool:
                if event.type() == QEvent.Type.Resize:
                    self._owner._reposition_px_ruler_toasts()
                return False

        self._remove_px_ruler_resize_filter()
        self._px_ruler_resize_filter = _ResizeFilter(self, host)
        host.installEventFilter(self._px_ruler_resize_filter)

    def _remove_px_ruler_resize_filter(self) -> None:
        filter_obj = self._px_ruler_resize_filter
        if filter_obj is None:
            return
        host = filter_obj.parent()
        if isinstance(host, QWidget):
            host.removeEventFilter(filter_obj)
        self._px_ruler_resize_filter = None

    # _PROGRESS_TAB_ACTIVE_STYLE / _INACTIVE_STYLE sao compartilhados com a tab
    # bar do _build_mcp_column (_switch_mcp_tab). Os antigos constantes
    # _PROGRESS_BOX_* (cards decorativos de output-toolbar-progress-boxes) foram
    # removidos junto com a coluna, que nao tinha side effects.
    _PROGRESS_TAB_ACTIVE_STYLE = (
        "QPushButton { background-color: #FBBF24; color: #18181B;"
        "  border: none; border-radius: 3px;"
        "  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }"
    )
    _PROGRESS_TAB_INACTIVE_STYLE = (
        "QPushButton { background-color: transparent; color: #A1A1AA;"
        "  border: none; border-radius: 3px;"
        "  font-size: 10px; font-weight: 600; letter-spacing: 0.5px; }"
        "QPushButton:hover { color: #D4D4D8; background-color: #2D2D30; }"
    )

    def _click_command_queue_button(self, testid: str) -> None:
        """Programa um click no botão da command queue identificado por testid."""
        from PySide6.QtWidgets import QPushButton as _Btn

        if not hasattr(self, "_command_queue"):
            return
        for btn in self._command_queue.findChildren(_Btn):
            if btn.property("testid") == testid:
                btn.click()
                return

    def _build_queue_toggles_column(self) -> QWidget:
        """Coluna irma de output-toolbar-test-mode, posicionada a esquerda dela.

        Aloja queue-count-toggles-row (reparenteado de metrics_bar — widget
        orfao). O antigo terminal-engine-toggle ("1-pyte") foi removido em
        2026-05-19; pyte virou T3 controlado pelo arrow no label bar do
        terminal-workspace-splitter.
        """
        from PySide6.QtWidgets import QBoxLayout, QVBoxLayout

        column = QWidget()
        column.setObjectName("OutputToolbarQueueToggles")
        column.setProperty("testid", "output-toolbar-queue-toggles")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(
            "QWidget#OutputToolbarQueueToggles { background-color: transparent;"
            "  border: none; }"
        )
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(6, 6, 6, 6)
        col_layout.setSpacing(6)

        # queue-count-toggles-row (reparent de metrics_bar — widget orfao)
        toggles_row = getattr(self._metrics_bar, "_queue_count_toggles_row", None)
        if toggles_row is not None:
            toggles_row.setParent(column)
            toggles_layout = toggles_row.layout()
            if isinstance(toggles_layout, QBoxLayout):
                toggles_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            col_layout.addWidget(
                toggles_row, alignment=Qt.AlignmentFlag.AlignHCenter,
            )

        col_layout.addStretch(1)
        return column

    def _on_test_mode_button_toggled(self, checked: bool) -> None:
        """Resolve o modo ativo, mantem exclusividade manual (no max 1 checado)
        e emite `datatest_mode_changed`.

        Comportamento radio-like:
        - Ativar um botao desliga os outros dois.
        - Re-click no checado desliga (modo "off").
        """
        if self._test_mode_syncing:
            return
        sender = self.sender()
        self._test_mode_syncing = True
        try:
            if checked:
                # Desligar os outros dois.
                for btn in self._test_mode_buttons.values():
                    if btn is not sender and btn.isChecked():
                        btn.setChecked(False)
        finally:
            self._test_mode_syncing = False

        mode = "off"
        for key, btn in self._test_mode_buttons.items():
            if btn.isChecked():
                mode = key
                break
        signal_bus.datatest_mode_changed.emit(mode)

    def _send_testid_probe_to_selected_terminal(self, testid: str) -> None:
        """Envia `data-testid="..."` + backspace para o(s) terminal(is) roteado(s).

        Reusa `_publish_to_terminal` para respeitar `terminal-route-toggles`
        e transferir foco para o terminal com prioridade configurada.
        """
        payload = f'data-testid="{testid}"\x08'
        self._publish_to_terminal(payload)

    _PROMPT_CATEGORIES: dict[str, str] = {
        "mcp-test": "Ops",
        "online-review": "Review",
        "next-module": "Build",
        "workflow-rules": "Plan",
        "progress": "Plan",
        "pending-actions-sweep": "Ops",
        "memory-decay-refresh": "Ops",
        "zero-rules-module-audit": "Review",
        "dcp-coherence-triage": "Review",
        "codex-hardening": "Review",
        "pdca-task-recovery": "Ops",
        "study-tasklist-codex": "Study",
        "turn-green": "Ops",
        "plan-vs-loop-coverage": "Review",
        "create-agent": "Build",
        "analista-trajeto-delegador": "Plan",
        "generated-command-list-comparison-whit-rules": "Review",
    }

    @staticmethod
    def _infer_prompt_category(label: str, path: str, description: str = "") -> str:
        """Inferencia conservadora para prompts fora do mapa explicito."""
        haystack = " ".join((label, path, description)).lower()

        def _has(*keys: str) -> bool:
            return any(k in haystack for k in keys)

        if _has("study", "estudo", "tasklist-codex"):
            return "Study"
        if _has(
            "review", "audit", "triage", "coherence", "zero", "hardening",
            "coverage", "compar", "revis", "qa",
        ):
            return "Review"
        if _has("next-module", "build", "module", "task", "implant", "deleg"):
            return "Build"
        if _has("plan", "workflow", "rules", "progress", "pdca", "trajeto"):
            return "Plan"
        if _has("mcp", "memory", "pending", "sweep", "turn-green", "listener"):
            return "Ops"
        return PROMPT_FILTER_DEFAULT

    def _prompt_category(self, label: str, path: str, description: str = "") -> str:
        slug = (
            Path(path).stem
            if path
            else re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        )
        category = self._PROMPT_CATEGORIES.get(slug) or self._infer_prompt_category(
            label, path, description
        )
        if category not in PROMPT_FILTER_CATEGORIES:
            category = PROMPT_FILTER_DEFAULT
        return category

    @staticmethod
    def _prompt_label_for_discovered_file(path: Path, fallback: str) -> str:
        """Label para prompts descobertos pelo watcher/reconciliacao.

        Se o .md tiver frontmatter com `label`, `title` ou `name`, respeita esse
        valor. Isso preserva labels intencionais como `create-agent` mesmo quando
        QSettings antigo nao tem a entry default nova.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return fallback
        if not text.startswith("---"):
            return fallback
        parts = text.split("---", 2)
        if len(parts) < 3:
            return fallback
        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return fallback
        if not isinstance(fm, dict):
            return fallback
        for key in ("label", "title", "name"):
            value = str(fm.get(key) or "").strip()
            if value:
                return value
        return fallback

    def _prompt_description(self, label: str, path: str, description: str = "") -> str:
        """Resumo curto para tooltip do botao de prompt."""
        desc = (description or "").strip()
        if not desc and path:
            prompt_path = Path(path)
            if not prompt_path.is_absolute():
                prompt_path = self._systemforge_root() / prompt_path
            try:
                text = prompt_path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            desc = self._summarize_prompt_markdown(text)
        if not desc:
            desc = f"Executa o prompt configurado para {label}."
        return desc

    @staticmethod
    def _summarize_prompt_markdown(text: str) -> str:
        """Extrai uma linha util de um arquivo .md para tooltip."""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1])
                except yaml.YAMLError:
                    fm = None
                if isinstance(fm, dict):
                    for key in ("description", "summary", "title", "name"):
                        value = str(fm.get(key) or "").strip()
                        if value:
                            return MainWindow._clean_prompt_summary(value)
                text = parts[2]

        lines = [line.strip() for line in text.splitlines()]
        lines = [
            line for line in lines
            if line and not line.startswith("```") and not line.startswith("---")
        ]
        if not lines:
            return ""

        for line in lines:
            normalized = line.rstrip(":").lower()
            if normalized in {"objetivo", "tarefa", "contexto"}:
                continue
            return MainWindow._clean_prompt_summary(line)
        return ""

    @staticmethod
    def _clean_prompt_summary(text: str) -> str:
        text = re.sub(r"^[#>*\-\d.\s]+", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        return text

    def _on_prompt_btn_clicked(self, idx: int) -> None:
        """Handler dos botoes da sub-aba prompts.

        Constroi a mensagem como "<base_prompt> <path>" e publica no terminal
        alvo (T1/T2) via _publish_to_terminal. NAO le o conteudo do .md —
        o Claude na outra ponta e quem le.
        """
        if idx >= len(self._prompt_entries):
            return
        entry = self._prompt_entries[idx]
        path = (entry.get("path") or "").strip()
        if not path:
            signal_bus.toast_requested.emit(
                "Entrada de prompt sem path. Configure via engrenagem.", "warning",
            )
            return
        import os as _os
        # Verificar existencia do arquivo. Os paths das entries sao relativos a
        # raiz do repo SystemForge (ex.: "ai-forge/custom-prompts/..."), NAO ao
        # project_dir do projeto ativo. Resolver contra _systemforge_root()
        # (mesma raiz usada pela reconciliacao de boot e pelo watcher acima);
        # resolver contra _project_dir gerava "Arquivo de prompt nao encontrado"
        # sempre que um projeto estava ativo (repo-root off-by-one).
        _abs = path if _os.path.isabs(path) else str(
            self._systemforge_root() / path
        )
        if not _os.path.exists(_abs):
            signal_bus.toast_requested.emit(
                f"Arquivo de prompt nao encontrado: {path}", "warning",
            )
            return
        msg = f"{self._prompt_base} {path}"
        self._publish_to_terminal(msg)

    def _resolve_repo_rules_dir(self) -> str | None:
        """Resolve `{workspace_root}/rules` do project.json ativo.

        Retorna None e emite toast (Zero Silencio) quando nenhum projeto esta
        carregado ou `workspace_root` esta vazio — NUNCA devolve path vazio.
        Mesmo contrato de guarda de `_on_repo_rules_path`/`_on_ws_rules_path`.
        """
        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit(
                "workspace_root indisponivel: nenhum projeto carregado."
                " Selecione o project.json via queue-btn-json-path.",
                "warning",
            )
            return None
        ws = (app_state.config.workspace_root or "").strip()
        if not ws:
            signal_bus.toast_requested.emit(
                "workspace_root nao configurado em project.json", "warning",
            )
            return None
        return f"{ws.rstrip('/')}/rules"

    def _on_reviewer_prompt(self) -> None:
        """Handler do botao 'reviewer' (PROMPTS/Review): cola um prompt de
        revisao do contexto desta conversa contra as regras do repo-alvo em
        `{workspace_root}/rules` via persona `specific-reviewer`. Guard de
        workspace_root ausente (no-op + toast) herdado de _resolve_repo_rules_dir.
        """
        rules_dir = self._resolve_repo_rules_dir()
        if not rules_dir:
            return
        prompt = (
            "Voce e o 'specific-reviewer' (regras canonicas em "
            "ai-forge/MCP/agents/specific-reviewer.md; leia integralmente antes "
            "de responder). Revise a implementacao e o texto discutidos nesta "
            f"conversa contra as regras vivas do repositorio-alvo em {rules_dir}. "
            "Para cada ponto, classifique conforme|violacao|conflito|nao-coberto "
            "com evidencia concreta (path + linha ou trecho literal). Marque "
            "hipotese/inferencia quando nao houver leitura direta. Nao altere o "
            "escopo; apenas revise e recomende correcoes."
        )
        self._publish_insertion_llm_aware(prompt)

    def _on_create_rule_prompt(self) -> None:
        """Handler do botao 'create rule' (PROMPTS/Ops): cola um prompt pedindo
        a criacao de um novo arquivo de regras em `{workspace_root}/rules` do
        repo-alvo (nunca `ai-forge/rules/`). Guard de workspace_root ausente
        (no-op + toast) herdado de _resolve_repo_rules_dir.
        """
        rules_dir = self._resolve_repo_rules_dir()
        if not rules_dir:
            return
        prompt = (
            f"Crie em {rules_dir} um novo arquivo de regras referente ao contexto "
            "que pedi para estudar agora, de forma estruturada e claude-friendly "
            "como os outros arquivos da pasta de regras do repositorio-alvo. O "
            f"destino e {rules_dir} (do project.json ativo), NAO ai-forge/rules/."
        )
        self._publish_insertion_llm_aware(prompt)

    def _populate_header_prompts_subtab(self) -> list[QPushButton]:
        """Constroi os botoes da sub-aba 'prompts' a partir de self._prompt_entries."""
        def _prompt_btn(
            label: str, testid: str, bg: str, hover: str,
            description: str, category: str,
        ) -> QPushButton:
            b = QPushButton(label)
            b.setProperty("testid", testid)
            b.setProperty("prompt_category", category)
            b.setProperty("prompt_description", description)
            b.setFixedHeight(32)
            b.setMinimumWidth(70)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(description)
            b.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {hover}; }}"
            )
            _PromptTooltipFilter(b, description, b)
            return b

        btns = []
        for _i, entry in enumerate(self._prompt_entries):
            label = entry["label"] or f"Prompt {_i+1}"
            description = self._prompt_description(
                label, entry.get("path", ""), entry.get("description", "")
            )
            category = self._prompt_category(
                label, entry.get("path", ""), description
            )
            b = _prompt_btn(
                label,
                entry["testid"],
                entry["bg"],
                entry["hover"],
                description,
                category,
            )
            b.clicked.connect(
                lambda _c=False, idx=_i: self._on_prompt_btn_clicked(idx)
            )
            btns.append(b)

        # Botao fixo 'executar-tasks': cola um prompt literal de loop de
        # execucao de tasklist com revisao adversarial via Codex. Diferente
        # dos botoes de entrada acima (modelo label+path, que publicam
        # base_prompt + caminho do .md), este publica o prompt cru direto no
        # terminal via _publish_to_terminal (roteamento T1/T2/T3).
        _EXECUTAR_TASKS_PROMPT = (
            "/goal execute o tasklist, faça uma task, chame o "
            "/mcp:codex para revisão adversarial, corrija o que for "
            "sugerido e for congruente, marque a task como concluida no "
            "progress.md e parte para a próxima. execute até acabar a "
            "tasklist."
        )
        _exec_tasks_btn = QPushButton("executar-tasks")
        _exec_tasks_btn.setProperty("testid", "queue-btn-executar-tasks")
        _exec_tasks_desc = (
            "Cola no terminal um prompt de loop: executa o tasklist task a "
            "task, revisao adversarial via /mcp:codex, corrige o que for "
            "congruente, marca no progress.md e segue ate acabar."
        )
        _exec_tasks_btn.setProperty("prompt_category", "Build")
        _exec_tasks_btn.setProperty("prompt_description", _exec_tasks_desc)
        _exec_tasks_btn.setFixedHeight(32)
        _exec_tasks_btn.setMinimumWidth(90)
        _exec_tasks_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _exec_tasks_btn.setToolTip(_exec_tasks_desc)
        _PromptTooltipFilter(_exec_tasks_btn, _exec_tasks_desc, _exec_tasks_btn)
        _exec_tasks_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
        )
        _exec_tasks_btn.clicked.connect(
            lambda _c=False: self._publish_insertion_llm_aware(_EXECUTAR_TASKS_PROMPT)
        )
        btns.append(_exec_tasks_btn)

        # Botao fixo 'reviewer' (filtro Review): cola um prompt de revisao do
        # contexto desta conversa contra as regras do repo-alvo
        # ({workspace_root}/rules) via persona specific-reviewer. Guard de
        # workspace_root em _on_reviewer_prompt (no-op + toast se ausente).
        _reviewer_btn = QPushButton("reviewer")
        _reviewer_btn.setProperty("testid", "queue-btn-reviewer")
        _reviewer_desc = (
            "Cola um prompt pedindo revisao do contexto desta conversa contra as "
            "regras do repo-alvo ({workspace_root}/rules) via specific-reviewer.\n"
            "Sem projeto/workspace_root carregado: toast de aviso, nada e colado."
        )
        _reviewer_btn.setProperty("prompt_category", "Review")
        _reviewer_btn.setProperty("prompt_description", _reviewer_desc)
        _reviewer_btn.setFixedHeight(32)
        _reviewer_btn.setMinimumWidth(90)
        _reviewer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _reviewer_btn.setToolTip(_reviewer_desc)
        _PromptTooltipFilter(_reviewer_btn, _reviewer_desc, _reviewer_btn)
        _reviewer_btn.setStyleSheet(
            "QPushButton { background-color: #7C3AED; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { background-color: #6D28D9; }"
            "QPushButton:pressed { background-color: #5B21B6; }"
        )
        _reviewer_btn.clicked.connect(lambda _c=False: self._on_reviewer_prompt())
        btns.append(_reviewer_btn)

        # Botao fixo 'create rule' (filtro Ops): cola um prompt pedindo a criacao
        # de um novo arquivo de regras em {workspace_root}/rules do repo-alvo
        # (nunca ai-forge/rules/). Guard de workspace_root em
        # _on_create_rule_prompt (no-op + toast se ausente).
        _create_rule_btn = QPushButton("create rule")
        _create_rule_btn.setProperty("testid", "queue-btn-create-rule")
        _create_rule_desc = (
            "Cola um prompt pedindo a criacao de um novo arquivo de regras em "
            "{workspace_root}/rules do repo-alvo (nao ai-forge/rules/).\n"
            "Sem projeto/workspace_root carregado: toast de aviso, nada e colado."
        )
        _create_rule_btn.setProperty("prompt_category", "Ops")
        _create_rule_btn.setProperty("prompt_description", _create_rule_desc)
        _create_rule_btn.setFixedHeight(32)
        _create_rule_btn.setMinimumWidth(90)
        _create_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _create_rule_btn.setToolTip(_create_rule_desc)
        _PromptTooltipFilter(_create_rule_btn, _create_rule_desc, _create_rule_btn)
        _create_rule_btn.setStyleSheet(
            "QPushButton { background-color: #0891B2; color: #FAFAFA;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { background-color: #0E7490; }"
            "QPushButton:pressed { background-color: #155E75; }"
        )
        _create_rule_btn.clicked.connect(lambda _c=False: self._on_create_rule_prompt())
        btns.append(_create_rule_btn)

        # Botao especial para criar novos prompts seguindo as regras
        _add_btn = QPushButton("+ Add prompt")
        _add_btn.setProperty("testid", "queue-btn-add-prompt")
        _add_btn.setFixedHeight(32)
        _add_btn.setMinimumWidth(90)
        _add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _add_prompt_desc = (
            "Envia meta-prompt ao terminal guiando a criacao de um novo prompt\n"
            "seguindo ai-forge/rules/prompt-creation-rules.md.\n"
            "Ao criar o .md na pasta, o botao aparece automaticamente."
        )
        _add_btn.setProperty("prompt_description", _add_prompt_desc)
        _add_btn.setToolTip(_add_prompt_desc)
        _PromptTooltipFilter(_add_btn, _add_prompt_desc, _add_btn)
        _add_btn.setStyleSheet(
            "QPushButton { background-color: #18181B; color: #A1A1AA;"
            "  border: 1px dashed #52525B; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; padding: 0 8px; }"
            "QPushButton:hover { background-color: #27272A; border-color: #71717A;"
            "  color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #3F3F46; }"
        )
        _add_btn.clicked.connect(self._on_add_prompt_btn_clicked)
        btns.append(_add_btn)

        return btns

    def _open_prompts_config_dialog(self) -> None:
        """Abre modal de configuracao de prompts (label+path+base_prompt).

        Submit -> atualiza self._prompt_entries + self._prompt_base, persiste
        em QSettings, reconstroi sub-aba prompts.
        """
        import json as _json

        from PySide6.QtWidgets import QDialog
        dlg = PromptsConfigDialog(self._prompt_entries, self._prompt_base, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        base_prompt, new_entries = dlg.collect()

        import re as _re
        def _slug(lbl: str) -> str:
            return _re.sub(r"[^a-z0-9]+", "-", lbl.lower()).strip("-") or "prompt"

        _PALETTE = [
            ("#0D9488", "#0F766E"), ("#EA580C", "#C2410C"),
            ("#7C3AED", "#6D28D9"), ("#0891B2", "#0E7490"),
            ("#10B981", "#059669"), ("#F59E0B", "#D97706"),
            ("#EF4444", "#DC2626"), ("#8B5CF6", "#7C3AED"),
        ]

        self._prompt_base = base_prompt
        self._prompt_entries = []
        for _i, (lbl, path, desc) in enumerate(new_entries):
            _bg, _hv = _PALETTE[_i % len(_PALETTE)]
            self._prompt_entries.append({
                "label": lbl,
                "path": path,
                "description": desc,
                "testid": f"output-btn-prompt-{_slug(lbl)}",
                "bg": _bg,
                "hover": _hv,
            })

        _pset = QSettings("systemForge", "workflow-app")
        _pset.setValue("prompts_row/base_prompt", self._prompt_base)
        _entries_simple = [
            {"label": e["label"], "path": e["path"], "description": e.get("description", "")}
            for e in self._prompt_entries
        ]
        _pset.setValue("prompts_row/entries", _json.dumps(_entries_simple))

        # Reconstruir sub-aba prompts. gear de prompts sempre como ultimo widget
        # do flow (vive dentro da sub-aba). asq-user nao entra aqui (migrou p/ CMD).
        _new_btns = (
            self._populate_header_prompts_subtab()
            + [self._prompts_config_gear]
        )
        self._command_queue.populate_prompts_subtab(_new_btns)
        signal_bus.toast_requested.emit("Prompts atualizados.", "info")

    def _on_add_prompt_btn_clicked(self) -> None:
        """Envia meta-prompt ao terminal guiando criacao de novo prompt.

        O prompt instrui o Claude a: ler as regras de criacao, entender o que
        o usuario quer e criar um .md em ai-forge/custom-prompts/prompts-subtab/.
        O QFileSystemWatcher detecta o novo arquivo e adiciona o botao automaticamente.
        """
        _rules_path = "ai-forge/rules/prompt-creation-rules.md"
        _prompts_dir = "ai-forge/custom-prompts/prompts-subtab"
        _meta_prompt = (
            f"Leia o arquivo {_rules_path} e siga rigorosamente as regras de criacao "
            f"de prompts descritas nele. Com base no que vou descrever a seguir, crie "
            f"um novo arquivo de prompt em {_prompts_dir}/<slug>.md — o slug deve ser "
            f"kebab-case descritivo. O workflow-app detectara automaticamente o novo "
            f"arquivo e adicionara o botao na sub-aba prompts. "
            f"Me diga agora o que voce quer que o prompt faca:"
        )
        self._publish_to_terminal(_meta_prompt)
        signal_bus.toast_requested.emit(
            "Meta-prompt 'Add prompt' enviado ao terminal.", "info"
        )

    def _on_prompts_dir_changed(self, path: str) -> None:
        """Auto-detecta novos .md criados em prompts-subtab e adiciona como botoes."""
        import json as _json
        import os as _os
        import re as _re

        _existing_paths = {e.get("path", "") for e in self._prompt_entries}
        _new = []
        if _os.path.isdir(path):
            for _fname in sorted(_os.listdir(path)):
                if not _fname.endswith(".md") or _fname in ("README.md",):
                    continue
                _rel = f"ai-forge/custom-prompts/prompts-subtab/{_fname}"
                if _rel not in _existing_paths:
                    _fallback_label = (
                        _fname.replace("-", " ").replace(".md", "").title()
                    )
                    _label = self._prompt_label_for_discovered_file(
                        Path(path) / _fname, _fallback_label
                    )
                    _new.append({"label": _label, "path": _rel, "description": ""})

        if not _new:
            return

        _PALETTE = [
            ("#0D9488", "#0F766E"), ("#EA580C", "#C2410C"),
            ("#7C3AED", "#6D28D9"), ("#0891B2", "#0E7490"),
            ("#10B981", "#059669"), ("#F59E0B", "#D97706"),
            ("#EF4444", "#DC2626"), ("#8B5CF6", "#7C3AED"),
        ]

        def _slug(lbl: str) -> str:
            return _re.sub(r"[^a-z0-9]+", "-", lbl.lower()).strip("-") or "prompt"

        _start = len(self._prompt_entries)
        for _i, _ne in enumerate(_new):
            _lbl = _ne["label"]
            _bg, _hv = _PALETTE[(_start + _i) % len(_PALETTE)]
            self._prompt_entries.append({
                "label": _lbl,
                "path": _ne["path"],
                "description": "",
                "testid": f"output-btn-prompt-{_slug(_lbl)}",
                "bg": _bg,
                "hover": _hv,
            })

        _pset = QSettings("systemForge", "workflow-app")
        _pset.setValue(
            "prompts_row/entries",
            _json.dumps([
                {"label": e["label"], "path": e["path"], "description": e.get("description", "")}
                for e in self._prompt_entries
            ]),
        )

        # asq-user nao entra aqui (migrou p/ CMD); gear sempre por ultimo no flow.
        _new_btns = (
            self._populate_header_prompts_subtab()
            + [self._prompts_config_gear]
        )
        self._command_queue.populate_prompts_subtab(_new_btns)
        signal_bus.toast_requested.emit(
            f"{len(_new)} novo(s) prompt(s) detectado(s) e adicionado(s).", "info"
        )

    # ── Workspace dispatch helpers (T2=pyte/Kimi, T3=pyte/Codex) ────── #
    def _xterm_inject_text(self, text: str, with_enter: bool = False) -> bool:
        """Injeta `text` diretamente no shell pyte do T3 (Codex).

        Retorna True quando o shell esta vivo e recebeu os bytes; False se o
        painel T3 nao existe ou o shell nao iniciou. Quando `with_enter=True`,
        arma a janela de early-exit (Camada 3) do painel e agenda um \r como
        keypress separado apos 1000ms — Codex/Ink engolem um Enter que chega
        colado ao paste. (Nome historico `_xterm_inject_text` preservado; o
        engine agora e pyte, igual a T1/T2.)
        """
        if not hasattr(self, "_workspace_panel_xterm"):
            return False
        panel = self._workspace_panel_xterm
        shell = getattr(panel, "_shell", None)
        if shell is None:
            return False
        try:
            ensure_started = getattr(panel, "ensure_shell_started", None)
            if callable(ensure_started):
                ensure_started()
            if getattr(shell, "_master_fd", None) is None:
                logger.warning("T3 (Codex) shell is not started; injection skipped")
                return False
            shell.send_raw(text.encode("utf-8", errors="replace"))
            if with_enter:
                # Arma o early-exit watcher do painel para este dispatch real:
                # a rota imperativa nao passa por OutputPanel._run_shell_command,
                # entao sem isto o _dispatch_ts nunca seria setado e um Codex que
                # morre cedo (auth/credit) ficaria verde-silencioso. Helpers sao
                # isentos dentro de arm_dispatch_window.
                arm = getattr(panel, "arm_dispatch_window", None)
                if callable(arm):
                    arm(text)
                # Codex/Ink can swallow Enter when it lands too close to paste.
                QTimer.singleShot(1000, lambda: shell.send_raw(b"\r"))
        except Exception:  # noqa: BLE001
            logger.exception("T3 (Codex) shell.send_raw failed")
            return False
        return True

    def _dispatch_workspace_text(self, text: str, with_enter: bool = False) -> None:
        """Helper para emissores que historicamente miravam o pyte direto
        (label-bar WORKSPACE/SystemForge/cd/mention + notes-bar ↑).

        Politica: T2 (pyte/Kimi) e o terminal sempre visivel no workspace e
        recebe sempre. T3 (pyte/Codex) so recebe quando o operador o expandiu
        pelo arrow do label bar (Zero Silencio: nao injeta em terminal
        colapsado/invisivel).
        """
        # T2 (pyte): sempre visivel -> recebe sempre.
        if with_enter:
            signal_bus.run_command_in_workspace_terminal.emit(text)
        else:
            signal_bus.paste_text_in_workspace_terminal.emit(text)
        # T3 (pyte/Codex): so quando expandido.
        if getattr(self, "_t3_visible", False):
            self._xterm_inject_text(text, with_enter=with_enter)

    def _publish_to_terminal(self, text: str) -> None:
        """Roteia `text` conforme estado dos checkboxes T1/T2/T3 e Notes T1/T2.

        Eixo terminal (linha 1): T1/T2/T3 publicam diretamente nos terminais.
        Eixo notes   (linha 2): Notes T1/T2 desviam o texto para o clipboard
        em vez de publicar no terminal, para edicao qualificada antes do envio.

        Nenhum marcado = no-op silencioso (Zero Estados Indefinidos).
        """
        t1 = bool(self._chk_route_t1.isChecked()) if hasattr(self, "_chk_route_t1") else True
        t2 = bool(self._chk_route_t2.isChecked()) if hasattr(self, "_chk_route_t2") else False
        t3 = bool(self._chk_route_t3.isChecked()) if hasattr(self, "_chk_route_t3") else False
        n1 = bool(self._chk_notes_t1.isChecked()) if hasattr(self, "_chk_notes_t1") else False
        n2 = bool(self._chk_notes_t2.isChecked()) if hasattr(self, "_chk_notes_t2") else False
        if not (t1 or t2 or t3):
            return
        # Notes: copia para clipboard em vez de publicar no terminal.
        if (t1 and n1) or (t2 and n2):
            from PySide6.QtWidgets import QApplication as _QApp
            _QApp.clipboard().setText(text)
            _notes_label = " + ".join(
                filter(None, ["T1" if (t1 and n1) else "", "T2" if (t2 and n2) else ""])
            )
            signal_bus.toast_requested.emit(
                f"Notas ({_notes_label}): texto copiado para clipboard.", "info"
            )
        if t1 and not n1:
            signal_bus.paste_text_in_terminal.emit(text)
        if t2 and not n2:
            signal_bus.paste_text_in_workspace_terminal.emit(text)
        if t3:
            self._xterm_inject_text(text, with_enter=False)
        # Focus priority: T1 > T2 > T3 (apenas para roteamento direto ao terminal).
        if t1 and not n1:
            signal_bus.focus_interactive_terminal.emit()
        elif t2 and not n2:
            try:
                self._workspace_panel._terminal.setFocus()
            except AttributeError:
                pass
        elif t3 and hasattr(self, "_workspace_panel_xterm"):
            try:
                self._workspace_panel_xterm._terminal.setFocus()
            except AttributeError:
                pass

    def _publish_insertion_llm_aware(self, text: str) -> bool:
        """Publica uma insercao LLM-aware: renderiza o payload para o LLM de
        destino ANTES de colar (paste/no-Enter), reusando o renderer puro
        `CommandQueueWidget.render_for_llm`. Separa renderizacao (no widget da
        fila) de transporte (aqui), sem tocar na fila.

        Contrato (blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing.md
        §5.1/§8.2/§9.3/§10):
        - payload neutro (path, texto livre, `/clear`) -> delega ao
          `_publish_to_terminal` (passthrough byte-identico ao legado);
        - payload LLM-especifico (slash-command/custom-prompt directive, exceto
          `/clear`) -> corte Phase-1: so T1 (+ Notes T1). Se T2/T3 tambem marcados,
          aborta com toast (fan-out heterogeneo nao suportado neste MVP, §9.3).
          Renderiza para o Main LLM do T1 e cola sem Enter; em `abort_reason`,
          toast e nada publicado (Zero Silencio).

        NUNCA chama `_on_run_command`, `_dispatch_*`, marca item de fila, usa
        `run_command_in_*` ou prefixa `WF_CHANNEL_OVERRIDE=` (§8.2/§11.1).
        Retorna True quando publicou (ou copiou via Notes), False em abort/no-op.
        """
        cq = self._command_queue
        head = cq._command_head(text)
        is_llm_specific = head.startswith("/") and head != "/clear"
        if not is_llm_specific:
            # path / texto livre / /clear -> comportamento legado (passthrough).
            self._publish_to_terminal(text)
            return True

        t1 = bool(self._chk_route_t1.isChecked()) if hasattr(self, "_chk_route_t1") else True
        t2 = bool(self._chk_route_t2.isChecked()) if hasattr(self, "_chk_route_t2") else False
        t3 = bool(self._chk_route_t3.isChecked()) if hasattr(self, "_chk_route_t3") else False
        n1 = bool(self._chk_notes_t1.isChecked()) if hasattr(self, "_chk_notes_t1") else False
        n2 = bool(self._chk_notes_t2.isChecked()) if hasattr(self, "_chk_notes_t2") else False
        if not (t1 or t2 or t3):
            return False  # nenhum destino -> no-op (igual _publish_to_terminal)

        # Notes D6 (§10): Notes T1 + Notes T2 simultaneos para payload LLM-especifico
        # -> abort com toast. (No corte Phase-1 isto tambem cai na guarda de fan-out
        # abaixo, ja que exige T2 marcado; mantido explicito para a regra valer.)
        if t1 and t2 and n1 and n2:
            signal_bus.toast_requested.emit(
                "Notes multiplo nao suportado para payload LLM-especifico.", "warning",
            )
            return False

        # Guarda Phase-1 (§9.3): fan-out heterogeneo (T2/T3) ainda nao suportado.
        if t2 or t3:
            signal_bus.toast_requested.emit(
                "Fan-out heterogeneo (T2/T3) ainda nao suportado para payload "
                "LLM-especifico — deixe apenas T1 marcado.", "warning",
            )
            return False

        # T1 unico: renderiza para o Main LLM efetivo do T1.
        llm = cq.current_main_llm()
        rendered = cq.render_for_llm(
            text, llm, listener_channel="interactive", mode="insert",
        )
        if rendered.abort_reason or rendered.text is None:
            signal_bus.toast_requested.emit(
                "Insercao LLM-aware abortada: "
                f"{rendered.abort_reason or 'nada a publicar'}.",
                "warning",
            )
            return False

        payload = rendered.text
        if t1 and n1:
            # Notes T1 (D6): clipboard recebe o texto RENDERIZADO para o destino.
            QApplication.clipboard().setText(payload)
            signal_bus.toast_requested.emit(
                "Notas (T1): texto renderizado copiado para clipboard.", "info",
            )
            return True
        # Cola no T1 SEM Enter (semantica de insercao), foca e da feedback.
        QApplication.clipboard().setText(payload)
        signal_bus.paste_text_in_terminal.emit(payload)
        signal_bus.focus_interactive_terminal.emit()
        signal_bus.toast_requested.emit(
            f"Insercao LLM-aware ({llm}) publicada no T1.", "info",
        )
        return True

    def _populate_header_actions(self) -> list[QPushButton]:
        """Constroi botoes da actions-tab: JSON, WS, MCPs Claude-side (laranja),
        skills Kimi-side (azul), skills Codex-side (roxo) e asq-user.

        Refactor 2026-05-15 output-toolbar-left consolidation:
        Brief/Docs descartados. Removido o fallback para `_header_actions_layout`
        do MetricsBar; unico consumer agora e CommandQueueHeader.populate_actions_tab().
        Retorna a lista de widgets em ordem; quem instala decide o layout.

        Handlers: JSON/WS resolvem via slots tipados de `app_state` + clipboard +
        `_publish_to_terminal`; demais emitem o comando cru via
        `_publish_to_terminal` (roteamento T1/T2).
        """
        def _make_action_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _on_json_path() -> None:
            project_cfg = app_state.project_config
            if not project_cfg:
                signal_bus.toast_requested.emit(
                    "Nenhum projeto carregado. Selecione um project.json no anexo project.",
                    "warning",
                )
                return
            abs_config = project_cfg.config_path
            project_dir = str(project_cfg.project_dir)
            try:
                rel = os.path.relpath(abs_config, project_dir)
            except ValueError:
                rel = abs_config
            QApplication.clipboard().setText(rel)
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(rel)
            signal_bus.toast_requested.emit(
                "Caminho JSON copiado e digitado no terminal.", "info",
            )

        def _on_ws_path() -> None:
            project_cfg = app_state.project_config
            if not project_cfg:
                signal_bus.toast_requested.emit(
                    "workspace_root indisponivel: nenhum projeto carregado."
                    " Selecione o project.json via queue-btn-json-path.",
                    "warning",
                )
                return
            ws = project_cfg.workspace_root
            QApplication.clipboard().setText(ws)
            # Task 6 (loop 05-13-workflow-app-layout-2): roteamento T1/T2.
            self._publish_to_terminal(ws)
            signal_bus.toast_requested.emit(
                "workspace_root copiado e digitado no terminal.", "info",
            )

        def _on_loop_path() -> None:
            loop_cfg = app_state.loop_config
            if not loop_cfg:
                signal_bus.toast_requested.emit(
                    "Loop anexado ausente: carregue um _LOOP-CONFIG.json para"
                    " usar queue-btn-loop-path.",
                    "warning",
                )
                return
            loop_path = str(loop_cfg.config_path or "")
            if not loop_path:
                signal_bus.toast_requested.emit(
                    "Loop anexado sem caminho. Recarregue o _LOOP-CONFIG.json",
                    "warning",
                )
                return
            QApplication.clipboard().setText(loop_path)
            self._publish_to_terminal(loop_path)
            signal_bus.toast_requested.emit(
                "Loop path copiado e digitado no terminal.", "info",
            )

        def _on_brainstorm_path() -> None:
            md_path = (self._brainstorm_md_path or "").strip()
            if not md_path:
                signal_bus.toast_requested.emit(
                    "Brainstorm .md nao carregado: selecione um arquivo no"
                    " brainstorm-md-picker antes de usar queue-btn-brainstorm-path.",
                    "warning",
                )
                return
            QApplication.clipboard().setText(md_path)
            self._publish_to_terminal(md_path)
            signal_bus.toast_requested.emit(
                "Brainstorm path copiado e digitado no terminal.", "info",
            )

        def _paste_cmd(cmd: str):
            def _h() -> None:
                self._publish_to_terminal(cmd)
            return _h

        json_btn = _make_action_btn(
            "JSON", "queue-btn-json-path",
            "#D97706", "#B45309", "#92400E",
            "Copia o caminho do project.json\ne digita no terminal automaticamente",
        )
        json_btn.clicked.connect(_on_json_path)

        ws_btn = _make_action_btn(
            "WS", "queue-btn-ws-path",
            "#059669", "#047857", "#065F46",
            "Copia o workspace_root do projeto\ne digita no terminal automaticamente",
        )
        ws_btn.clicked.connect(_on_ws_path)

        loop_btn = _make_action_btn(
            "Loop", "queue-btn-loop-path",
            "#0EA5E9", "#0284C7", "#0369A1",
            "Copia o path do _LOOP-CONFIG.json do anexo loop\ne digita no terminal automaticamente",
        )
        loop_btn.clicked.connect(_on_loop_path)

        brainstorm_btn = _make_action_btn(
            "Brainstorm", "queue-btn-brainstorm-path",
            "#7C3AED", "#6D28D9", "#5B21B6",
            "Copia o path do .md selecionado em brainstorm\ne digita no terminal automaticamente",
        )
        brainstorm_btn.clicked.connect(_on_brainstorm_path)

        # Botoes da coluna MCP (output-toolbar-mcp): labels resumidos + cores
        # padronizadas por linha. Linha 1 (Anthropic laranja): MCPs Claude-side.
        # Linha 2 (azul): skills Kimi-side. Linha 3 (roxo): skills Codex-side.
        # Largura fixa apos reducao de label.
        _MCP_BTN_WIDTH = 58
        _ACTIONS_ROW_MIN_WIDTH = 64
        _ANTHROPIC_ORANGE = ("#CC785C", "#B8674E", "#A55A42")
        _MCP_BLUE = ("#2563EB", "#1D4ED8", "#1E40AF")
        _MCP_PURPLE = ("#7C3AED", "#6D28D9", "#5B21B6")

        mcp_codex_btn = _make_action_btn(
            "codex", "output-btn-mcp-codex",
            *_ANTHROPIC_ORANGE,
            "/mcp:codex \u2014 Pair programming com Codex MCP",
        )
        mcp_codex_btn.setFixedWidth(_MCP_BTN_WIDTH)
        mcp_codex_btn.clicked.connect(_paste_cmd("/mcp:codex"))

        mcp_kimi_btn = _make_action_btn(
            "kimi", "output-btn-mcp-kimi",
            *_ANTHROPIC_ORANGE,
            "/mcp:kimi \u2014 Persona-aware Kimi orchestrator",
        )
        mcp_kimi_btn.setFixedWidth(_MCP_BTN_WIDTH)
        mcp_kimi_btn.clicked.connect(_paste_cmd("/mcp:kimi"))

        double_mcp_btn = _make_action_btn(
            "dual", "output-btn-double-mcp",
            *_ANTHROPIC_ORANGE,
            "/mcp:dual \u2014 Co-execucao paralela Codex+Kimi",
        )
        double_mcp_btn.setFixedWidth(_MCP_BTN_WIDTH)
        double_mcp_btn.clicked.connect(_paste_cmd("/mcp:dual"))

        skill_claude_btn = _make_action_btn(
            "claude", "output-btn-skill-claude",
            *_MCP_PURPLE,
            "Codex: use skill-claude com saida JSON consultiva",
        )
        skill_claude_btn.setFixedWidth(_MCP_BTN_WIDTH)
        skill_claude_btn.clicked.connect(
            _paste_cmd("Use skill-claude. Output JSON. Prompt: ")
        )

        skill_kimi_btn = _make_action_btn(
            "kimi", "output-btn-skill-kimi",
            *_MCP_PURPLE,
            "Codex: use skill-kimi com saida JSON consultiva",
        )
        skill_kimi_btn.setFixedWidth(_MCP_BTN_WIDTH)
        skill_kimi_btn.clicked.connect(
            _paste_cmd("Use skill-kimi. Output JSON. Prompt: ")
        )

        skill_dual_btn = _make_action_btn(
            "dual", "output-btn-skill-dual",
            *_MCP_PURPLE,
            "Codex: use skill-dual para consulta Claude+Kimi com divergencia",
        )
        skill_dual_btn.setFixedWidth(_MCP_BTN_WIDTH)
        skill_dual_btn.clicked.connect(
            _paste_cmd("Use skill-dual. Output JSON. Mode: stereo. Prompt: ")
        )

        # Linha 2 (azul): Kimi-side — chama Claude, Codex ou ambos via skill.
        kimi_claude_btn = _make_action_btn(
            "claude", "output-btn-kimi-claude",
            *_MCP_BLUE,
            "Kimi: chama Claude como consultor externo via /skill:claude",
        )
        kimi_claude_btn.setFixedWidth(_MCP_BTN_WIDTH)
        kimi_claude_btn.clicked.connect(_paste_cmd("/skill:claude"))

        kimi_codex_btn = _make_action_btn(
            "codex", "output-btn-kimi-codex",
            *_MCP_BLUE,
            "Kimi: chama Codex como consultor externo via /skill:codex",
        )
        kimi_codex_btn.setFixedWidth(_MCP_BTN_WIDTH)
        kimi_codex_btn.clicked.connect(_paste_cmd("/skill:codex"))

        kimi_dual_btn = _make_action_btn(
            "dual", "output-btn-kimi-dual",
            *_MCP_BLUE,
            "Kimi: chama Claude+Codex em paralelo via /skill:dual",
        )
        kimi_dual_btn.setFixedWidth(_MCP_BTN_WIDTH)
        kimi_dual_btn.clicked.connect(_paste_cmd("/skill:dual"))

        asq_user_btn = _make_action_btn(
            "asq-user", "output-btn-asq-user",
            "#F59E0B", "#D97706", "#B45309",
            "/tools:auq-interview \u2014 Entrevista AUQ guiada",
        )
        asq_user_btn.setMinimumWidth(_ACTIONS_ROW_MIN_WIDTH)
        asq_user_btn.clicked.connect(
            lambda _c=False: self._publish_insertion_llm_aware("/tools:auq-interview")
        )

        return [
            json_btn,
            ws_btn,
            loop_btn,
            brainstorm_btn,
            mcp_codex_btn,
            mcp_kimi_btn,
            double_mcp_btn,
            kimi_claude_btn,
            kimi_codex_btn,
            kimi_dual_btn,
            skill_claude_btn,
            skill_kimi_btn,
            skill_dual_btn,
            asq_user_btn,
        ]

    def _populate_header_workflow_app(self) -> list[QPushButton]:
        """Constroi os botoes da row terminal-insertions-row-workflow-app
        (Parte 3 do request 2026-05-17): atalhos de path para os documentos
        canonicos do workflow-app + atalho 'add-rules' para o prompt de
        criacao de novos arquivos de regras (2026-05-17 follow-up).

        Cada botao cola um path/prompt literal no terminal via
        _publish_to_terminal — respeita terminal-route-toggles (T1/T2) e
        transfere foco conforme ai-forge/rules/workflow-app-terminal.md.
        """
        def _make_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _paste_path(path: str):
            def _h() -> None:
                QApplication.clipboard().setText(path)
                # _publish_to_terminal ja consulta terminal-route-toggles e
                # transfere foco — ver ai-forge/rules/workflow-app-terminal.md.
                self._publish_to_terminal(path)
                signal_bus.toast_requested.emit(
                    f"Path copiado e digitado no terminal: {path}", "info",
                )
            return _h

        workflow_app_btn = _make_btn(
            "Workflow App", "queue-btn-workflow-app-path",
            "#0EA5E9", "#0284C7", "#0369A1",
            "Cola o path ai-forge/workflow-app no terminal\n(respeita terminal-route-toggles)",
        )
        workflow_app_btn.clicked.connect(_paste_path("ai-forge/workflow-app"))

        ws_rules_btn = _make_btn(
            "ws-rules", "queue-btn-ws-rules-path",
            "#14B8A6", "#0D9488", "#0F766E",
            "Cola o path {workspace_root}/rules do projeto ativo no terminal\n"
            "(mesma origem do queue-btn-ws-path, com subpasta rules)",
        )
        ws_rules_btn.clicked.connect(self._on_ws_rules_path)

        dcp_rules_btn = _make_btn(
            "Dcp-list-rules", "queue-btn-dcp-command-list-rules-path",
            "#10B981", "#059669", "#047857",
            "Cola o path ai-forge/rules/dcp-cmd-list-build.md no terminal\n"
            "(regras de construcao do SPECIFIC-FLOW.json por module DCP)",
        )
        dcp_rules_btn.clicked.connect(_paste_path("ai-forge/rules/dcp-cmd-list-build.md"))

        meta_feeding_rules_btn = _make_btn(
            "Meta-feeding-rules", "queue-btn-dcp-meta-feeding-rules-path",
            "#22C55E", "#16A34A", "#15803D",
            "Cola o path ai-forge/rules/dcp-module-meta-feeding.md no terminal\n"
            "(upstream do filtro: como a MODULE-META alimenta a lista de comandos\n"
            "de cada module — schema canonico, produtores, gates, mapa campo->comando)",
        )
        meta_feeding_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/dcp-module-meta-feeding.md")
        )

        cmd_rules_btn = _make_btn(
            "Cmd-list-rules", "queue-btn-command-list-basic-rules-path",
            "#A855F7", "#9333EA", "#7E22CE",
            "Cola o path ai-forge/rules/workflow-app-command-lists.md no terminal\n"
            "(politica de /clear, /model, /effort + anti-redundancia)",
        )
        cmd_rules_btn.clicked.connect(_paste_path("ai-forge/rules/workflow-app-command-lists.md"))

        terminal_rules_btn = _make_btn(
            "Terminal-rules", "queue-btn-terminal-basic-rules-path",
            "#F97316", "#EA580C", "#C2410C",
            "Cola o path ai-forge/rules/workflow-app-terminal.md no terminal\n"
            "(roteamento via terminal-route-toggles + focus transfer)",
        )
        terminal_rules_btn.clicked.connect(_paste_path("ai-forge/rules/workflow-app-terminal.md"))

        listeners_rules_btn = _make_btn(
            "Listeners-rules", "queue-btn-listeners-rules-path",
            "#EF4444", "#DC2626", "#B91C1C",
            "Cola o path ai-forge/rules/workflow-app-listeners.md no terminal\n"
            "(3 estados visuais do dot: idle/busy/failed + dual-script-finalize)",
        )
        listeners_rules_btn.clicked.connect(_paste_path("ai-forge/rules/workflow-app-listeners.md"))

        # Relatorio de bug recorrente (command-stacking cascade): comando ainda
        # rodando emite notify "finalizado", o gate verde+verde empilha dezenas
        # de comandos no buffer do CLI. Quase-impossivel de auto-resolver pelo
        # Claude (e codigo do MetricsBar/OutputPanel + ciclo de vida do processo,
        # nao do comando .md). Botao cola o path do relatorio canonico para
        # reacionar a investigacao quantas vezes for preciso. Ver §15.5 e §4 do
        # relatorio.
        cascade_bug_btn = _make_btn(
            "Cascade-bug", "queue-btn-cascade-bug-report-path",
            "#F43F5E", "#E11D48", "#BE123C",
            "Cola o path do relatorio do bug da cascade do listener no terminal\n"
            "blacksmith/recovery/interactive-listener-silence-cascade-2026-05-31T0338.md\n"
            "(comando ainda rodando emite notify de fim -> empilha dezenas de\n"
            "comandos na fila; quase-impossivel de auto-resolver pelo Claude)",
        )
        cascade_bug_btn.clicked.connect(
            _paste_path("blacksmith/recovery/interactive-listener-silence-cascade-2026-05-31T0338.md")
        )

        indicators_rules_btn = _make_btn(
            "Indicators-rules", "queue-btn-indicators-rules-path",
            "#14B8A6", "#0D9488", "#0F766E",
            "Cola o path ai-forge/rules/workflow-app-indicators.md no terminal\n"
            "(regras canonicas dos botoes-indicator /auto-flow em queue-tab-pipelines)",
        )
        indicators_rules_btn.clicked.connect(_paste_path("ai-forge/rules/workflow-app-indicators.md"))

        prompt_rules_btn = _make_btn(
            "Prompt-rules", "queue-btn-prompt-creation-rules-path",
            "#6366F1", "#4F46E5", "#4338CA",
            "Cola o path ai-forge/rules/prompt-creation-rules.md no terminal\n"
            "(regras de criacao de prompts para a sub-aba prompts)",
        )
        prompt_rules_btn.clicked.connect(_paste_path("ai-forge/rules/prompt-creation-rules.md"))

        # 2026-05-31: botoes para os arquivos de regras de ai-forge/rules/ que
        # ainda nao tinham atalho na sub-aba RULES (queue-subtab-insertions-rules).
        # Mesmo padrao _make_btn + _paste_path dos demais: copia o path literal e
        # digita no terminal via _publish_to_terminal (respeita terminal-route-toggles).
        build_render_rules_btn = _make_btn(
            "Build-render-rules", "queue-btn-dcp-build-to-list-rendering-rules-path",
            "#06B6D4", "#0891B2", "#0E7490",
            "Cola o path ai-forge/rules/dcp-build-to-list-rendering.md no terminal\n"
            "(contrato do hand-off Build -> Specific-Flow: queue-btn-dcp-build ->\n"
            "queue-btn-dcp-specific-flow, o trecho mais fragil do fluxo DCP)",
        )
        build_render_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/dcp-build-to-list-rendering.md")
        )

        matrix_spec_rules_btn = _make_btn(
            "Matrix-spec-rules", "queue-btn-dcp-matrix-spec-rules-path",
            "#8B5CF6", "#7C3AED", "#6D28D9",
            "Cola o path ai-forge/rules/dcp-matrix-spec.md no terminal\n"
            "(spec arquitetural do DCP-COMMAND-MATRIX.json: schema completo,\n"
            "invariantes I-NN, validator strict, telemetria, fail-closed)",
        )
        matrix_spec_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/dcp-matrix-spec.md")
        )

        llm_routing_rules_btn = _make_btn(
            "Llm-routing-rules", "queue-btn-llm-routing-div-rules-path",
            "#EC4899", "#DB2777", "#BE185D",
            "Cola o path ai-forge/rules/llm-routing-div.md no terminal\n"
            "(regras canonicas da queue-div-llm-routing: Main LLM x Parallel\n"
            "Worker, dispatch Claude/Codex/Kimi, supressao de /model e /effort)",
        )
        llm_routing_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/llm-routing-div.md")
        )

        main_llm_publish_rules_btn = _make_btn(
            "Main-llm-publish-rules", "queue-btn-main-llm-publish-rules-path",
            "#14B8A6", "#0D9488", "#0F766E",
            "Cola o path ai-forge/rules/main-llm-publish.md no terminal\n"
            "(regras de PUBLICACAO por Main LLM no queue-div-main-llm: Claude usa\n"
            "o comando, Kimi a adaptacao do comando, Codex o prompt que simula)",
        )
        main_llm_publish_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/main-llm-publish.md")
        )

        kimi_skill_routing_rules_btn = _make_btn(
            "Kimi-skill-routing-rules", "queue-btn-kimi-skill-routing-rules-path",
            "#F59E0B", "#D97706", "#B45309",
            "Cola o path ai-forge/rules/llms/kimi-skill-routing.md no terminal\n"
            "(as duas familias de skill Kimi: elegiveis/whitelist auto-roteadas vs\n"
            "pool de emergencia, que nunca tem preferencia mas fica pronto p/ uso\n"
            "manual quando o Claude esta indisponivel)",
        )
        kimi_skill_routing_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/llms/kimi-skill-routing.md")
        )

        single_arrow_rules_btn = _make_btn(
            "Single-arrow-rules", "queue-btn-single-arrow-rules-path",
            "#F472B6", "#EC4899", "#DB2777",
            "Cola o path ai-forge/rules/single-arrow-multifunction.md no terminal\n"
            "(regras do botao unico per-item da queue: provider router como\n"
            "autoridade, cor/destino por provider Claude/Kimi/Codex, paridade\n"
            "clique/step/autocast e divergencias conhecidas)",
        )
        single_arrow_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/single-arrow-multifunction.md")
        )

        loop_rules_btn = _make_btn(
            "Loop-rules", "queue-btn-loop-rules-path",
            "#84CC16", "#65A30D", "#4D7C0F",
            "Cola o path ai-forge/rules/loop-rules.md no terminal\n"
            "(regras canonicas do subflow /loop F4d: 8 fases de preparacao,\n"
            "schema _LOOP-CONFIG.json, iteration_template, comandos auxiliares)",
        )
        loop_rules_btn.clicked.connect(_paste_path("ai-forge/rules/loop-rules.md"))

        rocksmash_rules_btn = _make_btn(
            "Rocksmash-rules", "queue-btn-rocksmash-rules-path",
            "#D946EF", "#C026D3", "#A21CAF",
            "Cola o path ai-forge/rules/rocksmash.md no terminal\n"
            "(estudo + regras canonicas do subflow /loop --rocksmash: documento\n"
            "unificado de integracao em {wbs_root}/rocksmash-integration/)",
        )
        rocksmash_rules_btn.clicked.connect(_paste_path("ai-forge/rules/rocksmash.md"))

        multibackend_rules_btn = _make_btn(
            "Multibackend-rules", "queue-btn-multibackend-rules-path",
            "#0EA5E9", "#0284C7", "#0369A1",
            "Cola o path ai-forge/rules/multibackend-rules.md no terminal\n"
            "(contrato canonico do pipeline multibackend: arq B/C, per-host issuer,\n"
            "bounce host-safe (resolveRequestIssuer, nunca request.url), anti-cascade,\n"
            "X-Forwarded-Host, /register em PUBLIC_PATHS + REGISTER_ENABLED, modos de\n"
            "falha F-1..F-5 e tensoes T-01..T-09)",
        )
        multibackend_rules_btn.clicked.connect(
            _paste_path("ai-forge/rules/multibackend-rules.md")
        )

        listener_amarelo_btn = _make_btn(
            "Listener-amarelo", "queue-btn-listener-amarelo-rules-path",
            "#FBBF24", "#F59E0B", "#D97706",
            "Cola o path ai-forge/rules/listener-amarelo.md no terminal\n"
            "(cartao de referencia rapida do estado busy do listener;\n"
            "fonte-mae em workflow-app-listeners.md)",
        )
        listener_amarelo_btn.clicked.connect(
            _paste_path("ai-forge/rules/listener-amarelo.md")
        )

        listener_azul_btn = _make_btn(
            "Listener-azul", "queue-btn-listener-azul-rules-path",
            "#3B82F6", "#2563EB", "#1D4ED8",
            "Cola o path ai-forge/rules/listener-azul.md no terminal\n"
            "(cartao de referencia rapida do estado awaiting_user do listener;\n"
            "fonte-mae em workflow-app-listeners.md)",
        )
        listener_azul_btn.clicked.connect(
            _paste_path("ai-forge/rules/listener-azul.md")
        )

        listener_verde_btn = _make_btn(
            "Listener-verde", "queue-btn-listener-verde-rules-path",
            "#16A34A", "#15803D", "#166534",
            "Cola o path ai-forge/rules/listener-verde.md no terminal\n"
            "(cartao de referencia rapida do estado idle do listener;\n"
            "fonte-mae em workflow-app-listeners.md)",
        )
        listener_verde_btn.clicked.connect(
            _paste_path("ai-forge/rules/listener-verde.md")
        )

        listener_vermelho_btn = _make_btn(
            "Listener-vermelho", "queue-btn-listener-vermelho-rules-path",
            "#DC2626", "#B91C1C", "#991B1B",
            "Cola o path ai-forge/rules/listener-vermelho.md no terminal\n"
            "(cartao de referencia rapida do estado failed do listener;\n"
            "fonte-mae em workflow-app-listeners.md)",
        )
        listener_vermelho_btn.clicked.connect(
            _paste_path("ai-forge/rules/listener-vermelho.md")
        )

        add_rules_prompt = (
            "crie no ai-forge/rules um novo arquivo de regras referente a "
            "este contexto que pedi para estudar agora. Crie estes arquivos "
            "e estas regras de forma estruturada como os outros arquivos da "
            "pasta, e faça elas de forma claude-friendly, para serem "
            "compreensivas pelo claude."
        )

        def _paste_add_rules() -> None:
            QApplication.clipboard().setText(add_rules_prompt)
            # _publish_to_terminal ja consulta terminal-route-toggles e
            # transfere foco — ver ai-forge/rules/workflow-app-terminal.md.
            self._publish_to_terminal(add_rules_prompt)
            signal_bus.toast_requested.emit(
                "Prompt 'add-rules' copiado e digitado no terminal", "info",
            )

        add_rules_btn = _make_btn(
            "add-rules", "queue-btn-add-rules-prompt",
            "#EAB308", "#CA8A04", "#A16207",
            "Cola um prompt curto pedindo ao Claude para criar um novo arquivo "
            "em ai-forge/rules/ a partir do contexto estudado agora\n"
            "(respeita terminal-route-toggles)",
        )
        add_rules_btn.clicked.connect(_paste_add_rules)

        return [
            workflow_app_btn, ws_rules_btn, dcp_rules_btn, meta_feeding_rules_btn,
            cmd_rules_btn, terminal_rules_btn, listeners_rules_btn, cascade_bug_btn,
            indicators_rules_btn, prompt_rules_btn,
            build_render_rules_btn, matrix_spec_rules_btn, llm_routing_rules_btn,
            main_llm_publish_rules_btn, kimi_skill_routing_rules_btn,
            single_arrow_rules_btn,
            loop_rules_btn, rocksmash_rules_btn, multibackend_rules_btn,
            listener_amarelo_btn, listener_azul_btn, listener_verde_btn,
            listener_vermelho_btn,
            add_rules_btn,
        ]

    # ── PERSONAS sub-aba (ai-forge/MCP/agents/) ───────────────────────────── #
    # Diretorio canonico do registry de personas MCP (INDEX.md). Path
    # repo-relativo usado tanto para resolver o diretorio (via
    # _systemforge_root, cwd-independente) quanto para o texto colado no
    # terminal (ex: ai-forge/MCP/agents/code-debugger.md).
    _PERSONAS_RELDIR = Path("ai-forge/MCP/agents")

    def _personas_dir(self) -> Path:
        """Diretorio absoluto do registry de personas MCP (cwd-independente)."""
        return self._systemforge_root() / self._PERSONAS_RELDIR

    def _scan_persona_files(self) -> list[tuple[str, str]]:
        """Varre ai-forge/MCP/agents/ e retorna [(slug, rel_path)] das personas
        REAIS, em ordem alfabetica. `rel_path` e sempre repo-relativo.

        Persona real = arquivo `<slug>.md` cujo frontmatter declara
        `slug == nome_do_arquivo` E `provider_support`. Esse criterio exclui
        os meta-docs do diretorio (INDEX.md, CHANGELOG.md, MIGRATION-*.md e
        best-practices.md — cujo slug `mcp-agents-best-practices` nao casa com
        o nome do arquivo), mantendo apenas as personas reais do registry.
        """
        found: list[tuple[str, str]] = []
        agents_dir = self._personas_dir()
        if not agents_dir.is_dir():
            return found
        for md_file in sorted(agents_dir.glob("*.md")):
            slug = md_file.stem
            if self._is_persona_md(md_file, slug):
                rel_path = str(self._PERSONAS_RELDIR / md_file.name)
                found.append((slug, rel_path))
        return found

    @staticmethod
    def _is_persona_md(md_file: Path, slug: str) -> bool:
        """True se `md_file` for uma persona canonica (ver _scan_persona_files)."""
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            return False
        if not text.startswith("---"):
            return False
        # Frontmatter = primeiro bloco entre delimitadores `---`.
        parts = text.split("---", 2)
        if len(parts) < 3:
            return False
        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return False
        if not isinstance(fm, dict):
            return False
        return fm.get("slug") == slug and "provider_support" in fm

    _PERSONA_LABELS: dict[str, str] = {
        "analista-delegador-rules": "Delegador",
        "controversial-devils-advocate-rules": "Controversial",
        "criar-md-rules": "MD Creator",
        "criar-task-rules": "Task Creator",
        "executar-task-rules": "Executor",
        "executor-de-slash-commands-rules": "Slash Executor",
        "hardening-engineer-rules": "Hardening Eng",
        "revisar-execucao-rules": "Exec Reviewer",
        "revisar-qa-rules": "QA Reviewer",
        "revisar-task-rules": "Task Reviewer",
        "study-researcher-rules": "Researcher",
        "search-in-rules": "search-in",
        "search-out-rules": "search-out",
        "search-forge-rules": "search-forge",
        "landing-page-conversion-rules": "LP Conversion",
        "code-debugger": "Debugger",
        "loop-preparer-rules": "Loop Preparer",
        "orquestrador-pdca-rules": "PDCA Orchestrator",
        "visual-designer-rules": "Visual Design",
        "layout-architect-rules": "Layout",
        "deep-detailer": "Deep Detailer",
        "billing-scpecialist": "Billing",
        "auth-security-specialist": "Auth Security",
        "deployment-reliability-specialist": "Deploy Reliability",
        "soft-engineer": "soft Engen",
        "engenheiro-solucionador": "Eng Solucionador",
        "scaffolds-blueprints-updater": "Scaffold Update",
        "questioner-rules": "Questionador",
        "ux-ui-specialist": "UX/UI",
        "performance-engineer": "Performance",
    }

    # Atribuicao canonica persona -> categoria de filtro da sub-aba 'Agentes'.
    # Os valores DEVEM pertencer a PERSONA_FILTER_CATEGORIES (validado em teste).
    # Personas auto-descobertas (botao update) que nao estiverem aqui caem na
    # inferencia por palavra-chave (_infer_persona_category) e, em ultimo caso,
    # em PERSONA_FILTER_DEFAULT.
    _PERSONA_CATEGORIES: dict[str, str] = {
        # Plan — planejamento, orquestracao, roteamento, preparo de loop
        "analista-delegador-rules": "Plan",
        "orquestrador-pdca-rules": "Plan",
        "complexity-router-rules": "Plan",
        "loop-preparer-rules": "Plan",
        "criar-md-rules": "Plan",
        # Research — pesquisa interna/externa, aprofundamento de contexto
        "search-in-rules": "Research",
        "search-out-rules": "Research",
        "search-forge-rules": "Research",
        "study-researcher-rules": "Research",
        "deep-detailer": "Research",
        # Design — design visual, layout responsivo, conversao, SEO
        "visual-designer-rules": "Design",
        "layout-architect-rules": "Design",
        "landing-page-conversion-rules": "Design",
        "seo-specialist": "Design",
        # Build — criacao/execucao de tasks e slash-commands
        "criar-task-rules": "Build",
        "executar-task-rules": "Build",
        "executor-de-slash-commands-rules": "Build",
        "scaffolds-blueprints-updater": "Build",
        # Review — revisao, QA, hardening, debug, critica adversarial
        "revisar-task-rules": "Review",
        "revisar-execucao-rules": "Review",
        "revisar-qa-rules": "Review",
        "controversial-devils-advocate-rules": "Review",
        "hardening-engineer-rules": "Review",
        "code-debugger": "Review",
        "specific-reviewer": "Review",
        "questioner-rules": "Review",
        # specialists — especialistas de dominio acionados sob demanda
        "billing-scpecialist": "specialists",
        "auth-security-specialist": "specialists",
        "deployment-reliability-specialist": "specialists",
        "soft-engineer": "specialists",
        "engenheiro-solucionador": "specialists",
        "performance-engineer": "specialists",
        # UX/UI coordena jornada/IA/interacao; Visual/Layout mantem suas faixas.
        "ux-ui-specialist": "Design",
    }

    @staticmethod
    def _infer_persona_category(slug: str) -> str:
        """Inferencia por palavra-chave para personas fora de _PERSONA_CATEGORIES.

        Mantida deterministica e conservadora: cobre os eixos das 5 categorias e
        cai em PERSONA_FILTER_DEFAULT quando nada casa. Usada por _persona_category
        para classificar personas novas adicionadas ao vivo (botao 'update').
        """
        s = slug.lower()

        def _has(*keys: str) -> bool:
            return any(k in s for k in keys)

        if _has("search", "research", "pesquis", "study", "detail", "scrap", "crawl"):
            return "Research"
        if _has(
            "design", "layout", "visual", "seo", "landing", "conversion",
            "ux", "ui", "brand", "art",
        ):
            return "Design"
        if _has(
            "review", "revis", "qa", "harden", "debug", "controvers",
            "advoca", "critic", "audit", "lint",
        ):
            return "Review"
        if _has(
            "specialist", "billing", "payment", "finance", "financeiro",
            "auth", "security", "deploy", "reliability", "sre", "infra",
            "engineer", "engenheiro", "solution", "solucion",
        ):
            return "specialists"
        if _has(
            "plan", "delegad", "orquestr", "pdca", "router", "complex",
            "loop", "prep", "estrutur", "roadmap", "scope", "criar-md",
        ):
            return "Plan"
        return PERSONA_FILTER_DEFAULT

    def _persona_category(self, slug: str, rel_path: str) -> str:
        """Categoria de filtro ('Plan'/'Research'/'Design'/'Build'/'Review') de
        uma persona, para a barra de filtros da sub-aba 'Agentes'.

        Precedencia: mapa explicito _PERSONA_CATEGORIES > inferencia por
        palavra-chave > PERSONA_FILTER_DEFAULT. O resultado e sempre um membro
        de PERSONA_FILTER_CATEGORIES.
        """
        category = self._PERSONA_CATEGORIES.get(slug) or self._infer_persona_category(
            slug
        )
        if category not in PERSONA_FILTER_CATEGORIES:
            category = PERSONA_FILTER_DEFAULT
        return category

    def _load_persona_label_overrides(self) -> dict[str, str]:
        """Le os overrides de label de personas (slug -> label) do QSettings.

        Configurados pelo gear da sub-aba 'Agentes' (_open_personas_config_dialog).
        Valores vazios sao ignorados (equivalem a 'sem override').
        """
        import json as _json

        raw = QSettings("systemForge", "workflow-app").value(
            "personas/label_overrides", None
        )
        if isinstance(raw, str) and raw:
            try:
                data = _json.loads(raw)
            except _json.JSONDecodeError:
                return {}
            if isinstance(data, dict):
                return {
                    str(k): str(v).strip()
                    for k, v in data.items()
                    if str(v).strip()
                }
        return {}

    def _persona_button_label(
        self, slug: str, rel_path: str, *, ignore_overrides: bool = False,
    ) -> str:
        """Label curto e legivel para botoes da sub-aba PERSONAS.

        Precedencia: override do usuario (gear) > _PERSONA_LABELS > frontmatter
        `name` (truncado) > slug humanizado. `ignore_overrides=True` retorna o
        label canonico (sem override) — usado pelo modal para detectar edicoes.
        """
        if not ignore_overrides:
            overrides = getattr(self, "_persona_label_overrides", None)
            if overrides and slug in overrides:
                return overrides[slug]

        if slug in self._PERSONA_LABELS:
            return self._PERSONA_LABELS[slug]

        path = Path(rel_path)
        if not path.is_absolute():
            path = self._systemforge_root() / path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1])
                except yaml.YAMLError:
                    fm = None
                if isinstance(fm, dict):
                    name = str(fm.get("name") or "").strip()
                    if name:
                        return re.sub(r"\s+", " ", name.replace("SystemForge", "")).strip()[:18]

        words = [
            w.capitalize()
            for w in slug.replace("-rules", "").replace("-", " ").split()
            if w not in {"de", "do", "da"}
        ]
        return " ".join(words)[:18] or slug[:18]

    def _build_persona_buttons(
        self, personas: list[tuple[str, str]],
    ) -> list[QPushButton]:
        """Constroi um botao por persona (slug, rel_path) AINDA NAO renderizada.

        Pula slugs ja presentes em self._persona_rendered_slugs (idempotente) e
        registra os novos no set. Cada botao cola o path da persona no terminal
        via _publish_to_terminal (respeita terminal-route-toggles T1/T2).
        """
        out: list[QPushButton] = []
        for slug, rel_path in personas:
            if slug in self._persona_rendered_slugs:
                continue
            label = self._persona_button_label(slug, rel_path)
            category = self._persona_category(slug, rel_path)
            btn = QPushButton(label)
            btn.setProperty("testid", f"queue-btn-persona-{slug}")
            # Consumido pela barra de filtros da sub-aba 'Agentes'
            # (CommandQueueWidget._apply_persona_filter).
            btn.setProperty("persona_category", category)
            btn.setAccessibleName(f"{label} - persona {category}")
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                f"{label}  ·  {category}\n"
                f"Cola o path da persona no terminal: {rel_path}"
            )
            btn.setStyleSheet(
                "QPushButton { background-color: #8B5CF6; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                "QPushButton:hover { background-color: #7C3AED; }"
                "QPushButton:pressed { background-color: #6D28D9; }"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            btn.clicked.connect(self._make_persona_paste_handler(rel_path))
            self._persona_rendered_slugs.add(slug)
            out.append(btn)
        return out

    def _make_persona_paste_handler(self, path: str):
        """Fabrica do slot de clique: copia + cola o path da persona no terminal."""
        def _h() -> None:
            QApplication.clipboard().setText(path)
            self._publish_to_terminal(path)
            signal_bus.toast_requested.emit(
                f"Persona copiada e colada no terminal: {path}", "info",
            )
        return _h

    def _populate_header_personas_subtab(self) -> list[QPushButton]:
        """Constroi os botoes da sub-aba 'PERSONAS' a partir das personas reais
        de ai-forge/MCP/agents/, seguido do botao 'update' 1:1 (verde).

        Cada botao de persona cola o path relativo no terminal. O botao update
        (sempre o ultimo widget do flow) re-varre a pasta ao vivo e adiciona
        botoes para personas novas, sem reiniciar o app.
        """
        # Rastreia slugs ja renderizados para o botao 'update' detectar novos.
        self._persona_rendered_slugs: set[str] = set()
        # Overrides de label (slug -> label) configurados via gear da sub-aba.
        # Carregados aqui para que _persona_button_label os consulte ao montar.
        self._persona_label_overrides = self._load_persona_label_overrides()

        btns: list[QPushButton] = self._build_persona_buttons(
            self._scan_persona_files()
        )

        # Gear de configuracao (34x34) — abre modal que lista os agentes atuais
        # (sincronizado com os botoes) e permite renomear o label de cada um.
        # Vive DENTRO da sub-aba 'Agentes' (so renderiza com ela aberta).
        config_gear = _GearButton(
            testid="queue-btn-personas-config",
            tooltip=(
                "Configurar agentes\n"
                "Lista os agentes atuais de ai-forge/MCP/agents/ (em sincronia\n"
                "com os botoes) e permite renomear o label de cada um."
            ),
            size=34,
            font_px=18,
        )
        config_gear.clicked.connect(self._open_personas_config_dialog)
        self._personas_config_gear = config_gear
        btns.append(config_gear)

        # Botao 'update' 1:1 (34x34) verde com seta de refresh branca dentro.
        # Re-varre ai-forge/MCP/agents/ e cria botao para cada persona nova.
        update_btn = QPushButton()
        update_btn.setAccessibleName("Recarregar personas")
        update_btn.setProperty("testid", "queue-btn-personas-update")
        update_btn.setFixedSize(34, 34)
        update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        update_btn.setToolTip(
            "Recarregar personas\n"
            "Varre ai-forge/MCP/agents/, adiciona apenas personas novas e\n"
            "mantem este botao sempre no final da sub-aba."
        )
        _refresh_icon = Path(_WORKFLOW_APP_DIR) / "assets" / "refresh.svg"
        if _refresh_icon.is_file():
            update_btn.setIcon(QIcon(str(_refresh_icon)))
            update_btn.setIconSize(QSize(18, 18))
        else:
            # Fallback textual: glifo de refresh (U+27F3) em branco.
            update_btn.setText("⟳")
        update_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FFFFFF;"
            "  border: none; border-radius: 5px;"
            "  font-size: 18px; font-weight: 700; padding: 0; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:pressed { background-color: #166534; }"
        )
        update_btn.clicked.connect(self._on_personas_update_clicked)
        self._persona_update_btn = update_btn

        btns.append(update_btn)
        return btns

    def _on_personas_update_clicked(self) -> None:
        """Slot do botao 'update' da sub-aba PERSONAS.

        Re-varre ai-forge/MCP/agents/, detecta personas sem botao e materializa
        um botao para cada uma, inserido ANTES do proprio botao update (que
        permanece sempre o ultimo widget do flow).
        """
        new_btns = self._build_persona_buttons(self._scan_persona_files())
        if not new_btns:
            signal_bus.toast_requested.emit(
                "Nenhuma persona nova em ai-forge/MCP/agents/.", "info",
            )
            return
        self._command_queue.add_persona_buttons(
            new_btns, keep_last=self._persona_update_btn,
        )
        signal_bus.toast_requested.emit(
            f"{len(new_btns)} persona(s) adicionada(s) a aba PERSONAS.", "info",
        )

    def _open_personas_config_dialog(self) -> None:
        """Abre o modal de configuracao dos agentes da sub-aba 'Agentes'.

        Lista os agentes ATUAIS varridos de ai-forge/MCP/agents/ (sempre em
        sincronia com os botoes, nunca uma lista hardcoded) e permite renomear
        o label de cada um. Submit persiste os overrides (slug -> label) em
        QSettings e reconstroi a sub-aba para refletir os novos labels.
        """
        import json as _json

        from PySide6.QtWidgets import QDialog

        personas = self._scan_persona_files()
        entries = [
            {
                "slug": slug,
                "rel_path": rel_path,
                "label": self._persona_button_label(slug, rel_path),
                "default_label": self._persona_button_label(
                    slug, rel_path, ignore_overrides=True,
                ),
            }
            for slug, rel_path in personas
        ]

        dlg = PersonasConfigDialog(entries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # collect() devolve apenas os labels que diferem do canonico (edicoes).
        overrides = dlg.collect()
        QSettings("systemForge", "workflow-app").setValue(
            "personas/label_overrides", _json.dumps(overrides),
        )
        self._persona_label_overrides = overrides

        # Reconstroi a sub-aba 'Agentes' (limpa rendered_slugs + reaplica labels).
        new_btns = self._populate_header_personas_subtab()
        self._command_queue.populate_personas_subtab(new_btns)
        signal_bus.toast_requested.emit(
            f"Agentes atualizados ({len(overrides)} label(s) personalizado(s)).",
            "info",
        )

    def _populate_header_cmd_subtab(self) -> list[QPushButton]:
        """Constroi os botoes da sub-aba 'CMD' (comandos avulsos).

        Cada botao cola um slash-command literal no terminal via
        _publish_to_terminal — respeita terminal-route-toggles (T1/T2) e
        transfere foco conforme ai-forge/rules/workflow-app-terminal.md.
        Sub-aba destinada a comandos pontuais que nao pertencem a uma
        pipeline (DCP/loop/daily), disparados sob demanda pelo operador.
        """
        def _make_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _paste_command(command: str):
            def _h() -> None:
                # Insercao LLM-aware: o transportador renderiza por Main LLM (T1) e
                # da todo o feedback (clipboard/toast/abort). Botoes neutros (paths)
                # seguem em _publish_to_terminal. Ver
                # blacksmith/brainstorm-mcp/06-15-insertions-subtab-llm-routing-tasks.md.
                self._publish_insertion_llm_aware(command)
            return _h

        # ── Botões adicionados 2026-06-03 ─────────────────────────────────── #
        _EXTRA_CMDS = [
            (
                "listener-recovery",
                "queue-btn-cmd-listener-recovery",
                "#0EA5E9", "#0284C7", "#0369A1",
                "/tools:listener-recovery",
                "Cola o comando /tools:listener-recovery no terminal\n"
                "(aciona recuperacao do listener de canal)",
            ),
            (
                "autocast-put",
                "queue-btn-cmd-autocast-put",
                "#8B5CF6", "#7C3AED", "#6D28D9",
                "/cmd:autocast-put",
                "Cola o comando /cmd:autocast-put no terminal\n"
                "(injeta campo autocast em slash-commands)",
            ),
            (
                "create-agent",
                "queue-btn-cmd-mcp-create-agent",
                "#10B981", "#059669", "#047857",
                "/mcp:create-agent",
                "Cola o comando /mcp:create-agent no terminal\n"
                "(cria nova persona de agente MCP)",
            ),
            (
                "troop-review",
                "queue-btn-cmd-agents-troop-review",
                "#F59E0B", "#D97706", "#B45309",
                "/agents:troop-review",
                "Cola o comando /agents:troop-review no terminal\n"
                "(revisao de tropa pos-execucao: 3 checks sequenciais + correcao tasks [!])",
            ),
            (
                "mcp:research",
                "queue-btn-cmd-mcp-research",
                "#06B6D4", "#0891B2", "#0E7490",
                "/mcp:research",
                "Cola o comando /mcp:research no terminal\n"
                "(pesquisa via persona MCP Codex/Kimi)",
            ),
            (
                "mcp:update",
                "queue-btn-cmd-mcp-update",
                "#6366F1", "#4F46E5", "#4338CA",
                "/mcp:update",
                "Cola o comando /mcp:update no terminal\n"
                "(atualiza configuracoes de agentes MCP)",
            ),
            (
                "loop:clear",
                "queue-btn-cmd-loop-clear",
                "#EC4899", "#DB2777", "#BE185D",
                "/loop:clear",
                "Cola o comando /loop:clear no terminal\n"
                "(arquiva loops concluidos para blacksmith/done/)",
            ),
            (
                "kimi-pair-analyse",
                "queue-btn-cmd-kimi-pair-analyse",
                "#F97316", "#EA580C", "#C2410C",
                "/cmd:kimi-pair-analyse",
                "Cola o comando /cmd:kimi-pair-analyse no terminal\n"
                "(analisa slash-command para adaptacao Claude->Kimi com snapshot atomico)",
            ),
            (
                "kimi-pair-execute",
                "queue-btn-cmd-kimi-pair-execute",
                "#EF4444", "#DC2626", "#B91C1C",
                "/cmd:kimi-pair-execute",
                "Cola o comando /cmd:kimi-pair-execute no terminal\n"
                "(executa plano de adaptacao Claude->Kimi gerado pelo kimi-pair-analyse)",
            ),
            (
                "cmd:delete",
                "queue-btn-cmd-delete",
                "#71717A", "#52525B", "#3F3F46",
                "/cmd:delete",
                "Cola o comando /cmd:delete no terminal\n"
                "(remove slash-command do repositorio e dos indices)",
            ),
            (
                "global-mgmt",
                "queue-btn-cmd-global-management",
                "#A78BFA", "#7C3AED", "#6D28D9",
                "/cmd:global-management",
                "Cola o comando /cmd:global-management no terminal\n"
                "(gestao global de slash-commands: auditoria, limpeza, reorganizacao)",
            ),
            (
                "whitelist",
                "queue-btn-cmd-whitelist",
                "#34D399", "#059669", "#047857",
                "/cmd:whitelist",
                "Cola o comando /cmd:whitelist no terminal\n"
                "(classifica slash-command para Kimi/T2, Codex/T3 ou Claude-only/T1)",
            ),
        ]

        extra_btns = []
        for label, testid, bg, hover, pressed, cmd, tooltip in _EXTRA_CMDS:
            btn = _make_btn(label, testid, bg, hover, pressed, tooltip)
            btn.clicked.connect(_paste_command(cmd))
            extra_btns.append(btn)

        # ── Botoes de debug de listener (source.md secao 19) ──────────────── #
        # Cinco botoes de debug colam /listener:analyse --<flag>; o sexto cola
        # /listener:repair e mantem um contador persistente em
        # blacksmith/listeners/.debug-counter. As cores dos botoes de debug
        # espelham as cores canonicas dos dots em listener-{cor}.md
        # (debug-blue-reverse usa um tom de sky para distinguir do debug-blue).
        # IO do contador e auxiliar: try/except total, falha silenciosa com
        # warning no log, nunca crash nem toast de erro (R-btn1/R-btn2).
        _COUNTER_FILE = Path("blacksmith/listeners/.debug-counter")

        def _read_debug_counter() -> int:
            try:
                return int(_COUNTER_FILE.read_text(encoding="utf-8").strip())
            except Exception as exc:
                logger.warning("listener debug-counter read falhou: %s", exc)
                return 0

        def _write_debug_counter(value: int) -> None:
            try:
                _COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
                _COUNTER_FILE.write_text(str(value), encoding="utf-8")
            except Exception as exc:
                # contador auxiliar — falha nao e bloqueante.
                logger.warning("listener debug-counter write falhou: %s", exc)

        _DEBUG_CMDS = [
            ("debug-green",  "queue-btn-cmd-debug-green",
             "#22C55E", "#16A34A", "#15803D", "/listener:analyse --green",
             "Debug: dot verde ligado mas autocast nao despachou"),
            ("debug-yellow", "queue-btn-cmd-debug-yellow",
             "#F59E0B", "#D97706", "#B45309", "/listener:analyse --yellow",
             "Debug: dot amarelo persistiu apos sucesso"),
            ("debug-red",    "queue-btn-cmd-debug-red",
             "#EF4444", "#DC2626", "#B91C1C", "/listener:analyse --red",
             "Debug: dot vermelho sem causa aparente"),
            ("debug-blue",   "queue-btn-cmd-debug-blue",
             "#3B82F6", "#2563EB", "#1D4ED8", "/listener:analyse --blue",
             "Debug: AUQ na tela mas dot azul nao apareceu"),
            ("debug-blue-reverse", "queue-btn-cmd-debug-blue-reverse",
             "#0EA5E9", "#0284C7", "#0369A1", "/listener:analyse --blue-reverse",
             "Debug: dot azul na tela mas sem AUQ (azul espurio)"),
        ]

        _counter = _read_debug_counter()

        def _repair_label(n: int) -> str:
            return "listener-repair" if n == 0 else f"listener-repair ({n})"

        def _repair_tooltip(n: int) -> str:
            if n == 0:
                return "Nenhum caso pendente"
            return (
                f"{n} caso(s) pendente(s) de analise — clique para processar\n"
                "(contador pode divergir entre instancias simultaneas)"
            )

        repair_btn = _make_btn(
            _repair_label(_counter),
            "queue-btn-cmd-listener-repair",
            "#A855F7", "#9333EA", "#7E22CE",
            _repair_tooltip(_counter),
        )
        self._listener_repair_btn = repair_btn

        def _on_debug_click(cmd: str):
            def _h() -> None:
                nonlocal _counter
                ok = self._publish_insertion_llm_aware(cmd)
                if not ok:
                    return
                _counter += 1
                _write_debug_counter(_counter)
                self._listener_repair_btn.setText(_repair_label(_counter))
                self._listener_repair_btn.setToolTip(_repair_tooltip(_counter))
            return _h

        def _on_repair_click() -> None:
            nonlocal _counter
            ok = self._publish_insertion_llm_aware("/listener:repair")
            if not ok:
                return
            _counter = 0
            _write_debug_counter(0)
            self._listener_repair_btn.setText(_repair_label(0))
            self._listener_repair_btn.setToolTip(_repair_tooltip(0))

        for label, testid, bg, hover, pressed, cmd, tooltip in _DEBUG_CMDS:
            b = _make_btn(label, testid, bg, hover, pressed, tooltip)
            b.clicked.connect(_on_debug_click(cmd))
            extra_btns.append(b)

        repair_btn.clicked.connect(_on_repair_click)
        extra_btns.append(repair_btn)

        return extra_btns

    def _populate_header_auto_improove_subtab(self) -> list[QPushButton]:
        """Constroi os botoes da sub-aba 'AUTO IMPROOVE'.

        Cada botao cola um slash-command /auto-improove:* ou comandos de apoio
        (mcp:research, mcp:update, mcp:cmd-best-practices, cmd:*-gaps) no
        terminal via _publish_to_terminal.
        """
        def _make_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _paste_command(command: str):
            def _h() -> None:
                # Insercao LLM-aware: o transportador renderiza por Main LLM (T1) e
                # da todo o feedback (clipboard/toast/abort).
                self._publish_insertion_llm_aware(command)
            return _h

        _CMDS = [
            ("ai:cmd",          "queue-btn-ai-cmd",            "#6366F1", "#4F46E5", "#4338CA", "/auto-improove:cmd",                     "Melhoria continua de slash-commands"),
            ("ai:fases",        "queue-btn-ai-fases",          "#8B5CF6", "#7C3AED", "#6D28D9", "/auto-improove:fases",                   "Melhoria continua de WORKFLOW-FASES"),
            ("ai:templates",    "queue-btn-ai-templates",      "#A78BFA", "#7C3AED", "#6D28D9", "/auto-improove:templates",               "Melhoria continua de templates"),
            ("ai:flow",         "queue-btn-ai-flow",           "#0EA5E9", "#0284C7", "#0369A1", "/auto-improove:flow",                    "Melhoria continua do flow geral"),
            ("ai:blueprints",   "queue-btn-ai-blueprints",     "#06B6D4", "#0891B2", "#0E7490", "/auto-improove:blueprints",              "Melhoria continua de blueprints"),
            ("ai:guardrails",   "queue-btn-ai-guardrails",     "#10B981", "#059669", "#047857", "/auto-improove:guardrails",              "Melhoria continua de guardrails"),
            ("ai:anthropic",    "queue-btn-ai-anthropic",      "#F59E0B", "#D97706", "#B45309", "/auto-improove:anthropic",               "Melhoria continua do contexto Anthropic"),
            ("ai:cli-bp",       "queue-btn-ai-cli-bp",         "#F97316", "#EA580C", "#C2410C", "/auto-improove:cli-bp",                  "Melhoria continua de CLI blueprints"),
            ("ai:skills",       "queue-btn-ai-skills",         "#EC4899", "#DB2777", "#BE185D", "/auto-improove:skills",                  "Melhoria continua de skills"),
            ("use-kimi-sweep",  "queue-btn-ai-use-kimi",       "#14B8A6", "#0D9488", "#0F766E", "/cmd:use-kimi",                          "Sweep sem-argumento: cria a versao Kimi (pool de emergencia) de 1 comando por execucao, fora da whitelist"),
            ("ai:upd-wf",       "queue-btn-ai-update-wf",      "#EF4444", "#DC2626", "#B91C1C", "/auto-improove:update-workflow-template", "Atualiza template canonico de workflow"),
            ("mcp:research",    "queue-btn-ai-mcp-research",   "#06B6D4", "#0891B2", "#0E7490", "/mcp:research",                          "Pesquisa via persona MCP Codex/Kimi"),
            ("mcp:update",      "queue-btn-ai-mcp-update",     "#6366F1", "#4F46E5", "#4338CA", "/mcp:update",                            "Atualiza configuracoes de agentes MCP"),
            ("cmd-best-prac",   "queue-btn-ai-cmd-best-prac",  "#8B5CF6", "#7C3AED", "#6D28D9", "/mcp:cmd-best-practices",                "Auditoria MCP de boas praticas em slash-commands"),
            ("find-gaps",       "queue-btn-ai-find-gaps",      "#34D399", "#059669", "#047857", "/cmd:find-gaps",                         "Identifica gaps nos slash-commands"),
            ("gap-to-task",     "queue-btn-ai-gap-to-task",    "#10B981", "#059669", "#047857", "/cmd:gap-to-task",                       "Converte gaps identificados em tasks"),
            ("exec-gap-tasks",  "queue-btn-ai-exec-gap-tasks", "#F59E0B", "#D97706", "#B45309", "/cmd:execute-gap-tasks",                 "Executa tasks de correcao de gaps"),
            ("gap-review",      "queue-btn-ai-gap-review",     "#F97316", "#EA580C", "#C2410C", "/cmd:gap-review",                        "Revisao de gaps apos execucao"),
            ("ai:auq",          "queue-btn-ai-auq",            "#A78BFA", "#7C3AED", "#6D28D9", "/auto-improove:auq",                     "Auto-improove via AUQ interview"),
        ]

        btns = []
        for label, testid, bg, hover, pressed, cmd, tooltip in _CMDS:
            btn = _make_btn(label, testid, bg, hover, pressed, tooltip)
            btn.clicked.connect(_paste_command(cmd))
            btns.append(btn)
        return btns

    def _populate_header_personal_subtab(self) -> list[QPushButton]:
        """Constroi os botoes da sub-aba 'PERSONAL'.

        Comandos pessoais: curriculum, imbound e marketing pessoal.
        """
        def _make_btn(
            label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str,
        ) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #FAFAFA;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _paste_command(command: str):
            def _h() -> None:
                # Insercao LLM-aware: o transportador renderiza por Main LLM (T1) e
                # da todo o feedback (clipboard/toast/abort).
                self._publish_insertion_llm_aware(command)
            return _h

        _CMDS = [
            ("cv:create",      "queue-btn-personal-cv-create",   "#6366F1", "#4F46E5", "#4338CA", "/curriculum:create",  "Gera novo curriculum vitae"),
            ("cv:print",       "queue-btn-personal-cv-print",    "#8B5CF6", "#7C3AED", "#6D28D9", "/curriculum:print",   "Exporta curriculum para PDF"),
            ("imbound:query",  "queue-btn-personal-imb-query",   "#0EA5E9", "#0284C7", "#0369A1", "/imbound:query",      "Consulta leads/oportunidades no imbound"),
            ("imbound:prep",   "queue-btn-personal-imb-prep",    "#06B6D4", "#0891B2", "#0E7490", "/imbound:prepare",    "Prepara proposta para lead imbound"),
            ("imbound:lessie", "queue-btn-personal-imb-lessie",  "#10B981", "#059669", "#047857", "/imbound:lessie",     "Fluxo Lessie de onboarding imbound"),
            ("my-pictures",    "queue-btn-personal-my-pics",     "#F59E0B", "#D97706", "#B45309", "/mkt:my-pictures",    "Gera fotos pessoais via gpt-image-1"),
            ("realism-pass",   "queue-btn-personal-realism",     "#F97316", "#EA580C", "#C2410C", "/mkt:realism-pass",   "Aplica realism pass nas imagens geradas"),
            ("mkt:clone",      "queue-btn-personal-mkt-clone",   "#EC4899", "#DB2777", "#BE185D", "/mkt:clone",          "Clona site de referencia para boilerplate mkt"),
        ]

        btns = []
        for label, testid, bg, hover, pressed, cmd, tooltip in _CMDS:
            btn = _make_btn(label, testid, bg, hover, pressed, tooltip)
            btn.clicked.connect(_paste_command(cmd))
            btns.append(btn)
        return btns

    def _populate_header_paths_extras(self) -> list[QPushButton]:
        """Constroi 6 botoes para campos basic_flow do project.json ativo.

        Campos: brief_root, wbs_root, docs_root, github_ssh, dcp_root,
        custom_workflow_root. Resolve via app_state.config; github_ssh via
        app_state.config.raw["basic_flow"]. Campo ausente ou vazio emite
        toast warning; preenchido: clipboard + _publish_to_terminal + toast info.
        Respeita T1/T2 via _publish_to_terminal.
        """
        _FIELDS = [
            ("brief",     "output-btn-brief-path",            "#22D3EE", "#0891B2", "#0E7490",
             "brief_root",          "Cola o valor de basic_flow.brief_root no terminal"),
            ("wbs",       "output-btn-wbs-path",              "#A78BFA", "#7C3AED", "#6D28D9",
             "wbs_root",            "Cola o valor de basic_flow.wbs_root no terminal"),
            ("docs",      "output-btn-docs-path",             "#34D399", "#059669", "#047857",
             "docs_root",           "Cola o valor de basic_flow.docs_root no terminal"),
            ("github",    "output-btn-github-ssh",            "#F472B6", "#DB2777", "#BE185D",
             "github_ssh",          "Cola o valor de basic_flow.github_ssh no terminal"),
            ("dcp",       "output-btn-dcp-root",              "#FB923C", "#EA580C", "#C2410C",
             "dcp_root",            "Cola o valor de basic_flow.dcp_root no terminal"),
            ("custom-wf", "output-btn-custom-workflow-root",  "#FBBF24", "#F59E0B", "#D97706",
             "custom_workflow_root","Cola o valor de basic_flow.custom_workflow_root no terminal"),
            ("app-rules", "output-btn-rules-path",            "#10B981", "#059669", "#047857",
             "rules_root",          "Cola o valor de basic_flow.rules_root no terminal (pasta gitignored de regras)"),
        ]

        def _make_btn(label: str, testid: str, bg: str, hover: str, pressed: str, tooltip: str) -> QPushButton:
            btn = QPushButton(label)
            btn.setProperty("testid", testid)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: #18181B;"
                "  border: none; border-radius: 5px;"
                "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
                f"QPushButton:hover {{ background-color: {hover}; color: #FAFAFA; }}"
                f"QPushButton:pressed {{ background-color: {pressed}; color: #FAFAFA; }}"
                "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
            )
            return btn

        def _make_handler(field: str):
            def _h() -> None:
                if not app_state.has_config or not app_state.config:
                    signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                    return
                cfg = app_state.config
                if field == "github_ssh":
                    val = (cfg.raw.get("basic_flow") or {}).get("github_ssh", "") or ""
                else:
                    val = getattr(cfg, field, "") or ""
                val = val.strip()
                if not val:
                    signal_bus.toast_requested.emit(
                        f"{field} nao configurado em project.json", "warning",
                    )
                    return
                QApplication.clipboard().setText(val)
                self._publish_to_terminal(val)
                signal_bus.toast_requested.emit(
                    f"Path copiado e digitado no terminal: {val}", "info",
                )
            return _h

        btns = []
        for label, testid, bg, hover, pressed, field, tooltip in _FIELDS:
            btn = _make_btn(label, testid, bg, hover, pressed, f"{tooltip} ({field})")
            btn.clicked.connect(_make_handler(field))
            btns.append(btn)

        # Botão "Analise a documentação" — mix de json+brief+docs+wbs num único prompt
        analyse_btn = _make_btn(
            "Analise a documentação",
            "output-btn-analyse-docs",
            "#6366F1", "#4F46E5", "#4338CA",
            "Gera no terminal um prompt de análise combinando JSON, brief, docs e wbs",
        )

        def _on_analyse_docs() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            cfg = app_state.config
            import os
            try:
                json_path = os.path.relpath(cfg.config_path, str(cfg.project_dir))
            except ValueError:
                json_path = cfg.config_path
            brief = (getattr(cfg, "brief_root", "") or "").strip()
            docs  = (getattr(cfg, "docs_root",  "") or "").strip()
            wbs   = (getattr(cfg, "wbs_root",   "") or "").strip()
            missing = [f for f, v in [("brief_root", brief), ("docs_root", docs), ("wbs_root", wbs)] if not v]
            if missing:
                signal_bus.toast_requested.emit(
                    f"Campo(s) ausente(s) no project.json: {', '.join(missing)}", "warning",
                )
                return
            text = (
                f"Analise a documentação referente ao projeto {json_path}, "
                f"a documentação do brief do produto está no {brief}, "
                f"a documentação técnica como PRD, HLD, USER STORIES, ADRs, DESIGN, entre outras estão no {docs}. "
                f"Caso seja necessário também, detalhamento dos modules e tasks da contrução do sistema estão no {wbs}"
            )
            self._publish_to_terminal(text)
            signal_bus.toast_requested.emit("Prompt de análise enviado ao terminal.", "info")

        analyse_btn.clicked.connect(_on_analyse_docs)
        btns.append(analyse_btn)
        return btns

    def _build_repo_rules_button(self) -> QPushButton:
        """Botao 'repo rules' da linha de baixo da sub-aba paths & IDs.

        Cola no terminal o path `{workspace_root}/rules`, onde workspace_root
        vem do project.json ativo (anexado em metrics-project-pill). Sem
        projeto carregado ou workspace_root vazio: toast warning, nada e
        publicado (anti Zero Silencio). Respeita T1/T2 via _publish_to_terminal.
        """
        btn = QPushButton("repo rules")
        btn.setProperty("testid", "queue-btn-repo-rules-path")
        btn.setFixedHeight(34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(
            "Cola no terminal o path {workspace_root}/rules do projeto ativo\n"
            "(workspace_root vem do project.json anexado em metrics-project-pill)"
        )
        btn.setStyleSheet(
            "QPushButton { background-color: #14B8A6; color: #18181B;"
            "  border: none; border-radius: 5px;"
            "  font-size: 10px; font-weight: 700; padding: 2px 8px; }"
            "QPushButton:hover { background-color: #0D9488; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #0F766E; color: #FAFAFA; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #71717A; }"
        )
        btn.clicked.connect(self._on_repo_rules_path)
        return btn

    def _on_ws_rules_path(self) -> None:
        project_cfg = app_state.project_config
        if not project_cfg:
            signal_bus.toast_requested.emit(
                "workspace_root indisponivel: nenhum projeto carregado."
                " Selecione o project.json via queue-btn-json-path.",
                "warning",
            )
            return
        ws = (project_cfg.workspace_root or "").strip()
        if not ws:
            signal_bus.toast_requested.emit(
                "workspace_root nao configurado em project.json", "warning",
            )
            return
        path = f"{ws.rstrip('/')}/rules"
        QApplication.clipboard().setText(path)
        self._publish_to_terminal(path)
        signal_bus.toast_requested.emit(
            f"Path copiado e digitado no terminal: {path}", "info",
        )

    def _on_repo_rules_path(self) -> None:
        if not app_state.has_config or not app_state.config:
            signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
            return
        ws = (app_state.config.workspace_root or "").strip()
        if not ws:
            signal_bus.toast_requested.emit(
                "workspace_root nao configurado em project.json", "warning",
            )
            return
        path = f"{ws.rstrip('/')}/rules"
        QApplication.clipboard().setText(path)
        self._publish_to_terminal(path)
        signal_bus.toast_requested.emit(
            f"Path copiado e digitado no terminal: {path}", "info",
        )

    def _build_terminal_notes_footer(self, testid: str) -> QWidget:
        """Footer de anotacoes livre por terminal — sem comunicacao com o resto
        do app.

        Mesma altura do `queue-add-bar` (36px) para casar visualmente quando os
        terminais ficam lado a lado com a queue. Aparencia neutra (letra
        normal, fundo escuro padrao), distinto do `main-window-label` que e
        outdoor verde grande.

        Acoes a direita do input:
          1. Botao seta para cima — cola o texto do input no terminal
             correspondente ao testid (interactive vs workspace).
          2. Botao copiar (icone de duas folhas sobrepostas) — joga o texto
             na clipboard.

        Os icones SVG sao renderizados em branco via QSvgRenderer + QPainter
        porque os assets usam `stroke="currentColor"` e QIcon nao herda cor
        do QSS.
        """
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QApplication, QHBoxLayout

        bar = QWidget()
        bar.setProperty("testid", testid)
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        notes_input = QLineEdit()
        notes_input.setPlaceholderText("anotacoes")
        notes_input.setStyleSheet(
            "QLineEdit {"
            "  color: #E4E4E7;"
            "  background-color: #18181B;"
            "  border: 1px solid #3F3F46;"
            "  border-radius: 3px;"
            "  font-size: 12px;"
            "  padding: 2px 6px;"
            "}"
            "QLineEdit:focus { border-color: #52525B; }"
        )
        lay.addWidget(notes_input, stretch=1)

        btn_style = (
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 3px; padding: 2px; }"
            "QPushButton:hover { background-color: #52525B; color: #FFFFFF; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )

        def _open_notes_modal() -> None:
            from workflow_app.dialogs.notes_expand_modal import NotesExpandModal

            modal = NotesExpandModal(testid, notes_input.text(), parent=self)
            if modal.exec() == QDialog.DialogCode.Accepted:
                notes_input.setText(modal.text())
                notes_input.setFocus()

        expand_btn = QPushButton()
        expand_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "expand.svg"
        expand_icon = self._load_tinted_svg_icon(expand_icon_path, "#FAFAFA")
        if expand_icon is not None:
            expand_btn.setIcon(expand_icon)
            expand_btn.setIconSize(QSize(14, 14))
        else:
            expand_btn.setText("⛶")
        expand_btn.setFixedSize(26, 26)
        expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        expand_btn.setToolTip("Abrir anotacao em janela ampliada (Ctrl+E)")
        expand_btn.setStyleSheet(btn_style)
        expand_btn.clicked.connect(_open_notes_modal)
        lay.addWidget(expand_btn)

        expand_shortcut = QShortcut(QKeySequence("Ctrl+E"), notes_input)
        expand_shortcut.activated.connect(_open_notes_modal)

        paste_btn = QPushButton()
        arrow_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "arrow-up.svg"
        arrow_icon = self._load_tinted_svg_icon(arrow_icon_path, "#FAFAFA")
        if arrow_icon is not None:
            paste_btn.setIcon(arrow_icon)
            paste_btn.setIconSize(QSize(14, 14))
        else:
            paste_btn.setText("↑")
        paste_btn.setFixedSize(26, 26)
        paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        paste_btn.setToolTip("Colar anotacao no terminal")
        paste_btn.setStyleSheet(btn_style)

        is_workspace = testid == "terminal-workspace-notes"

        def _paste_to_terminal() -> None:
            text = notes_input.text()
            if not text:
                return
            if is_workspace:
                # workspace = T2 (Kimi, sempre visivel) + T3 (Codex) quando
                # expandido; ambos pyte. Foco no T3 quando expandido, senao T2.
                self._dispatch_workspace_text(text, with_enter=False)
                if getattr(self, "_t3_visible", False) and hasattr(self, "_workspace_panel_xterm"):
                    try:
                        self._workspace_panel_xterm._terminal.setFocus()
                    except AttributeError:
                        pass
                else:
                    try:
                        self._workspace_panel._terminal.setFocus()
                    except AttributeError:
                        pass
            else:
                signal_bus.paste_text_in_terminal.emit(text)
                signal_bus.focus_interactive_terminal.emit()

        paste_btn.clicked.connect(_paste_to_terminal)
        lay.addWidget(paste_btn)

        clear_btn = QPushButton()
        broom_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "broom.svg"
        broom_icon = self._load_tinted_svg_icon(broom_icon_path, "#FAFAFA")
        if broom_icon is not None:
            clear_btn.setIcon(broom_icon)
            clear_btn.setIconSize(QSize(14, 14))
        else:
            clear_btn.setText("🧹")
        clear_btn.setFixedSize(26, 26)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Limpar anotacao")
        clear_btn.setStyleSheet(btn_style)
        clear_btn.clicked.connect(notes_input.clear)
        lay.addWidget(clear_btn)

        copy_btn = QPushButton()
        copy_icon_path = Path(_WORKFLOW_APP_DIR) / "assets" / "copy.svg"
        copy_icon = self._load_tinted_svg_icon(copy_icon_path, "#FAFAFA")
        if copy_icon is not None:
            copy_btn.setIcon(copy_icon)
            copy_btn.setIconSize(QSize(14, 14))
        else:
            copy_btn.setText("⎘")
        copy_btn.setFixedSize(26, 26)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setToolTip("Copiar anotacao para a area de transferencia")
        copy_btn.setStyleSheet(btn_style)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(notes_input.text())
        )
        lay.addWidget(copy_btn)

        return bar

    def _load_tinted_svg_icon(self, path: Path, color_hex: str) -> QIcon | None:
        """Le um SVG com `stroke/fill="currentColor"` e renderiza em `color_hex`,
        retornando um QIcon. Devolve None se o arquivo nao existir ou o
        modulo QtSvg nao estiver disponivel — caller cuida do fallback texto.
        """
        if not path.is_file():
            return None
        try:
            from PySide6.QtCore import QByteArray
            from PySide6.QtCore import QSize as _QSize
            from PySide6.QtGui import QPainter, QPixmap
            from PySide6.QtSvg import QSvgRenderer
        except ImportError:
            return None

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        tinted = raw.replace("currentColor", color_hex)

        renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
        if not renderer.isValid():
            return None
        pixmap = QPixmap(_QSize(32, 32))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        return QIcon(pixmap)

    def _build_workspace_label_bar(self) -> QWidget:
        """20px label bar for the Workspace terminal with four shortcut buttons.

        Buttons: WORKSPACE (purple) · SystemForge (blue) · cd Workflow-app (teal)
        · mention Workflow-app (teal). The three leftmost send a `cd <absolute>`
        + Enter; the rightmost pastes the relative path `ai-forge/workflow-app`
        without Enter.
        """
        from PySide6.QtWidgets import QHBoxLayout

        bar = QWidget()
        bar.setFixedHeight(20)
        bar.setStyleSheet("background-color: #1E1B4B;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(0)

        def _btn(label: str, color: str) -> QPushButton:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; color: {color};"
                f"  font-size: 10px; font-weight: 700; padding: 0 3px; }}"
                f"QPushButton:hover {{ color: #FFFFFF; background: transparent; }}"
            )
            return b

        # ── WORKSPACE — cd to project workspace_root ──────────────────── #
        btn_ws = _btn("WORKSPACE", "#A78BFA")
        btn_ws.setToolTip("cd → workspace do projeto carregado")

        # label-bar buttons roteiam para o terminal WORKSPACE visivel
        # (T2/Kimi sempre visivel; T3/Codex se expandido) via
        # _dispatch_workspace_text. Foco no T3 quando expandido, senao T2.
        def _focus_workspace() -> None:
            if getattr(self, "_t3_visible", False) and hasattr(self, "_workspace_panel_xterm"):
                try:
                    self._workspace_panel_xterm._terminal.setFocus()
                    return
                except AttributeError:
                    pass
            try:
                self._workspace_panel._terminal.setFocus()
            except AttributeError:
                pass

        def _on_workspace() -> None:
            if not app_state.has_config or not app_state.config:
                signal_bus.toast_requested.emit("Nenhum projeto carregado.", "warning")
                return
            path = str(app_state.config.project_dir / app_state.config.workspace_root)
            self._dispatch_workspace_text(f"cd {path}", with_enter=True)
            _focus_workspace()

        btn_ws.clicked.connect(_on_workspace)

        # ── SystemForge — cd to monorepo root ─────────────────────────── #
        btn_sf = _btn("SystemForge", "#60A5FA")
        btn_sf.setToolTip(f"cd → {_SYSTEMFORGE_DIR}")
        btn_sf.clicked.connect(
            lambda: (
                self._dispatch_workspace_text(f"cd {_SYSTEMFORGE_DIR}", with_enter=True),
                _focus_workspace(),
            )
        )

        # ── cd Workflow-app — cd to ai-forge/workflow-app ─────────────── #
        btn_wa = _btn("cd Workflow-app", "#2DD4BF")
        btn_wa.setToolTip(f"cd → {_WORKFLOW_APP_DIR}")
        btn_wa.clicked.connect(
            lambda: (
                self._dispatch_workspace_text(f"cd {_WORKFLOW_APP_DIR}", with_enter=True),
                _focus_workspace(),
            )
        )

        # ── mention Workflow-app — paste relative path without Enter ──── #
        btn_wa_mention = _btn("mention Workflow-app", "#2DD4BF")
        btn_wa_mention.setToolTip("Cola 'ai-forge/workflow-app' no terminal (sem Enter)")
        btn_wa_mention.clicked.connect(
            lambda: (
                self._dispatch_workspace_text("ai-forge/workflow-app", with_enter=False),
                _focus_workspace(),
            )
        )

        lay.addWidget(btn_ws)
        lay.addSpacing(6)
        lay.addWidget(btn_sf)
        lay.addSpacing(6)
        lay.addWidget(btn_wa)
        lay.addSpacing(6)
        lay.addWidget(btn_wa_mention)
        lay.addSpacing(10)
        # space-between: stretch empurra o arrow T3 para a borda oposta dos
        # botoes de path/mention.
        lay.addStretch()

        # ── Arrow T3 (pyte) — colapsar/expandir terceiro terminal ─────── #
        # 2026-05-19: substitui o antigo terminal-engine-toggle ("1-pyte").
        # Icone reage ao layout outer:
        #   - T1+T2 column (terminal_is_vertical=True)  -> seta lateral ◀/▶
        #   - T1+T2 row    (terminal_is_vertical=False) -> seta vertical ▲/▼
        self._t3_arrow_btn = QPushButton()
        self._t3_arrow_btn.setProperty("testid", "terminal-t3-toggle")
        self._t3_arrow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t3_arrow_btn.setFixedSize(18, 18)
        self._t3_arrow_btn.setEnabled(True)
        self._t3_arrow_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: #FAFAFA; font-size: 12px; font-weight: 700; padding: 0; }"
            "QPushButton:hover { color: #FBBF24; background: transparent; }"
            "QPushButton:disabled { color: #52525B; }"
        )
        self._t3_arrow_btn.clicked.connect(self._on_t3_arrow_clicked)
        self._update_t3_arrow_icon()
        lay.addWidget(self._t3_arrow_btn)
        lay.addSpacing(4)
        return bar

    def _build_history_panel(self) -> QWidget:
        """Cria o painel de histórico: FilterPanel + lista + detalhe.

        Se o DatabaseManager ainda não foi inicializado (ex: em testes),
        retorna um placeholder vazio sem levantar exceção.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.history.history_manager import HistoryManager

            history_mgr = HistoryManager(db_manager.session_factory)

            self._filter_panel = FilterPanel(parent=container)
            layout.addWidget(self._filter_panel)

            content_splitter = QSplitter(Qt.Orientation.Vertical)
            content_splitter.setChildrenCollapsible(False)

            self._history_list = ExecutionHistoryWidget(history_mgr, parent=container)
            content_splitter.addWidget(self._history_list)

            self._history_detail = ExecutionDetailPanel(history_mgr, parent=container)
            content_splitter.addWidget(self._history_detail)

            content_splitter.setSizes([300, 200])
            layout.addWidget(content_splitter, stretch=1)

            # Wire signals
            self._filter_panel.filter_changed.connect(self._history_list.apply_filter)
            self._history_list.execution_selected.connect(
                self._history_detail.load_execution
            )

        except RuntimeError:
            # db_manager not yet initialized (e.g. during tests without setup())
            from PySide6.QtWidgets import QLabel
            placeholder = QLabel("Histórico disponível após inicialização do banco.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        return container

    def _setup_shortcuts(self) -> None:
        save_queue = QAction("Salvar Fila", self)
        save_queue.setShortcut(QKeySequence("Ctrl+S"))
        save_queue.triggered.connect(self._on_save_queue)
        self.addAction(save_queue)

    def _toggle_terminal_layout(self) -> None:
        """Toggle terminal splitter between vertical (column) and horizontal (row)."""
        if self._terminal_is_vertical:
            self._terminal_splitter.setOrientation(Qt.Orientation.Horizontal)
            self._layout_toggle_btn.setIcon(self._layout_icon_stacked)
            self._layout_toggle_btn.setToolTip("Layout: lado a lado. Clique para empilhar")
            self._terminal_is_vertical = False
        else:
            self._terminal_splitter.setOrientation(Qt.Orientation.Vertical)
            self._layout_toggle_btn.setIcon(self._layout_icon_side)
            self._layout_toggle_btn.setToolTip("Layout: empilhado. Clique para lado a lado")
            self._terminal_is_vertical = True
        self._update_collapse_chevron()
        # Inner workspace splitter (T2 + T3) must remain perpendicular to outer.
        self._apply_workspace_inner_orientation()
        self._update_t3_arrow_icon()

    def _toggle_workspace_collapse(self) -> None:
        """Toggle collapse/expand of the workspace terminal."""
        if self._workspace_collapsed:
            self._workspace_wrapper.show()
            if hasattr(self, "_saved_splitter_sizes"):
                self._terminal_splitter.setSizes(self._saved_splitter_sizes)
            else:
                self._terminal_splitter.setSizes([350, 350])
            self._workspace_collapsed = False
            self._collapse_chevron.setToolTip("Colapsar terminal Workspace")
        else:
            self._saved_splitter_sizes = self._terminal_splitter.sizes()
            self._workspace_wrapper.hide()
            self._workspace_collapsed = True
            self._collapse_chevron.setToolTip("Expandir terminal Workspace")
        self._update_collapse_chevron()

    def _update_collapse_chevron(self) -> None:
        """Update chevron icon based on layout and collapsed state."""
        if self._terminal_is_vertical:
            text = "\u25B2" if self._workspace_collapsed else "\u25BC"
        else:
            text = "\u25C4" if self._workspace_collapsed else "\u25BA"
        self._collapse_chevron.setText(text)

    # ── T3 (pyte) arrow toggle (2026-05-19) ───────────────────────────── #
    def _apply_workspace_inner_orientation(self) -> None:
        """Reorienta _workspace_terminal_splitter perpendicular ao _terminal_splitter.

        - _terminal_is_vertical = True  (T1+T2 column) -> inner Horizontal
        - _terminal_is_vertical = False (T1+T2 row)    -> inner Vertical
        Ajusta sizes conforme _t3_visible.
        """
        if not hasattr(self, "_workspace_terminal_splitter"):
            return
        if self._terminal_is_vertical:
            self._workspace_terminal_splitter.setOrientation(Qt.Orientation.Horizontal)
        else:
            self._workspace_terminal_splitter.setOrientation(Qt.Orientation.Vertical)
        self._apply_workspace_split_sizes()

    def _apply_workspace_split_sizes(self) -> None:
        """Aplica split do workspace sem substituir terminais.

        child 0 = T2 (pyte), child 1 = T3 (pyte). Regra (so 2 estados):
        - T3 expandido -> 50/50 exato entre T2 e T3
        - T3 colapsado -> T2 ocupa 100%, T3 fica em 0
        T3 NUNCA ocupa a area inteira.
        """
        if not hasattr(self, "_workspace_terminal_splitter"):
            return
        splitter = self._workspace_terminal_splitter
        if splitter.orientation() == Qt.Orientation.Vertical:
            total = max(0, splitter.height() - splitter.handleWidth())
        else:
            total = max(0, splitter.width() - splitter.handleWidth())
        if total <= 0:
            # Layout ainda nao estabilizou; fallback proporcional.
            splitter.setSizes([1, 1] if getattr(self, "_t3_visible", False) else [1, 0])
            return
        if getattr(self, "_t3_visible", False):
            second = total // 2
            first = total - second
            splitter.setSizes([first, second])
        else:
            splitter.setSizes([total, 0])

    def _update_t3_arrow_icon(self) -> None:
        if not hasattr(self, "_t3_arrow_btn"):
            return
        visible = getattr(self, "_t3_visible", False)
        if self._terminal_is_vertical:
            text = "▶" if visible else "◀"
        else:
            text = "▼" if visible else "▲"
        tip = (
            "Colapsar terminal 3 (Codex)"
            if visible
            else "Expandir terminal 3 (Codex) em 50/50"
        )
        self._t3_arrow_btn.setText(text)
        self._t3_arrow_btn.setToolTip(tip)

    def _on_t3_arrow_clicked(self) -> None:
        self._t3_visible = not getattr(self, "_t3_visible", False)
        self._apply_workspace_inner_orientation()
        self._update_t3_arrow_icon()

    def _connect_signals(self) -> None:
        self._command_queue.add_command_requested.connect(self._open_add_command)
        self._command_queue.reorder_requested.connect(self._on_queue_reorder_requested)
        self._command_queue.save_requested.connect(self._on_save_queue)
        self._metrics_bar.view_changed.connect(self._on_view_changed)
        self._metrics_bar.project_config_change_requested.connect(
            self._on_project_config_change_requested
        )
        self._metrics_bar.loop_config_change_requested.connect(
            self._on_loop_config_change_requested
        )
        self._metrics_bar.config_change_requested.connect(
            self._on_config_change_requested
        )
        self._metrics_bar.loop_config_unload_requested.connect(
            self._unload_loop_config
        )
        self._metrics_bar.loop_config_reload_requested.connect(
            self._reload_loop_config
        )
        signal_bus.toast_requested.connect(self._show_toast)
        signal_bus.pipeline_ready.connect(self._on_pipeline_ready)
        signal_bus.history_panel_toggled.connect(self._switch_to_history_tab)
        signal_bus.pipeline_started.connect(self._switch_to_output_tab)
        # Task 3 (loop 05-13-workflow-app-layout-2): migrado para signal granular
        # com modos `off`/`main`/`body`/`buttons`. `datatest_toggled` mantido em
        # signal_bus por compat mas nao mais emitido pela UI.
        signal_bus.datatest_mode_changed.connect(self._on_datatest_mode_changed)
        signal_bus.focus_interactive_terminal.connect(self._on_focus_interactive_terminal)
        signal_bus.run_command_in_workspace_xterm.connect(
            lambda text: self._xterm_inject_text(text, with_enter=True)
        )
        signal_bus.pipeline_completed.connect(self._refresh_history_list)
        signal_bus.permission_request_received.connect(self._on_permission_request)
        # _btn_new removed — pipeline creator accessible via command queue or Ctrl+N
        # RF10: Dry Run handler
        signal_bus.dry_run_requested.connect(self._on_dry_run)
        # RF03: Pipeline execution control (guarded to prevent signal recursion)
        signal_bus.pipeline_paused.connect(self._on_pipeline_paused_for_pm)
        signal_bus.pipeline_resumed.connect(self._on_pipeline_resumed_for_pm)
        signal_bus.pipeline_retry_requested.connect(self._on_pipeline_retry_requested)
        signal_bus.pipeline_cancelled.connect(self._on_pipeline_cancel_for_pm)

    # ─────────────────────────────────────────────────────── State ───── #

    def _save_state(self) -> None:
        self._settings.setValue(self._SETTINGS_GEOMETRY, self.saveGeometry())
        self._settings.setValue(self._SETTINGS_SPLITTER, self._splitter.sizes())

    def _restore_state(self) -> None:
        geometry = self._settings.value(self._SETTINGS_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
        splitter_sizes = self._settings.value(self._SETTINGS_SPLITTER)
        if splitter_sizes:
            try:
                self._splitter.setSizes([int(s) for s in splitter_sizes])
            except (ValueError, TypeError):
                pass

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._settings.value(self._SETTINGS_SPLITTER):
            total = self._splitter.width()
            if total > 0:
                self._splitter.setSizes([total // 3, total * 2 // 3])

    def closeEvent(self, event) -> None:  # noqa: N802
        # T-037: release the cooperative lock BEFORE saving state so the
        # filesystem lock is relinquished even if persistence blows up.
        # release_and_stop() is idempotent and never raises, but we wrap
        # it defensively so a regression cannot prevent app shutdown.
        try:
            self._lock_service.release_and_stop()
        except Exception:  # noqa: BLE001
            logger.exception("closeEvent: failed to release cooperative lock")
        self._save_state()
        super().closeEvent(event)

    def _on_lock_lost(self, reason: str) -> None:
        """Slot for LockService.lock_lost — surface a toast to the user.

        T-037: in API-only mode, no flow actively holds the lock, so this
        slot is mostly a safety net for future T-038 edit flows. We keep
        the wiring now so the contract is stable from day one.
        """
        logger.warning("MainWindow: cooperative lock lost: %s", reason)
        signal_bus.toast_requested.emit(
            "Lock cooperativo perdido — outra instancia assumiu delivery.json",
            "error",
        )

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _open_add_command(self) -> None:
        next_pos = len(self._command_queue._items) + 1
        dialog = AddCommandDialog(next_position=next_pos, parent=self)
        dialog.command_added.connect(self._on_command_added)
        dialog.exec()

    def _on_pipeline_ready(self, commands: list[CommandSpec]) -> None:
        # Annotate each spec with the relative config path when a project is loaded.
        # Comandos /boilerplate:* recebem config_path pre-setado pelo handler
        # (repo_path no scan, staging_path nos demais) e NAO devem ser sobrescritos
        # pelo project.json. Para os demais comandos mantemos o comportamento legado
        # (anotar com a config relativa) para nao regredir templates customizados.
        if app_state.has_config and app_state.config:
            import os
            abs_config = app_state.config.config_path
            project_dir = str(app_state.config.project_dir)
            try:
                rel = os.path.relpath(abs_config, project_dir)
            except ValueError:
                rel = abs_config
            for spec in commands:
                if spec.name.startswith("/model ") or spec.name.startswith("/effort ") or spec.name == "/clear":
                    continue  # model-switch, /effort and /clear rows must never carry a config path
                if spec.name.startswith("/boilerplate:"):
                    continue  # respeita config_path pre-setado por _on_boilerplate_clicked
                if spec.name.startswith("/auto-improove:"):
                    continue  # auto-improove opera sobre o proprio SystemForge, sem project.json
                if spec.name.startswith("/blog:"):
                    continue  # blog opera sobre o proprio SystemForge, sem project.json
                if spec.name.startswith("/cmd:"):
                    continue  # /cmd:* sao META commands do SystemForge, nao dependem de project.json
                spec.config_path = rel

        self._command_queue.load_pipeline(commands)
        # NOTE: do NOT emit signal_bus.pipeline_ready here — it is connected back
        # to this slot and would cause infinite recursion.
        signal_bus.pipeline_created.emit(commands)

        # RF03: Instantiate PipelineManager for this pipeline session.
        from workflow_app.db.database_manager import db_manager
        from workflow_app.pipeline.pipeline_manager import PipelineManager
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        adapter = SDKAdapter()
        # cwd = raiz da systemForge (onde está .claude/commands/) para que os
        # slash commands sejam encontrados pelo claude-agent-sdk
        if app_state.has_config:
            workspace = str(app_state.config.project_dir)
        else:
            # Detect systemForge root by walking up from cwd looking for .claude/commands/
            from pathlib import Path
            _cwd = Path.cwd()
            workspace = str(_cwd)
            for p in [_cwd, *_cwd.parents]:
                if (p / ".claude" / "commands").is_dir() and (p / "CLAUDE.md").is_file():
                    workspace = str(p)
                    break
        self._pipeline_manager = PipelineManager(
            signal_bus=signal_bus,
            sdk_adapter=adapter,
            session_factory=db_manager.session_factory,
            workspace_dir=workspace,
        )
        self._pipeline_manager.set_queue(commands)
        self._command_queue.set_pipeline_manager(self._pipeline_manager)

        self._show_toast(
            f"Pipeline carregado: {len(commands)} comandos", "success"
        )

    def _on_command_added(self, spec: CommandSpec) -> None:
        # RESOLVED: G001 — append to existing queue
        self._command_queue.add_command(spec)
        self._show_toast(f"Comando adicionado: {spec.name}", "success")

    def _on_project_config_change_requested(self, path: str) -> None:
        """Handle project selection from metrics bar."""
        self._load_config(path, config_kind="project")
        if app_state.project_config and app_state.project_config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Projeto carregado: {app_state.project_name}", "success"
            )

    def _on_loop_config_change_requested(self, path: str) -> None:
        """Handle loop selection from metrics bar."""
        self._load_config(path, config_kind="loop")
        if app_state.loop_config and app_state.loop_config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Loop carregado: {app_state.loop_config.project_name}", "success"
            )

    def _on_config_change_requested(self, path: str) -> None:
        """Handle legacy config change requests from ConfigBar/MetricsBar."""
        if (
            (app_state.project_config and app_state.project_config.config_path == path)
            or (app_state.loop_config and app_state.loop_config.config_path == path)
        ):
            return
        self._load_config(path)

        if app_state.loop_config and app_state.loop_config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Loop carregado: {app_state.loop_config.project_name}", "success"
            )
            return
        if app_state.project_config and app_state.project_config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Projeto carregado: {app_state.project_name}", "success"
            )

    def _on_view_changed(self, index: int) -> None:
        """Switch the main view stack (0=Workflow, 2=Kanban, 3=ModuleDetail).

        Index 1 (Comandos) is blocked — nav buttons are hidden and the
        workflow view is permanently active.
        """
        if index == 1:
            return
        self._view_stack.setCurrentIndex(index)
        if self._datatest_active:
            self._show_testid_overlays()

    def _switch_to_output_tab(self) -> None:
        """Switch to Workflow view (output container is the only left pane)."""
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)

    def _switch_to_history_tab(self) -> None:
        """No-op since the Histórico tab was eliminated (refactor 2026-05-12).

        Kept as a stub because signal_bus.history_panel_toggled still exists
        and may be wired by remote/legacy code paths.
        """
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)

    def _refresh_history_list(self) -> None:
        """No-op stub; the history panel is no longer mounted in the UI."""
        return

    def _show_toast(self, message: str, msg_type: str = "info") -> None:
        self._toast_notifier.show(message, msg_type)

    # ─────────────────────────────────── DataTest overlay & terminal focus ─ #

    def _on_focus_interactive_terminal(self) -> None:
        """Switch to output tab and focus the interactive terminal."""
        self._switch_to_output_tab()
        self._output_panel._terminal.setFocus()

    def _on_datatest_toggled(self, enabled: bool) -> None:
        """Compat legado: roteia para o novo handler de modo.

        Mantido caso codigo externo ainda emita `signal_bus.datatest_toggled`.
        Mapeia `True` para `"main"` (subset curado) — comportamento original
        do antigo botao DataTest (que filtrava por _DATATEST_FILTERED_IDS).
        """
        self._on_datatest_mode_changed("main" if enabled else "off")

    def _on_datatest_mode_changed(self, mode: str) -> None:
        """Handler de modo test-mode.

        Modos validos:
        - `off`     : sem overlays.
        - `main`    : subset curado em `_DATATEST_FILTERED_IDS`.
        - `key`     : alias legado de `main`.
        - `body`    : tudo MENOS QAbstractButton.
        - `buttons` : APENAS QAbstractButton.
        """
        if mode == "key":
            mode = "main"
        if mode not in ("off", "main", "body", "buttons"):
            mode = "off"
        self._datatest_mode = mode
        self._datatest_active = mode != "off"
        if mode == "off":
            self._hide_testid_overlays()
        else:
            self._show_testid_overlays()

    def _show_testid_overlays(self) -> None:
        """Walk child widgets of the active tab and show floating red testid overlay labels.

        Only scans widgets within the currently selected view tab
        (0=Workflow, 1=Comandos, 2=Kanban, 3=ModuleDetail) plus the shared MetricsBar.
        Overlays are parented to the central widget so they float beyond
        their target widget bounds. Click an overlay to copy its text.
        """
        self._hide_testid_overlays()
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication as _QApp
        from PySide6.QtWidgets import QLabel as _Lbl

        central = self.centralWidget()
        used_positions: list[tuple[int, int, int, int]] = []  # x, y, w, h

        _STYLE_NORMAL_BODY = (
            "background-color: rgba(220, 38, 38, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )
        _STYLE_NORMAL_BUTTON = (
            "background-color: rgba(37, 99, 235, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )
        _STYLE_COPIED = (
            "background-color: rgba(34, 197, 94, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )

        # Only scan the active view's widget + metrics bar
        active_page = self._view_stack.currentWidget()
        scan_roots = [active_page, self._metrics_bar]
        scan_widgets: list[QWidget] = []
        for root in scan_roots:
            if root:
                scan_widgets.append(root)
                scan_widgets.extend(root.findChildren(QWidget))

        # Task 3 (loop 05-13-workflow-app-layout-2): filtragem por modo test-mode.
        from PySide6.QtWidgets import QAbstractButton as _AbsBtn

        _mode = getattr(self, "_datatest_mode", "main")
        for widget in scan_widgets:
            testid = widget.property("testid")
            if not testid or widget.property("_is_testid_overlay"):
                continue
            _is_btn = isinstance(widget, _AbsBtn)
            if _mode == "body" and _is_btn:
                continue
            if _mode == "buttons" and not _is_btn:
                continue
            if testid and not widget.property("_is_testid_overlay"):
                # Skip widgets that aren't visible on screen
                if not widget.isVisible() or not widget.isVisibleTo(central):
                    continue
                testid_str = str(testid)
                # Modo "main" = subset curado; "body"/"buttons" sem filtro
                # adicional alem do _is_btn ja aplicado acima.
                if _mode == "main" and testid_str not in _DATATEST_FILTERED_IDS:
                    continue

                # Map widget position to central widget coordinates
                # Offset badges slightly above the target widget
                try:
                    pos = widget.mapTo(central, QPoint(0, 0))
                except RuntimeError:
                    continue
                x, y = pos.x(), pos.y() - 14

                # Offset if overlapping with existing overlay
                for ux, uy, uw, uh in used_positions:
                    if abs(x - ux) < max(uw, 30) and abs(y - uy) < max(uh, 18):
                        y = uy + uh + 2

                overlay = _Lbl(testid_str, central)
                normal_style = _STYLE_NORMAL_BUTTON if _is_btn else _STYLE_NORMAL_BODY
                overlay.setStyleSheet(normal_style)
                overlay.setProperty("_is_testid_overlay", True)
                overlay.setCursor(Qt.CursorShape.PointingHandCursor)
                overlay.setToolTip(f"Clique para copiar: {testid_str}")

                # Click to copy to clipboard with visual feedback
                def _make_click(lbl, text, style):
                    def _handler(_event):
                        _QApp.clipboard().setText(f'data-testid="{text}"')
                        if self._datatest_terminal_write_enabled:
                            self._send_testid_probe_to_selected_terminal(text)
                        lbl.setStyleSheet(_STYLE_COPIED)
                        QTimer.singleShot(600, lambda: lbl.setStyleSheet(style))
                    return _handler

                overlay.mousePressEvent = _make_click(overlay, testid_str, normal_style)

                overlay.adjustSize()
                overlay.move(x, y)
                overlay.show()
                overlay.raise_()
                used_positions.append((x, y, overlay.width(), overlay.height()))
                self._testid_overlays.append(overlay)

    def _hide_testid_overlays(self) -> None:
        """Remove all testid overlay labels."""
        for overlay in self._testid_overlays:
            overlay.hide()
            overlay.deleteLater()
        self._testid_overlays.clear()

    def _reposition_modal_test_btn(self) -> None:
        parent = self._active_modal_dialog or self.centralWidget()
        if parent and self._modal_test_btn:
            btn_w = self._modal_test_btn.width() or 80
            self._modal_test_btn.move(parent.width() - btn_w - 8, 8)

    def _on_modal_test_toggled(self, checked: bool) -> None:
        if checked:
            self._show_modal_testid_overlays()
        else:
            self._hide_modal_testid_overlays()

    def _show_modal_testid_overlays(self) -> None:
        self._hide_modal_testid_overlays()
        if not self._active_modal_dialog:
            return
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication as _QApp
        from PySide6.QtWidgets import QLabel as _Lbl

        dlg = self._active_modal_dialog
        overlay_parent = dlg
        used_positions: list[tuple[int, int, int, int]] = []

        _STYLE_NORMAL = (
            "background-color: rgba(124, 58, 237, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )
        _STYLE_COPIED = (
            "background-color: rgba(34, 197, 94, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 3px 6px;"
            " border-radius: 3px; border: none;"
        )

        scan_widgets: list = [dlg]
        scan_widgets.extend(dlg.findChildren(QWidget))

        for widget in scan_widgets:
            testid = widget.property("testid")
            if not testid or widget.property("_is_testid_overlay"):
                continue
            testid_str = str(testid)
            # Renderiza TODOS os testids visiveis dentro do modal (os itens
            # reais do dialog). Antes havia um allowlist estatico curado
            # (`_MODAL_TESTIDS`) que vivia defasado: qualquer modal novo — ou
            # qualquer item nao catalogado — caia fora do set e o botao ModalTest
            # nao mostrava nada (onClick sem efeito). Igual ao overlay nao-modal
            # (`_show_testid_overlays`), agora mostramos tudo que tem testid e
            # esta visivel dentro do dialog.
            if not widget.isVisible():
                continue
            try:
                pos = widget.mapTo(overlay_parent, QPoint(0, 0))
            except RuntimeError:
                continue
            x, y = pos.x(), pos.y() - 14
            for ux, uy, uw, uh in used_positions:
                if abs(x - ux) < max(uw, 30) and abs(y - uy) < max(uh, 18):
                    y = uy + uh + 2
            overlay = _Lbl(testid_str, overlay_parent)
            overlay.setStyleSheet(_STYLE_NORMAL)
            overlay.setProperty("_is_testid_overlay", True)
            overlay.setCursor(Qt.CursorShape.PointingHandCursor)
            overlay.setToolTip(f"Clique para copiar: {testid_str}")

            def _make_click(lbl, text):
                def _handler(_event):
                    _QApp.clipboard().setText(f'data-testid="{text}"')
                    lbl.setStyleSheet(_STYLE_COPIED)
                    QTimer.singleShot(600, lambda: lbl.setStyleSheet(_STYLE_NORMAL))
                return _handler

            overlay.mousePressEvent = _make_click(overlay, testid_str)
            overlay.adjustSize()
            overlay.move(x, y)
            overlay.show()
            overlay.raise_()
            used_positions.append((x, y, overlay.width(), overlay.height()))
            self._modal_test_overlays.append(overlay)
        self._modal_test_btn.raise_()

    def _hide_modal_testid_overlays(self) -> None:
        for overlay in self._modal_test_overlays:
            overlay.hide()
            overlay.deleteLater()
        self._modal_test_overlays.clear()

    def _check_for_active_modal(self) -> None:
        from PySide6.QtWidgets import QApplication, QDialog
        active = None
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                active = w
                break
        if active is not self._active_modal_dialog:
            self._active_modal_dialog = active
            if active:
                if self._modal_test_btn.parent() is not active:
                    self._modal_test_btn.setParent(active)
                self._modal_test_btn.setVisible(True)
                self._reposition_modal_test_btn()
                self._modal_test_btn.raise_()
                if self._modal_test_btn.isChecked():
                    self._show_modal_testid_overlays()
            else:
                self._modal_test_btn.setVisible(False)
                self._modal_test_btn.setChecked(False)
                self._hide_modal_testid_overlays()
                central = self.centralWidget()
                if central and self._modal_test_btn.parent() is not central:
                    self._modal_test_btn.setParent(central)
        elif active:
            self._reposition_modal_test_btn()
            self._modal_test_btn.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, '_modal_test_btn') and self._modal_test_btn.isVisible():
            self._reposition_modal_test_btn()
        if self._datatest_panel is not None and self._datatest_panel.isVisible():
            self._position_datatest_panel()
        self._reposition_px_ruler_toasts()

    def _on_permission_request(self, request_data: dict) -> None:
        """Show PermissionRequestDialog when the SDK needs user approval."""
        from workflow_app.dialogs.permission_request_dialog import (
            PermissionRequestDialog,
        )
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        dlg = PermissionRequestDialog(parent=self, request_data=request_data)

        # Route permission response to the active PipelineManager's SDKAdapter.
        sdk_adapter: SDKAdapter | None = None
        if self._pipeline_manager is not None:
            sdk_adapter = self._pipeline_manager._sdk_adapter

        def _on_granted() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(True)

        def _on_rejected() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(False)
            self._show_toast("Permissão rejeitada.", "warning")

        dlg.permission_granted.connect(_on_granted)
        dlg.permission_rejected.connect(_on_rejected)
        dlg.exec()

    # ──────────────────────────────────────────── Config detection ──── #

    def _attempt_startup_detection(self) -> None:
        """Inicia SEMPRE em "modo sem projeto" — nenhum JSON carregado.

        Decisao de seguranca multi-instance (2026-05-31): o workflow-app roda
        em multiplas instancias sobre o mesmo working tree. Auto-carregar o
        ultimo project.json (via QSettings) ou auto-detectar via detect_config()
        no startup faz uma instancia recem-aberta herdar o projeto + a fila
        (queue-command-list) de outra sessao, criando o risco real de comecar
        a rodar a pipeline errada contra o projeto errado.

        Portanto o startup NAO carrega nada:
        - metrics-project-pill fica sem selecao (_apply_project_empty, via
          MetricsBar.__init__ ao ver app_state sem config);
        - queue-command-list fica vazio (so e populado por _load_config ->
          _restore_queue_from_storage, que nunca roda aqui);
        - o usuario seleciona explicitamente o JSON na pill (_on_proj_select /
          _on_loop_select / _on_proj_open), tornando a escolha de contexto um
          ato consciente por instancia.

        O ultimo config continua persistido em QSettings
        (self._SETTINGS_LAST_CONFIG, gravado por _load_config) apenas como
        registro/conveniencia do seletor — nunca para auto-load.
        """
        logger.info(
            "Startup em modo sem projeto (multi-instance safety): nenhum "
            "config auto-carregado; aguardando selecao manual na "
            "metrics-project-pill."
        )
        self._update_title(project_name=None)

    def _load_config(self, path: str, *, config_kind: str | None = None) -> None:
        """Carrega uma configuração e atualiza o estado da aplicação.

        Emite signal_bus.config_loaded em caso de sucesso.
        Exibe toast de erro em caso de falha.

        Side-effects de "projeto" (restore de queue + load de Kanban) sao
        suprimidos quando o JSON e um loop config (`kind=daily-loop` +
        `daily_loop`, ou `iteration_template`+`items`+`finalization`).
        Loop configs sao artefatos de pipeline, nao tem queue persistente
        nem modulos para o Kanban — restaurar dispara reads silenciosos
        de paths invalidos e polui a UI com estado de outro projeto.
        """
        try:
            config = parse_config(path)
        except (ConfigError, FileNotFoundError) as exc:
            logger.error("Falha ao carregar config '%s': %s", path, exc)
            signal_bus.toast_requested.emit(
                f"Falha ao carregar config: {exc.message if isinstance(exc, ConfigError) else str(exc)}",
                "error",
            )
            return

        raw = config.raw if isinstance(config.raw, dict) else {}

        # Compatibilidade por slot:
        # - config_kind="project" => ProjectConfig slot
        # - config_kind="loop"   => LoopConfig slot
        # - vazio                => autodetecção por shape de payload
        # Sem quebrar consumidores antigos de compatibilidade, também atualiza
        # set_config alias no fim deste bloco.
        is_loop_json_config = (
            (raw.get("kind") == "daily-loop" and "daily_loop" in raw)
            or (
                "iteration_template" in raw
                and "items" in raw
                and "finalization" in raw
            )
        )
        is_loop_attachment = False
        if config_kind == "loop":
            is_loop_attachment = True
        elif config_kind is None and is_loop_json_config:
            is_loop_attachment = True

        if is_loop_attachment:
            app_state.set_loop_config(config)
            logger.debug("Config carregado como loop: %s", path)
        elif config_kind == "project":
            app_state.set_project_config(config)
            logger.debug("Config carregado como projeto: %s", path)
        else:
            app_state.set_project_config(config)
            logger.debug("Config carregado por autodetecao como projeto: %s", path)
        # compat: manter alias legado para fluxos que ainda fazem write-only em
        # app_state.config sem escolher explicitamente project/loop. Para loop,
        # NAO escrever no alias: a facade derivada ja retorna loop quando nao ha
        # project, e escrever aqui sobrescreveria o slot de project.
        if not is_loop_attachment:
            app_state.set_config(config)
            self._update_title(project_name=config.project_name)
            self._settings.setValue(self._SETTINGS_LAST_CONFIG, path)
        signal_bus.config_loaded.emit(path)
        logger.info("Config carregado: projeto=%s", config.project_name)
        self._check_template_versions()  # RESOLVED: G002

        if is_loop_attachment:
            logger.info(
                "Config '%s' identificada como loop config — skip "
                "_restore_queue_from_storage + _load_kanban_from_config.",
                path,
            )
            return

        self._restore_queue_from_storage(path)
        if config.wbs_root:
            self._load_kanban_from_config(config)
        else:
            logger.info(
                "wbs_root vazio em '%s' — skip _load_kanban_from_config.",
                path,
            )

    def _check_template_versions(self) -> None:
        """Check if factory templates are aligned with the current CLAUDE.md.  # RESOLVED: G002"""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            from workflow_app.templates.version_checker import VersionChecker

            self._version_checker_mgr = TemplateManager(db_manager)
            self._version_checker = VersionChecker(self._version_checker_mgr)
            result = self._version_checker.check_factory_templates()
            if result.is_outdated:
                self._version_banner.set_outdated_names(result.outdated_names)
                self._version_banner.setVisible(True)
        except Exception:
            pass  # version check is non-critical

    def _on_version_update_requested(self) -> None:
        """Refresh factory templates with the current CLAUDE.md hash."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.claude_md_hasher import compute_hash, find_claude_md
            from workflow_app.templates.factory_templates import refresh_factory_templates

            path = find_claude_md()
            new_hash = compute_hash(path) if path else None
            if new_hash:
                refresh_factory_templates(db_manager, new_hash)
                self._show_toast("Templates de fábrica atualizados.", "success")
            else:
                self._show_toast("CLAUDE.md não encontrado. Atualização cancelada.", "warning")
        except Exception as exc:
            logger.error("Erro ao atualizar templates de fábrica: %s", exc)
            self._show_toast("Falha ao atualizar templates.", "error")

    # ─────────────────────────────────── RF03: Pipeline execution control ─── #

    def _on_run_requested(self) -> None:
        """Called when ▶ is clicked — starts the active PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.start()

    def _on_pipeline_paused_for_pm(self) -> None:
        """Guard-wrapped pause: prevents signal recursion (pm.pause() re-emits pipeline_paused)."""
        pm = self._pipeline_manager
        if pm is not None and not pm._paused:
            pm.pause()

    def _on_pipeline_resumed_for_pm(self) -> None:
        """Guard-wrapped resume: prevents signal recursion (pm.resume() re-emits pipeline_resumed)."""
        pm = self._pipeline_manager
        if pm is not None and pm._paused:
            pm.resume()

    def _on_pipeline_retry_requested(self, _index: int) -> None:
        """Retry the current ERRO command via PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.retry_current()

    def _on_pipeline_cancel_for_pm(self) -> None:
        """Cancel the active pipeline, then clear the manager reference."""
        pm = self._pipeline_manager
        if pm is not None and pm._pipeline_exec_id is not None:
            self._pipeline_manager = None  # clear first to prevent re-entry
            pm.cancel()

    def _on_queue_reorder_requested(self, from_pos: int, to_pos: int) -> None:
        """Handle drag-and-drop reorder from CommandQueueWidget."""
        if self._pipeline_manager is None:
            return
        success = self._pipeline_manager.reorder_command(from_pos, to_pos)
        if success:
            self._refresh_queue_ui()

    def _refresh_queue_ui(self) -> None:
        """Reload the queue display from the pipeline manager's current queue."""
        if self._pipeline_manager is None:
            return
        self._command_queue.load_pipeline(self._pipeline_manager._queue)

    # ──────────────────────────────────────── RF10: Dry Run handler ─────── #

    def _on_dry_run(self) -> None:
        """Validate the current command queue offline via DryRunValidator."""
        from workflow_app.dry_run import DryRunValidator

        commands = [item.get_spec() for item in self._command_queue._items]
        if not commands:
            self._show_toast("Nenhum comando na fila para validar.", "warning")
            return

        report = DryRunValidator().validate(commands)
        if report.is_valid:
            warnings = len(report.warnings)
            msg = f"Dry Run: OK — {len(commands)} comando(s) válido(s)."
            if warnings:
                msg += f" {warnings} aviso(s)."
            self._show_toast(msg, "success")
        else:
            errors = len(report.errors)
            self._show_toast(
                f"Dry Run: {errors} erro(s) encontrado(s). Verifique a fila.", "warning"
            )

    # ──────────────────────────────────── RF11: Resume interrupted pipeline ─ #

    def _check_for_interrupted_pipeline(self) -> None:
        """After loading config, offer to resume an interrupted pipeline (RF11)."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.db.models import CommandExecution, PipelineExecution
            from workflow_app.dialogs.resume_dialog import ResumeDialog, ResumeInfo
            from workflow_app.domain import CommandStatus
            from workflow_app.pipeline.pipeline_manager import PipelineManager
            from workflow_app.sdk.sdk_adapter import SDKAdapter

            adapter = SDKAdapter()
            pm = PipelineManager(
                signal_bus=signal_bus,
                sdk_adapter=adapter,
                session_factory=db_manager.session_factory,
            )
            interrupted_id = pm.check_resume()
            if interrupted_id is None:
                return

            with db_manager.session_factory() as session:
                pipeline = session.get(PipelineExecution, interrupted_id)
                if pipeline is None:
                    return

                cmds = (
                    session.query(CommandExecution)
                    .filter_by(pipeline_id=interrupted_id)
                    .order_by(CommandExecution.position)
                    .all()
                )
                completed = [c for c in cmds if c.status == CommandStatus.CONCLUIDO.value]
                uncertain = next(
                    (c for c in cmds if c.status == CommandStatus.INCERTO.value), None
                )
                pending = [c for c in cmds if c.status == CommandStatus.PENDENTE.value]

                info = ResumeInfo(
                    pipeline_exec_id=interrupted_id,
                    last_completed_command=completed[-1].command_name if completed else None,
                    uncertain_command=uncertain.command_name if uncertain else None,
                    pending_count=len(pending),
                    total_count=len(cmds),
                    completed_count=len(completed),
                    interrupted_at=pipeline.started_at or pipeline.created_at,
                )

            dlg = ResumeDialog(info, parent=self)
            result = dlg.exec()
            choice = dlg.user_choice()

            if result == ResumeDialog.RESULT_REEXECUTE:
                self._show_toast("Selecione o pipeline para retomar a execução.", "info")
            elif choice == ResumeDialog.RESULT_SKIP:
                self._show_toast("Pipeline interrompido ignorado.", "info")
            # RESULT_CANCEL: do nothing

        except Exception:
            pass  # resume check is non-critical; never block startup

    def _on_save_queue(self) -> None:
        """Salva snapshot da fila + metadados no storage dedicado queue_root.

        Grava em `output/wbs/pipeline-position/{slug}.json` via
        `write_queue_root` (atomic: tmp + os.replace). Consumido por
        `_restore_queue_from_storage` no startup.

        Para `last_command`, se o valor for `/model` ou `/clear`, anda para
        tras na fila buscando o ultimo comando real.
        """
        from datetime import datetime
        from pathlib import Path

        from workflow_app.services.queue_storage import write_queue_root

        if not app_state.has_config or not app_state.config:
            self._show_toast("Nenhum projeto carregado.", "warning")
            return

        commands = self._command_queue.get_queue_snapshot()
        template_label = self._command_queue.get_template_label_text()
        last_command = self._command_queue.get_last_command_text()

        if not commands and not template_label and not last_command:
            self._show_toast("Nada a salvar (fila vazia).", "warning")
            return

        # If last_command is /model or /clear, find the previous valid command
        _skip = ("/model", "/clear")
        if last_command:
            cmd_lower = last_command.strip().split("\n")[0].strip().lower()
            if any(cmd_lower.startswith(s) for s in _skip) or cmd_lower == "/clear":
                last_command = self._command_queue.find_last_valid_command()

        queue_root_path = Path(app_state.config.project_dir) / app_state.config.queue_root
        data = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "template_label": template_label,
            "last_command": last_command,
            "commands": commands,
        }

        try:
            write_queue_root(queue_root_path, data)
            self._show_toast(
                f"Fila salva: {len(commands)} comandos"
                + (f" — {template_label}" if template_label else ""),
                "success",
            )
        except Exception as exc:
            self._show_toast(f"Erro ao salvar fila: {exc}", "error")

    def _on_clear_queue_clicked(self) -> None:
        """Esvazia o queue-command-list desta instancia (botao Clear do pill-row).

        Acao destrutiva direta (sem confirmacao, conforme pedido), mas com
        feedback explicito via toast (Zero Silencio). Idempotente: clicar com
        a fila ja vazia apenas informa, sem efeito colateral.
        """
        count = len(self._command_queue.get_queue_snapshot())
        if count == 0:
            self._show_toast("Fila ja esta vazia.", "info")
            return
        self._command_queue.clear_queue()
        self._show_toast(f"Fila esvaziada: {count} comandos removidos.", "success")

    def _restore_queue_from_storage(self, config_path: str) -> None:
        """Restaura fila do storage dedicado queue_root, se existir."""
        from pathlib import Path

        from workflow_app.services.queue_storage import read_queue_root

        if not app_state.has_config or not app_state.config:
            return

        queue_root_path = Path(app_state.config.project_dir) / app_state.config.queue_root
        queue_data = read_queue_root(queue_root_path)

        commands = queue_data.get("commands")
        if not commands:
            return

        self._command_queue.restore_queue_snapshot(commands)

        saved_at = queue_data.get("saved_at", "")[:16].replace("T", " ")
        self._show_toast(
            f"Fila restaurada: {len(commands)} comandos (salva {saved_at})", "info"
        )

    def _unload_config(self) -> None:
        """Desvincula o projeto atual.

        Emite signal_bus.config_unloaded (escopo project-only) para que os
        consumidores nao-metrics-bar reajam ao unload de projeto: config_bar
        (_on_config_unloaded) e a governanca da command queue
        (_on_config_unloaded_for_governance). O slot de loop e preservado
        (clear_project granular); por isso metrics_bar nao conecta
        config_unloaded a _apply_loop_empty (loop tem path proprio em
        _unload_loop_config).
        """
        app_state.clear_project()
        self._metrics_bar._apply_project_empty()
        self._settings.remove(self._SETTINGS_LAST_CONFIG)
        self._update_title(project_name=None)
        self._kanban_view.clear()
        self._module_detail_view.clear()
        signal_bus.config_unloaded.emit()
        signal_bus.toast_requested.emit("Projeto desvinculado", "info")

    def _reload_config(self, path: str) -> None:
        """Recarrega o config atual simulando unload/load sem abrir dialog."""
        if not path:
            signal_bus.toast_requested.emit(
                "Nenhum projeto carregado para atualizar.", "warning"
            )
            return
        app_state.clear_project()
        self._metrics_bar._apply_project_empty()
        self._settings.remove(self._SETTINGS_LAST_CONFIG)
        self._update_title(project_name=None)
        self._kanban_view.clear()
        self._module_detail_view.clear()
        self._load_config(path, config_kind="project")
        if app_state.has_config and app_state.config and app_state.config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Projeto atualizado: {app_state.project_name}", "success"
            )

    def _unload_loop_config(self) -> None:
        """Desvincula apenas o loop atual, preservando o project."""
        app_state.clear_loop()
        self._metrics_bar._apply_loop_empty()
        signal_bus.toast_requested.emit("Loop desvinculado", "info")

    def _reload_loop_config(self, path: str) -> None:
        """Recarrega apenas o loop atual sem tocar no project."""
        if not path:
            signal_bus.toast_requested.emit(
                "Nenhum loop carregado para atualizar.", "warning"
            )
            return
        app_state.clear_loop()
        self._metrics_bar._apply_loop_empty()
        self._load_config(path, config_kind="loop")
        if app_state.loop_config and app_state.loop_config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Loop atualizado: {app_state.loop_config.project_name}", "success"
            )

    # ─────────────────────────────────────────────── Kanban (T-036) ──── #

    def _load_kanban_from_config(self, config) -> None:
        """Populate the Kanban view with modules from the loaded project.

        Resolves ``{project_dir}/{wbs_root}`` and delegates to
        ``KanbanView.load``. Failures are logged; the kanban header surfaces
        the user-visible message itself.
        """
        try:
            wbs_abs = config.project_dir / config.wbs_root
        except (AttributeError, TypeError) as exc:
            logger.warning("Kanban: cannot resolve wbs_root: %s", exc)
            return
        self._kanban_view.load(wbs_abs)
        self._module_detail_view.set_wbs_root(wbs_abs)

    def _on_kanban_module_clicked(self, module_id: str) -> None:
        """Open the per-module detail view (T-038).

        Resolves ``module_id`` via ``ModuleDetailView.show_for`` and switches
        ``_view_stack`` to page 4. Failures surface via ``signal_bus`` toast.
        """
        try:
            self._module_detail_view.show_for(module_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("ModuleDetail: show_for(%s) failed", module_id)
            signal_bus.toast_requested.emit(
                f"Falha ao abrir módulo: {exc}", "error"
            )
            return
        self._view_stack.setCurrentIndex(3)

    def _update_title(self, project_name: str | None) -> None:
        """Atualiza a barra de título da janela.

        Com projeto: "{project_name} — SystemForge Desktop"
        Sem projeto: "SystemForge Desktop — Sem Projeto"
        """
        if project_name:
            self.setWindowTitle(f"{project_name} — SystemForge Desktop")
        else:
            self.setWindowTitle("SystemForge Desktop — Sem Projeto")


# ──────────────────────────────────────────────── Prompts config dialog ─── #


class _PromptTooltipFilter(QObject):
    """Event filter que exibe tooltip com 1 segundo de atraso ao passar o mouse."""

    def __init__(self, widget: QWidget, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        self._w = widget
        self._text = text
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._show)
        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._w:
            t = event.type()
            if t == QEvent.Type.Enter:
                self._timer.start()
            elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
                self._timer.stop()
                QToolTip.hideText()
        return False

    def _show(self) -> None:
        if self._w.underMouse():
            QToolTip.showText(
                self._w.mapToGlobal(self._w.rect().center()),
                self._text,
                self._w,
            )


class PromptsConfigDialog(QDialog):
    """Modal de configuracao de prompts da sub-aba prompts.

    Recebe a lista de entries (label+path+description) e o prompt base.
    Layout: topo = QPlainTextEdit do prompt base; abaixo = lista variavel de
    linhas (label 20% / path 50% / description 25% / X 5%); rodape = '+ adicionar'.
    collect() retorna (base_prompt, [(label, path, description), ...]).
    """

    def __init__(self, entries: list[dict], base_prompt: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar prompts")
        self.setMinimumSize(1000, 580)
        self.setProperty("testid", "prompts-config-dialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # Prompt base
        _base_lbl = QLabel("Prompt base:")
        _base_lbl.setStyleSheet("font-weight: 600;")
        outer.addWidget(_base_lbl)
        self._base_edit = QPlainTextEdit(base_prompt)
        self._base_edit.setProperty("testid", "prompts-config-base-prompt")
        self._base_edit.setMinimumHeight(80)
        self._base_edit.setMaximumHeight(100)
        self._base_edit.setPlaceholderText(
            "Prefixo enviado ao terminal antes do path do arquivo .md"
        )
        outer.addWidget(self._base_edit)

        # Cabecalho das colunas
        _header = QWidget()
        _hdr_layout = QHBoxLayout(_header)
        _hdr_layout.setContentsMargins(0, 0, 0, 0)
        _hdr_layout.setSpacing(4)
        for _txt, _stretch in [("Label", 20), ("Path / Ação", 50), ("Description", 25)]:
            _lbl = QLabel(_txt)
            _lbl.setStyleSheet("font-size: 10px; color: #71717A; font-weight: 600;")
            _hdr_layout.addWidget(_lbl, _stretch)
        _hdr_layout.addWidget(QLabel(""), 5)
        outer.addWidget(_header)

        # Botões fixos (não editáveis) — aparecem na sub-aba mas sem configuração
        # de path: asq-user (primeiro) e executar-tasks (último).
        _FIXED_ROW_STYLE = (
            "QWidget { background-color: #18181B; border: 1px solid #27272A;"
            "  border-radius: 4px; }"
        )
        _FIXED_LBL_STYLE = (
            "color: #71717A; font-size: 10px; font-style: italic; background: transparent;"
            "border: none;"
        )
        _fixed_section_lbl = QLabel("Botões fixos (não editáveis via modal):")
        _fixed_section_lbl.setStyleSheet("font-size: 10px; color: #52525B; font-weight: 600;")
        outer.addWidget(_fixed_section_lbl)

        _FIXED_ENTRIES = [
            ("asq-user", "/tools:auq-interview", "Entrevista AUQ guiada — abre no terminal"),
            ("executar-tasks", "(prompt inline)", "Loop: execute tasklist com revisão adversarial via Codex"),
            ("+ Add prompt", "(meta-prompt)", "Envia meta-prompt ao terminal para criar novo .md em prompts-subtab"),
        ]
        for _flabel, _fpath, _fdesc in _FIXED_ENTRIES:
            _frow = QWidget()
            _frow.setStyleSheet(_FIXED_ROW_STYLE)
            _frow_lay = QHBoxLayout(_frow)
            _frow_lay.setContentsMargins(6, 3, 6, 3)
            _frow_lay.setSpacing(4)
            _fl = QLabel(_flabel)
            _fl.setStyleSheet(_FIXED_LBL_STYLE)
            _fp = QLabel(_fpath)
            _fp.setStyleSheet(_FIXED_LBL_STYLE)
            _fd = QLabel(_fdesc)
            _fd.setStyleSheet(_FIXED_LBL_STYLE)
            _fd.setWordWrap(True)
            _lock = QLabel("🔒")
            _lock.setStyleSheet("color: #3F3F46; font-size: 11px; background: transparent; border: none;")
            _lock.setFixedWidth(22)
            _frow_lay.addWidget(_fl, 20)
            _frow_lay.addWidget(_fp, 50)
            _frow_lay.addWidget(_fd, 25)
            _frow_lay.addWidget(_lock, 5)
            outer.addWidget(_frow)

        # Separador entre fixos e configuráveis
        _sep_lbl = QLabel("Botões configuráveis:")
        _sep_lbl.setStyleSheet("font-size: 10px; color: #52525B; font-weight: 600; margin-top: 4px;")
        outer.addWidget(_sep_lbl)

        # Lista variável de entradas configuráveis (label / path / description / X)
        _list_scroll = QScrollArea()
        _list_scroll.setWidgetResizable(True)
        _list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _list_container = QWidget()
        self._list_layout = QVBoxLayout(_list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)

        self._rows: list[tuple[QLineEdit, QLineEdit, QLineEdit]] = []
        for i, entry in enumerate(entries):
            self._add_row(
                entry.get("label", ""),
                entry.get("path", ""),
                entry.get("description", ""),
                i,
            )

        self._list_layout.addStretch(1)
        _list_scroll.setWidget(_list_container)
        outer.addWidget(_list_scroll, 1)

        # Botao adicionar
        _add_btn = QPushButton("+ adicionar prompt")
        _add_btn.setProperty("testid", "prompts-config-add-row")
        _add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _add_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 11px; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        _add_btn.clicked.connect(self._on_add_row)
        outer.addWidget(_add_btn)

        # Botoes Salvar / Cancelar
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = bb.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Salvar")
            save_btn.setProperty("testid", "prompts-config-submit")
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn = bb.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Cancelar")
            cancel_btn.setProperty("testid", "prompts-config-cancel")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _add_row(
        self,
        label: str = "",
        path: str = "",
        description: str = "",
        idx: int | None = None,
    ) -> None:
        """Adiciona uma linha (label | path | description | X) ao layout."""
        i = len(self._rows) if idx is None else idx
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        le_label = QLineEdit(label)
        le_label.setProperty("testid", f"prompts-config-label-{i}")
        le_label.setPlaceholderText("label")

        le_path = QLineEdit(path)
        le_path.setProperty("testid", f"prompts-config-path-{i}")
        le_path.setPlaceholderText("ai-forge/custom-prompts/prompts-subtab/<arquivo>.md")

        path_picker = QPushButton("🔍")
        path_picker.setProperty("testid", f"prompts-config-path-browse-{i}")
        path_picker.setFixedSize(24, 24)
        path_picker.setCursor(Qt.CursorShape.PointingHandCursor)
        path_picker.setToolTip("Selecionar arquivo .md")
        path_picker.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        path_picker.clicked.connect(lambda _checked=False, le=le_path: self._browse_prompt_md(le))

        path_cell = QWidget()
        path_layout = QHBoxLayout(path_cell)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)
        path_layout.addWidget(le_path, 1)
        path_layout.addWidget(path_picker)

        le_desc = QLineEdit(description)
        le_desc.setProperty("testid", f"prompts-config-description-{i}")
        le_desc.setPlaceholderText("Descricao curta (exibida como tooltip)")

        del_btn = QPushButton("✕")
        del_btn.setObjectName("PromptDelBtn")
        del_btn.setProperty("testid", f"prompts-config-delete-{i}")
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("Remover entrada")
        del_btn.setStyleSheet(
            "QPushButton#PromptDelBtn { background: transparent; border: none;"
            "  color: #EF4444; font-size: 14px; font-weight: 700;"
            "  min-width: 22px; min-height: 22px; padding: 0; margin: 0; }"
            "QPushButton#PromptDelBtn:hover { color: #FCA5A5;"
            "  background: rgba(239,68,68,0.15); border-radius: 3px; }"
        )

        row_layout.addWidget(le_label, 20)
        row_layout.addWidget(path_cell, 50)
        row_layout.addWidget(le_desc, 25)
        row_layout.addWidget(del_btn, 5)

        # Remover antes do stretch (indice count-1 e o stretch)
        _stretch_idx = self._list_layout.count() - 1
        if _stretch_idx >= 0:
            self._list_layout.insertWidget(_stretch_idx, row_widget)
        else:
            self._list_layout.addWidget(row_widget)

        triple = (le_label, le_path, le_desc)
        self._rows.append(triple)

        def _on_delete():
            if triple in self._rows:
                self._rows.remove(triple)
            row_widget.setParent(None)  # type: ignore[arg-type]
            signal_bus.toast_requested.emit("Entrada removida.", "info")

        del_btn.clicked.connect(_on_delete)

    @staticmethod
    def _prompt_md_start_dir() -> str:
        cur = Path.cwd().resolve()
        while cur != cur.parent:
            # `brainstorm` foi realocado para `blacksmith/brainstorm` na
            # reorganizacao do repo; mantemos o top-level legado por compat.
            for cand in (cur / "brainstorm", cur / "blacksmith" / "brainstorm"):
                if cand.is_dir():
                    return str(cand)
            if (cur / "ai-forge" / "workflow-app").is_dir():
                break
            cur = cur.parent
        return str(Path.cwd())

    def _browse_prompt_md(self, line_edit: QLineEdit) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo .md",
            self._prompt_md_start_dir(),
            "Markdown (*.md);;All Files (*)",
        )
        if path:
            line_edit.setText(path)

    def _on_add_row(self) -> None:
        self._add_row()

    def collect(self) -> tuple[str, list[tuple[str, str, str]]]:
        base = self._base_edit.toPlainText()
        entries = [
            (le.text().strip(), lp.text().strip(), ld.text().strip())
            for le, lp, ld in self._rows
        ]
        return base, entries


class PersonasConfigDialog(QDialog):
    """Modal de configuracao dos agentes da sub-aba 'Agentes'.

    Recebe a lista de agentes ATUAIS (varridos de ai-forge/MCP/agents/, sempre
    em sincronia com os botoes — nunca uma lista hardcoded) e renderiza um por
    linha: label editavel + slug/path (somente leitura). collect() devolve
    {slug: label} apenas para os labels editados (diferentes do canonico); um
    label deixado igual ao padrao reseta o override (nao entra no dict), para
    nao mascarar futuras mudancas em _PERSONA_LABELS ou no frontmatter.
    """

    def __init__(self, entries: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar agentes")
        self.setMinimumSize(720, 520)
        self.setProperty("testid", "personas-config-dialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        _intro = QLabel(
            f"{len(entries)} agente(s) em ai-forge/MCP/agents/ "
            "(sincronizado com os botoes da sub-aba). Edite o label de cada um; "
            "deixe igual ao padrao para resetar."
        )
        _intro.setWordWrap(True)
        _intro.setStyleSheet("font-size: 11px; color: #A1A1AA;")
        outer.addWidget(_intro)

        _header = QWidget()
        _hdr = QHBoxLayout(_header)
        _hdr.setContentsMargins(0, 0, 0, 0)
        _hdr.setSpacing(4)
        for _txt, _stretch in [("Label", 28), ("Slug / Path", 72)]:
            _l = QLabel(_txt)
            _l.setStyleSheet("font-size: 10px; color: #71717A; font-weight: 600;")
            _hdr.addWidget(_l, _stretch)
        outer.addWidget(_header)

        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.Shape.NoFrame)
        _container = QWidget()
        _list = QVBoxLayout(_container)
        _list.setContentsMargins(0, 0, 0, 0)
        _list.setSpacing(4)

        # (slug, default_label, QLineEdit) — default_label permite detectar edicao.
        self._rows: list[tuple[str, str, QLineEdit]] = []
        for entry in entries:
            slug = str(entry.get("slug", ""))
            rel_path = str(entry.get("rel_path", ""))
            label = str(entry.get("label", ""))
            default_label = str(entry.get("default_label", label))

            row = QWidget()
            row.setStyleSheet(
                "QWidget { background-color: #18181B; border: 1px solid #27272A;"
                "  border-radius: 4px; }"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            rl.setSpacing(6)

            le_label = QLineEdit(label)
            le_label.setProperty("testid", f"personas-config-label-{slug}")
            le_label.setPlaceholderText(default_label or slug)
            le_label.setStyleSheet(
                "QLineEdit { background-color: #27272A; color: #FAFAFA;"
                "  border: 1px solid #3F3F46; border-radius: 4px; padding: 3px 6px; }"
            )

            _meta = QLabel(f"{slug}\n{rel_path}")
            _meta.setProperty("testid", f"personas-config-meta-{slug}")
            _meta.setStyleSheet(
                "color: #71717A; font-size: 10px; background: transparent;"
                " border: none;"
            )
            _meta.setWordWrap(True)

            rl.addWidget(le_label, 28)
            rl.addWidget(_meta, 72)
            _list.addWidget(row)
            self._rows.append((slug, default_label, le_label))

        _list.addStretch(1)
        _scroll.setWidget(_container)
        outer.addWidget(_scroll, 1)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = bb.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Salvar")
            save_btn.setProperty("testid", "personas-config-submit")
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn = bb.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Cancelar")
            cancel_btn.setProperty("testid", "personas-config-cancel")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def collect(self) -> dict[str, str]:
        """{slug: label} apenas para labels editados (diferentes do canonico)."""
        out: dict[str, str] = {}
        for slug, default_label, le in self._rows:
            val = le.text().strip()
            if val and val != default_label:
                out[slug] = val
        return out


# ──────────────────────────────────────────────────────── Entry point ─── #


def main() -> None:
    from workflow_app.core.sentry_config import init_sentry
    from workflow_app.logger import setup_logging

    setup_logging()
    init_sentry()

    app = QApplication(sys.argv)
    app.setApplicationName("SystemForge Desktop")
    app.setOrganizationName("SystemForge")

    # Apply D19 Graphite Amber theme
    from workflow_app.theme import apply_theme
    apply_theme(app)

    # Load --wf-* design tokens (centralized colors/spacing/radius/typography).
    # Appended after apply_theme so theme defaults remain, with token overrides
    # for widgets that opt-in via objectName/property selectors.
    try:
        _tokens_path = Path(__file__).resolve().parent / "styles" / "tokens.qss"
        if _tokens_path.exists():
            _existing = app.styleSheet() or ""
            app.setStyleSheet(_existing + "\n" + _tokens_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - estilos nao podem quebrar boot
        logger.warning("Falha ao carregar styles/tokens.qss: %s", exc)

    # Window icon
    icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Initialize database (seeds factory templates on first run)
    from workflow_app.db.database_manager import db_manager
    db_manager.setup()

    # Verify SDK availability and authentication before opening main window
    from workflow_app.dialogs.critical_error_modal import CriticalErrorModal
    from workflow_app.errors import SDKNotAuthenticatedError, SDKNotAvailableError
    from workflow_app.sdk.sdk_adapter import SDKAdapter

    adapter = SDKAdapter()
    try:
        adapter.ensure_sdk_ready()
    except (SDKNotAvailableError, SDKNotAuthenticatedError) as exc:
        CriticalErrorModal.show_and_exit(exc)
        return  # sys.exit already called, prevents further execution

    window = MainWindow()
    window.show()

    # Cleanup garantido do PTY no fechamento do app (widgets-filho nao
    # recebem closeEvent confiavelmente; aboutToQuit eh o caminho safe).
    # Cobre todos os OutputPanel ativos (interactive + workspace pyte).
    def _shutdown_terminals() -> None:
        for attr in ("_output_panel", "_workspace_panel"):
            panel = getattr(window, attr, None)
            if panel is not None and hasattr(panel, "shutdown"):
                try:
                    panel.shutdown()
                except Exception:  # noqa: BLE001
                    pass

    app.aboutToQuit.connect(_shutdown_terminals)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
