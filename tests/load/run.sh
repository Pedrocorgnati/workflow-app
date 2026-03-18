#!/bin/bash
# Workflow App — Load Test Runner
#
# Uso: ./tests/load/run.sh [cenário] [BASE_URL]
#
# ── Cenários k6 (JavaScript) ──────────────────────────────────────────
#   sync          — ws_sync_request.js   (baseline latência)
#   flood         — ws_control_flood.js  (controle play/pause/skip)
#   large         — ws_large_message.js  (mensagem grande, limite 64KB)
#   all           — todos os k6 sequencialmente
#
# ── Cenários Locust (Python WebSocket) ────────────────────────────────
#   locust-smoke  — 1 usuário, 1 min  (validação de scripts)
#   locust-load   — 1 usuário, 10 min (single-client mode)
#   locust-stress — 1 usuário, 10 min com wait menor
#   locust-all    — orquestrador locustfile.py (todos os cenários Locust)
#
#   BASE_URL: ws://100.x.x.x:18765  (padrão: ws://100.64.0.1:18765)
#
# Exemplos:
#   ./tests/load/run.sh sync ws://100.64.0.1:18765
#   ./tests/load/run.sh locust-smoke ws://100.64.0.1:18765
#   ./tests/load/run.sh locust-all
#   ./tests/load/run.sh all ws://100.64.0.1:18765
#
# PRÉ-REQUISITOS:
#   k6:     brew install k6
#   Locust: pip install locust locust-plugins
#   Tailscale ativo nesta máquina
#   workflow-app em execução com Remote Mode ativado na UI
#   Nenhum outro cliente Android conectado (single-client mode)
#
# ATENÇÃO (Locust): o servidor aceita apenas 1 conexão simultânea.
#   Com -u > 1 o segundo usuário receberá close 1008.
#   Execute sempre com -u 1 para este servidor.

set -euo pipefail

SCENARIO="${1:-sync}"
BASE_URL="${2:-ws://100.64.0.1:18765}"
RESULTS_DIR="tests/load/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$RESULTS_DIR"

# ── k6 ────────────────────────────────────────────────────────────────

run_k6_scenario() {
  local name="$1"
  local file="$2"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  [k6] Cenário: $name"
  echo "  URL:          $BASE_URL"
  echo "  Script:       $file"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  k6 run \
    --env "BASE_URL=$BASE_URL" \
    --summary-export "$RESULTS_DIR/${name}_${TIMESTAMP}.json" \
    "$file"
}

# ── Locust ────────────────────────────────────────────────────────────

run_locust() {
  local name="$1"
  local locustfile="$2"
  local users="$3"
  local spawn_rate="$4"
  local duration="$5"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  [Locust] Cenário: $name"
  echo "  URL:              $BASE_URL"
  echo "  Usuários:         $users  Spawn rate: $spawn_rate/s  Duração: $duration"
  echo "  Script:           $locustfile"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  BASE_URL="$BASE_URL" locust \
    -f "$locustfile" \
    --headless \
    -u "$users" \
    -r "$spawn_rate" \
    -t "$duration" \
    --html "$RESULTS_DIR/${name}_${TIMESTAMP}.html" \
    --csv "$RESULTS_DIR/${name}_${TIMESTAMP}"
}

# ── Roteamento ────────────────────────────────────────────────────────

case "$SCENARIO" in

  # ── k6 ──────────────────────────────────────────────────────────────
  sync)
    if ! command -v k6 &>/dev/null; then
      echo "ERRO: k6 não encontrado. Instale com: brew install k6"
      exit 1
    fi
    run_k6_scenario "ws_sync_request" "tests/load/scenarios/ws_sync_request.js"
    ;;
  flood)
    if ! command -v k6 &>/dev/null; then
      echo "ERRO: k6 não encontrado. Instale com: brew install k6"
      exit 1
    fi
    run_k6_scenario "ws_control_flood" "tests/load/scenarios/ws_control_flood.js"
    ;;
  large)
    if ! command -v k6 &>/dev/null; then
      echo "ERRO: k6 não encontrado. Instale com: brew install k6"
      exit 1
    fi
    run_k6_scenario "ws_large_message" "tests/load/scenarios/ws_large_message.js"
    ;;
  all)
    if ! command -v k6 &>/dev/null; then
      echo "ERRO: k6 não encontrado. Instale com: brew install k6"
      exit 1
    fi
    run_k6_scenario "ws_sync_request" "tests/load/scenarios/ws_sync_request.js"
    echo "Aguardando 5s antes do próximo cenário..."
    sleep 5
    run_k6_scenario "ws_control_flood" "tests/load/scenarios/ws_control_flood.js"
    echo "Aguardando 5s antes do próximo cenário..."
    sleep 5
    run_k6_scenario "ws_large_message" "tests/load/scenarios/ws_large_message.js"
    ;;

  # ── Locust ──────────────────────────────────────────────────────────
  locust-smoke)
    if ! command -v locust &>/dev/null; then
      echo "ERRO: locust não encontrado. Instale com: pip install locust locust-plugins"
      exit 1
    fi
    # 1 usuário, 1 min — valida que os scripts funcionam corretamente
    run_locust "locust_smoke" "tests/load/locustfile.py" 1 1 "1m"
    ;;
  locust-load)
    if ! command -v locust &>/dev/null; then
      echo "ERRO: locust não encontrado. Instale com: pip install locust locust-plugins"
      exit 1
    fi
    # 1 usuário, 10 min — carga sustentada (respeita single-client mode)
    run_locust "locust_load" "tests/load/locustfile.py" 1 1 "10m"
    ;;
  locust-stress)
    if ! command -v locust &>/dev/null; then
      echo "ERRO: locust não encontrado. Instale com: pip install locust locust-plugins"
      exit 1
    fi
    # 1 usuário, 10 min, wait_time reduzido via env — pressão máxima single-client
    run_locust "locust_stress" "tests/load/locustfile.py" 1 1 "10m"
    ;;
  locust-all)
    if ! command -v locust &>/dev/null; then
      echo "ERRO: locust não encontrado. Instale com: pip install locust locust-plugins"
      exit 1
    fi
    # Todos os cenários Locust sequencialmente
    echo ""
    echo "Executando todos os cenários Locust sequencialmente..."
    run_locust "locust_smoke"   "tests/load/locustfile.py" 1 1 "1m"
    echo "Aguardando 5s antes do próximo cenário..."
    sleep 5
    run_locust "locust_load"    "tests/load/locustfile.py" 1 1 "10m"
    echo ""
    echo "Para executar cenário individual:"
    echo "  locust -f tests/load/scenarios/ws_connect_sync.py --headless -u 1 -r 1 -t 1m"
    echo "  locust -f tests/load/scenarios/ws_control.py      --headless -u 1 -r 1 -t 1m"
    echo "  locust -f tests/load/scenarios/ws_interaction.py  --headless -u 1 -r 1 -t 1m"
    ;;

  *)
    echo "Uso: $0 [cenário] [BASE_URL]"
    echo ""
    echo "Cenários k6:     sync | flood | large | all"
    echo "Cenários Locust: locust-smoke | locust-load | locust-stress | locust-all"
    exit 1
    ;;
esac

echo ""
echo "Resultados salvos em: $RESULTS_DIR/"
