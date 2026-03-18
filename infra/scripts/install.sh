#!/usr/bin/env bash
# ============================================================
# Workflow App — Instalação Desktop (Linux)
# Uso: ./infra/scripts/install.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Workflow App — Instalação Desktop"
echo "    Projeto: $PROJECT_ROOT"
echo ""

# ── Verificações de pré-requisitos ────────────────────────────────────────────

check_command() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERRO: '$1' não encontrado. $2"
    exit 1
  fi
}

check_command python3 "Instale Python 3.10+ em https://python.org"
check_command uv     "Instale uv: curl -Ls https://astral.sh/uv/install.sh | sh"

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED_MAJOR=3
REQUIRED_MINOR=10

if python3 -c "import sys; exit(0 if sys.version_info >= ($REQUIRED_MAJOR, $REQUIRED_MINOR) else 1)"; then
  echo "  Python $PYTHON_VERSION — OK"
else
  echo "ERRO: Python $PYTHON_VERSION encontrado, mas >= 3.10 é necessário."
  exit 1
fi

# ── Dependências de sistema (Qt6/PySide6) ─────────────────────────────────────

echo ""
echo "==> Verificando dependências de sistema para PySide6..."

MISSING_PKGS=()
for pkg in libgl1 libglib2.0-0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
           libxcb-keysyms1 libxcb-randr0 libxcb-render-util0; do
  if ! dpkg -l "$pkg" &>/dev/null 2>&1; then
    MISSING_PKGS+=("$pkg")
  fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
  echo "  Instalando pacotes Qt: ${MISSING_PKGS[*]}"
  sudo apt-get install -y --no-install-recommends "${MISSING_PKGS[@]}"
else
  echo "  Dependências Qt — OK"
fi

# ── WebSocketServer (workflow-mobile) — dependência PySide6 QtWebSockets ─────

echo ""
echo "==> Verificando PySide6 >= 6.6.0 (QtWebSockets necessário para workflow-mobile)..."

if python3 -c "from PySide6.QtWebSockets import QWebSocketServer" &>/dev/null 2>&1; then
  echo "  QtWebSockets — OK"
else
  echo "  AVISO: QtWebSockets não disponível. Certifique-se de usar PySide6 >= 6.6.0."
fi

# ── Instalar dependências do projeto ─────────────────────────────────────────

echo ""
echo "==> Instalando dependências Python via uv..."
cd "$PROJECT_ROOT"
uv sync --frozen

echo ""
echo "==> Instalação concluída!"
echo ""
echo "  Para rodar: ./infra/scripts/run.sh"
echo "  Para testar: make test"
echo "  WebSocket (workflow-mobile): ver infra/README.md"
