"""
E2E conftest — helpers compartilhados pelos testes Playwright/pytest-qt do
workflow-app. Centraliza locators canonicos para os dois engines de terminal
(pyte legado e xterm.js novo) introduzidos pelo PR2 do plano
05-14-workflow-app-terminal-fix-plan.

Regra: testes E2E NUNCA devem usar o testid `terminal-workspace` sem o
qualifier `[data-engine="..."]`. A interface anuncia DOIS nodes com o mesmo
testid (um por engine), e Playwright em strict mode aborta com
`strict mode violation` se a query nao for desambiguada. Use as constantes
abaixo em vez de string literal.

Importacao recomendada:

    from tests.e2e.conftest import TERMINAL_PYTE, TERMINAL_XTERM

Gate de regressao: `ai-forge/workflow-app/scripts/check-terminal-locator-qualifier.sh`
(invocado por `.git/hooks/pre-commit`) bloqueia commits que reintroduzam
locator nao-qualificado.
"""

TERMINAL_PYTE = '[data-testid="terminal-workspace"][data-engine="pyte"]'
TERMINAL_XTERM = '[data-testid="terminal-workspace"][data-engine="xterm"]'
