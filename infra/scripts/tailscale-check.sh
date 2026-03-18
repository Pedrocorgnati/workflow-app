#!/usr/bin/env bash
# ============================================================
# Workflow App — Verificação Tailscale (workflow-mobile)
# Uso: ./infra/scripts/tailscale-check.sh
#
# Verifica:
#   1. Tailscale está instalado e ativo
#   2. IP Tailscale do PC (100.x.x.x)
#   3. Interface tailscale0 disponível para bind do QWebSocketServer
# ============================================================
set -euo pipefail

echo "==> Tailscale Check — Workflow Mobile"
echo ""

# ── 1. Verificar instalação ───────────────────────────────────────────────────
if ! command -v tailscale &>/dev/null; then
  echo "  ERRO: Tailscale não instalado."
  echo "        Instale em: https://tailscale.com/download"
  exit 1
fi
echo "  Tailscale instalado — OK"

# ── 2. Verificar status ───────────────────────────────────────────────────────
TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('BackendState', 'unknown'))
" 2>/dev/null || echo "unknown")

if [ "$TS_STATUS" != "Running" ]; then
  echo "  ERRO: Tailscale não está ativo (estado: $TS_STATUS)"
  echo "        Execute: sudo tailscale up"
  exit 1
fi
echo "  Tailscale ativo (BackendState: $TS_STATUS) — OK"

# ── 3. Obter IP Tailscale ─────────────────────────────────────────────────────
TS_IP=$(tailscale ip -4 2>/dev/null || echo "")

if [ -z "$TS_IP" ]; then
  echo "  ERRO: IP Tailscale não encontrado."
  exit 1
fi

echo "  IP Tailscale: $TS_IP — OK"

# ── 4. Verificar interface de rede ────────────────────────────────────────────
if ip link show tailscale0 &>/dev/null 2>&1; then
  echo "  Interface tailscale0 — OK"
else
  echo "  AVISO: Interface tailscale0 não encontrada."
  echo "         O QWebSocketServer pode não conseguir bind em $TS_IP"
fi

echo ""
echo "==> Configuração para workflow-mobile:"
echo "    WS_BIND_HOST=$TS_IP"
echo "    WS_PORT=8765  (fallback: 8766-8774)"
echo ""
echo "    No app Android: conectar em ws://$TS_IP:8765"
