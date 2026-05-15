#!/bin/sh
# check-terminal-locator-qualifier.sh
#
# Gate de regressao para o PR2 do plano 05-14-workflow-app-terminal-fix-plan.
# Falha se qualquer teste em ai-forge/workflow-app/tests/e2e referencia o
# testid `terminal-workspace` sem o qualifier `[data-engine="pyte"]` ou
# `[data-engine="xterm"]`. Dois nodes Qt compartilham o mesmo testid; sem
# o qualifier Playwright aborta com strict mode violation e o CI quebra
# silenciosamente.
#
# Uso direto:   ai-forge/workflow-app/scripts/check-terminal-locator-qualifier.sh
# Uso via hook: .git/hooks/pre-commit chama este script.
#
# Exit: 0 = ok, 1 = locator nao qualificado encontrado.

set -eu

TARGET_DIR="ai-forge/workflow-app/tests/e2e"

if [ ! -d "$TARGET_DIR" ]; then
  # Sem diretorio de testes E2E nao ha nada a verificar.
  exit 0
fi

RESULT=$(grep -rEn 'testid["\047]?\s*[:=]\s*["\047]terminal-workspace["\047]' \
  "$TARGET_DIR" \
  | grep -v 'data-engine' \
  || true)

if [ -n "$RESULT" ]; then
  echo "ERROR: locator terminal-workspace sem data-engine qualifier:" >&2
  echo "$RESULT" >&2
  echo "" >&2
  echo "Use as constantes TERMINAL_PYTE / TERMINAL_XTERM de tests/e2e/conftest.py" >&2
  echo "ou o seletor literal '[data-testid=\"terminal-workspace\"][data-engine=\"pyte\"|\"xterm\"]'." >&2
  exit 1
fi

exit 0
