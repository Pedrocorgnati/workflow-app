#!/usr/bin/env bash
# ============================================================
# Workflow App — Inicialização Desktop
# Uso: ./infra/scripts/run.sh [--db-path PATH] [--log-level LEVEL]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Defaults
DB_PATH="${DB_PATH:-$HOME/.workflow-app/workflow_app.db}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Parsear argumentos
while [[ $# -gt 0 ]]; do
  case $1 in
    --db-path) DB_PATH="$2"; shift 2 ;;
    --log-level) LOG_LEVEL="$2"; shift 2 ;;
    *) echo "Argumento desconhecido: $1"; exit 1 ;;
  esac
done

echo "==> Workflow App"
echo "    DB: $DB_PATH"
echo "    Log: $LOG_LEVEL"
echo ""

# Criar diretório de dados se não existir
mkdir -p "$(dirname "$DB_PATH")"
mkdir -p "$HOME/.workflow-app/logs"

cd "$PROJECT_ROOT"

export DB_PATH
export LOG_LEVEL

exec uv run workflow-app
