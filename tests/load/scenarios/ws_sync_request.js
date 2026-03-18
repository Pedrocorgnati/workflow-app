/**
 * Cenário: sync_request latency (INT-020 PC-side)
 *
 * Envia sync_request e mede o tempo até receber pipeline_state.
 * Este é o único padrão request-response disponível no protocolo PC↔Android.
 *
 * PRÉ-REQUISITOS:
 *   1. Tailscale ativo na máquina que executa o k6
 *   2. workflow-app em execução com Remote Mode ativado na UI
 *   3. BASE_URL apontando para ws://{tailscale_ip}:{port}
 *
 * Uso:
 *   k6 run --env BASE_URL=ws://100.x.x.x:18765 tests/load/scenarios/ws_sync_request.js
 *   k6 run --env BASE_URL=ws://100.x.x.x:18765 --env SCENARIO=smoke tests/load/scenarios/ws_sync_request.js
 */

import ws from 'k6/ws'
import { check, sleep } from 'k6'
import { Rate, Trend } from 'k6/metrics'
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js'

const BASE_URL = __ENV.BASE_URL || 'ws://100.64.0.1:18765'
const SCENARIO = __ENV.SCENARIO || 'smoke'

// SLOs do protocolo (INT-020 — PC side budget)
const SLO_P95_MS = 100
const SLO_P99_MS = 200

const syncLatency = new Trend('ws_sync_request_latency_ms', true)
const syncErrors = new Rate('ws_sync_request_errors')
const pipelineStateReceived = new Rate('ws_pipeline_state_received')

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: 1,
      duration: '30s',
    },
  },
  thresholds: {
    ws_sync_request_latency_ms: [`p(95)<${SLO_P95_MS}`, `p(99)<${SLO_P99_MS}`],
    ws_sync_request_errors: ['rate<0.05'],
    ws_pipeline_state_received: ['rate>0.90'],
  },
}

export default function () {
  const params = {
    headers: { 'User-Agent': 'k6-load-test/workflow-app' },
  }

  const res = ws.connect(BASE_URL, params, function (socket) {
    let pendingRequests = {}

    socket.on('open', function () {
      // Enviar sync_request a cada 2s (bem abaixo do rate limit de 20 msg/s)
      socket.setInterval(function () {
        const msgId = uuidv4()
        const envelope = {
          message_id: msgId,
          type: 'sync_request',
          timestamp: new Date().toISOString(),
          payload: {},
        }
        pendingRequests[msgId] = Date.now()
        socket.send(JSON.stringify(envelope))
      }, 2000)

      // Fechar após 28s (dentro do duration do smoke test)
      socket.setTimeout(function () {
        socket.close()
      }, 28000)
    })

    socket.on('message', function (data) {
      try {
        const msg = JSON.parse(data)

        if (msg.type === 'pipeline_state') {
          // Encontrar o sync_request correspondente pelo context (sem correlation id nativo)
          // O servidor responde na ordem de chegada — usar o request mais antigo
          const pendingIds = Object.keys(pendingRequests)
          if (pendingIds.length > 0) {
            const sentAt = pendingRequests[pendingIds[0]]
            const latency = Date.now() - sentAt
            delete pendingRequests[pendingIds[0]]

            syncLatency.add(latency)
            pipelineStateReceived.add(1)

            check(msg, {
              'pipeline_state tem campo status': (m) => typeof m.payload?.status === 'string',
              'pipeline_state tem command_queue': (m) => Array.isArray(m.payload?.command_queue),
              [`latência < SLO p95 (${SLO_P95_MS}ms)`]: () => latency < SLO_P95_MS,
            })
          }
        }
      } catch (e) {
        syncErrors.add(1)
      }
    })

    socket.on('error', function (e) {
      syncErrors.add(1)
      console.error('WebSocket error:', e.error())
    })

    socket.on('close', function () {
      // Requests sem resposta = timeout
      for (const id of Object.keys(pendingRequests)) {
        syncErrors.add(1)
        pipelineStateReceived.add(0)
        delete pendingRequests[id]
      }
    })
  })

  check(res, {
    'WebSocket conectado (status 101)': (r) => r && r.status === 101,
  })

  sleep(1)
}
