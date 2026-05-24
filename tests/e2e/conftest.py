"""
E2E conftest — helpers compartilhados pelos testes Playwright/pytest-qt do
workflow-app. Centraliza locators canonicos para os dois engines de terminal
(pyte legado e xterm.js novo) introduzidos pelo PR2 do plano
05-14-workflow-app-terminal-fix-plan.

Regra (pre-T020): testes E2E NUNCA deviam usar o testid `terminal-workspace`
sem o qualifier `[data-engine="..."]` porque DOIS nodes compartilhavam o mesmo
testid (um por engine, pyte/xterm). Pos-T020 (loop 05-21, 2026-05-22), o
xterm migrou para `terminal-codex-output`, ficando UM testid por engine no
nivel Qt. O qualifier `[data-engine="..."]` permanece util para Playwright/
DOM puro (assets/xterm/index.html injeta engine via webchannel) e como
salvaguarda contra futuros placeholders com mesmo testid. Use as constantes
abaixo em vez de string literal.

Importacao recomendada:

    from tests.e2e.conftest import TERMINAL_PYTE, TERMINAL_XTERM

Gate de regressao: `ai-forge/workflow-app/scripts/check-terminal-locator-qualifier.sh`
(invocado por `.git/hooks/pre-commit`) bloqueia commits que reintroduzam
locator nao-qualificado.

T020 BLOCKER 2 (2026-05-22, loop 05-21-implantation-tasklist-aba-brainstorm):
o testid Qt do XtermOutputPanel mudou de `terminal-workspace-xterm` para
`terminal-codex-output` (canonico §10.5 do mcp-flow-implantation-base-archive.md).
TERMINAL_XTERM passa a refletir o novo nome; mantemos TERMINAL_PYTE em
`terminal-workspace` pois o panel pyte (`_workspace_panel`) preserva esse
testid em `main_window.py:1233`.
"""

TERMINAL_PYTE = '[data-testid="terminal-workspace"][data-engine="pyte"]'
TERMINAL_XTERM = '[data-testid="terminal-codex-output"][data-engine="xterm"]'
