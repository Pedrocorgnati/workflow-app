"""
E2E conftest — helpers compartilhados pelos testes Playwright/pytest-qt do
workflow-app. Centraliza locators canonicos dos terminais do workspace.

Regra (pre-T020): testes E2E NUNCA deviam usar o testid `terminal-workspace`
sem o qualifier `[data-engine="..."]` porque DOIS nodes compartilhavam o mesmo
testid (um por engine, pyte/xterm). Pos-T020 (loop 05-21, 2026-05-22), o T3
migrou para o testid `terminal-codex-output`, ficando UM testid por painel no
nivel Qt. O qualifier `[data-engine="..."]` permanece util para Playwright/DOM
puro e como salvaguarda contra futuros placeholders com mesmo testid. Use as
constantes abaixo em vez de string literal.

Importacao recomendada:

    from tests.e2e.conftest import TERMINAL_PYTE, TERMINAL_T3

Gate de regressao: `ai-forge/workflow-app/scripts/check-terminal-locator-qualifier.sh`
(invocado por `.git/hooks/pre-commit`) bloqueia commits que reintroduzam
locator nao-qualificado.

2026-06-01: T3 (terminal Codex) passou de xterm.js/QWebEngine para pyte —
agora os TRES terminais usam o engine pyte (OutputPanel). O testid de painel
`terminal-codex-output` (contrato de deteccao Codex) e mantido; o data-engine
do T3 e agora `pyte`. TERMINAL_T3 substitui o antigo nome TERMINAL_XTERM
(alias retido por compat). TERMINAL_PYTE segue em `terminal-workspace` (T2).
"""

TERMINAL_PYTE = '[data-testid="terminal-workspace"][data-engine="pyte"]'
TERMINAL_T3 = '[data-testid="terminal-codex-output"][data-engine="pyte"]'
# Alias historico (T3 era xterm.js ate 2026-06-01). Mantido para nao quebrar
# importadores antigos; aponta para o mesmo locator pyte.
TERMINAL_XTERM = TERMINAL_T3
