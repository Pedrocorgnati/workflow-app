# Load Test Report — Workflow Mobile Remote

**Data:** 2026-03-16
**Projeto:** Workflow Mobile Remote Feature
**Runtime:** Python
**Ferramenta:** Locust + locust-plugins (WebSocketUser)
**Protocolo:** WebSocket

---

## SLOs Definidos

| Cenário | Métrica | Valor | Fonte |
|---------|---------|-------|-------|
| sync_request_latency | p95 | 100ms | slos.json |
| sync_request_latency | p99 | 200ms | slos.json |
| control_ack_latency | p95 | 100ms | slos.json |
| control_ack_latency | p99 | 200ms | slos.json |
| end_to_end_budget | ceiling | 500ms | slos.json |
| global | rate_limit | 20 msg/s | slos.json |
| global | max_message_bytes | 65536 bytes (64KB) | slos.json |

---

## Cenários Gerados

| # | Cenário | Arquivo | Classe | Endpoint | SLO |
|---|---------|---------|--------|----------|-----|
| 1 | Conexão + sync_request baseline | `tests/load/scenarios/ws_connect_sync.py` | `WsConnectSyncUser` | `sync_request` → `pipeline_state` | p95 < 100ms |
| 2 | Control messages (play/pause/skip) | `tests/load/scenarios/ws_control.py` | `WsControlUser` | `control` → `control_ack` | p95 < 100ms |
| 3 | Interaction response | `tests/load/scenarios/ws_interaction.py` | `WsInteractionUser` | `interaction_response` → `interaction_response_ack` | ceiling < 500ms |

---

## Smoke Test

**Status: PULADO**

Domínio não configurado em `.claude/projects/workflow-app.json` (`deploy_info.domain` vazio).
O servidor requer conexão via rede Tailscale (IPs `100.64.0.0/10`).

Para executar manualmente:

```bash
# Certificar que o workflow-app está em execução com Remote Mode ativado na UI
# Certificar que está na rede Tailscale e nenhum cliente Android conectado

./tests/load/run.sh locust-smoke ws://100.64.0.1:18765
```

---

## Instruções de Execução

### Pré-requisitos

```bash
# Instalar Locust e plugin WebSocket
pip install locust locust-plugins

# Verificar instalação
locust --version
```

### Cenário único

```bash
# Smoke (1 usuário, 1 min) — validação
./tests/load/run.sh locust-smoke ws://100.64.0.1:18765

# Carga sustentada (1 usuário, 10 min)
./tests/load/run.sh locust-load ws://100.64.0.1:18765

# Pressão máxima single-client (1 usuário, 10 min, wait menor)
./tests/load/run.sh locust-stress ws://100.64.0.1:18765
```

### Todos os cenários

```bash
./tests/load/run.sh locust-all ws://100.64.0.1:18765
```

### Cenário individual com arquivo específico

```bash
locust -f tests/load/scenarios/ws_connect_sync.py --headless -u 1 -r 1 -t 1m
locust -f tests/load/scenarios/ws_control.py      --headless -u 1 -r 1 -t 1m
locust -f tests/load/scenarios/ws_interaction.py  --headless -u 1 -r 1 -t 1m
```

### Todos os cenários via orquestrador

```bash
locust -f tests/load/locustfile.py --headless -u 1 -r 1 -t 10m \
  --html tests/load/results/all_$(date +%Y%m%d_%H%M%S).html
```

> **ATENÇÃO:** O servidor aceita apenas 1 conexão simultânea (single-client mode).
> Sempre execute com `-u 1`. Com `-u > 1`, o segundo usuário receberá close code 1008.

---

## Template para Resultados de Carga Real

Preencher após execução dos testes:

| Cenário | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Taxa Erro | SLO |
|---------|-----|----------|----------|----------|-----------|-----|
| sync_request | — | — | — | — | — | p95 < 100ms |
| control_play | — | — | — | — | — | p95 < 100ms |
| control_pause | — | — | — | — | — | p95 < 100ms |
| control_skip | — | — | — | — | — | p95 < 100ms |
| interaction_response | — | — | — | — | — | ceiling < 500ms |

---

## Gargalos Identificados

*Seção para preencher após execução dos testes de carga reais.*

Áreas a monitorar:
- Latência de serialização/deserialização JSON no servidor Python
- Overhead do loop asyncio no `remote_server.py` com mensagens de alta frequência
- Tempo de processamento de `sync_request` sob carga sustentada (estado do pipeline pode crescer)
- Comportamento do `interaction_response` quando há pipeline state lock

---

## Recomendações

*Seção para preencher após análise dos resultados.*

Baseline recomendado antes de carga real:
1. Executar `locust-smoke` para validar scripts (1 usuário, 1 min)
2. Executar `locust-load` para carga sustentada baseline (1 usuário, 10 min)
3. Comparar p95 com SLOs definidos em `slos.json`
4. Se p95 > 80ms: investigar gargalos antes de considera SLO em risco

---

## Arquivos Gerados

| Arquivo | Descrição |
|---------|-----------|
| `tests/load/slos.json` | SLOs por cenário (existente, não modificado) |
| `tests/load/scenarios/ws_connect_sync.py` | Cenário Locust: sync_request baseline |
| `tests/load/scenarios/ws_control.py` | Cenário Locust: control play/pause/skip |
| `tests/load/scenarios/ws_interaction.py` | Cenário Locust: interaction_response |
| `tests/load/locustfile.py` | Orquestrador Locust (importa os 3 cenários) |
| `tests/load/run.sh` | Script de conveniência (k6 + Locust) |
| `tests/load/results/` | Resultados gerados em execução (gitignored) |

---

## Instalação

```bash
# Locust
pip install locust locust-plugins

# k6 (cenários JS existentes)
brew install k6   # macOS
# ou: https://k6.io/docs/getting-started/installation/
```
