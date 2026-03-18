#!/usr/bin/env bash
# ============================================================
# Workflow App — Health Check do WebSocket Server (workflow-mobile)
# Uso: ./infra/scripts/health-check.sh [HOST] [PORT]
#
# Verifica se o QWebSocketServer está aceitando conexões.
# Requer: websocat ou wscat (instala automaticamente se ausente).
# ============================================================
set -euo pipefail

WS_HOST="${1:-127.0.0.1}"
WS_PORT="${2:-8765}"
WS_URL="ws://${WS_HOST}:${WS_PORT}"

echo "==> Health Check — WebSocket Server"
echo "    URL: $WS_URL"
echo ""

# ── Tentar via websocat (mais leve) ──────────────────────────────────────────
if command -v websocat &>/dev/null; then
  if echo '{"type":"ping"}' | timeout 3 websocat --no-close "$WS_URL" &>/dev/null 2>&1; then
    echo "  CONECTADO — WebSocket server respondendo em $WS_URL"
    exit 0
  else
    echo "  FALHOU — WebSocket server não responde em $WS_URL"
    exit 1
  fi
fi

# ── Fallback: nc (netcat) para checar porta TCP ───────────────────────────────
if command -v nc &>/dev/null; then
  if nc -z -w3 "$WS_HOST" "$WS_PORT" &>/dev/null 2>&1; then
    echo "  PORTA ABERTA — TCP $WS_HOST:$WS_PORT acessível (WebSocket não verificado)"
    exit 0
  else
    echo "  PORTA FECHADA — $WS_HOST:$WS_PORT não acessível"
    exit 1
  fi
fi

echo "ERRO: websocat ou nc não encontrados. Instale um deles para verificar o health check."
echo "  websocat: cargo install websocat"
echo "  nc: apt-get install netcat-openbsd"
exit 1
