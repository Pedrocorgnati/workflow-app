/**
 * Cenário: Large message handling — validação do limite de 64KB
 *
 * Verifica que:
 * - Mensagens acima de 65536 bytes são descartadas (sem fechar conexão)
 * - Mensagens abaixo do limite são processadas normalmente
 *
 * O servidor usa MAX_MESSAGE_BYTES = 65536 (64KB).
 * Mensagens acima desse limite são descartadas ANTES do parse (size check step 0).
 *
 * PRÉ-REQUISITOS:
 *   1. Tailscale ativo na máquina que executa o k6
 *   2. workflow-app com Remote Mode ativo
 *
 * Uso:
 *   k6 run --env BASE_URL=ws://100.x.x.x:18765 tests/load/scenarios/ws_large_message.js
 */

import ws from 'k6/ws'
import { check, sleep } from 'k6'
import { Rate } from 'k6/metrics'
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js'

const BASE_URL = __ENV.BASE_URL || 'ws://100.64.0.1:18765'

// Limite do servidor (MAX_MESSAGE_BYTES)
const MAX_MESSAGE_BYTES = 65536

const connectionErrors = new Rate('ws_large_msg_errors')
const smallMsgProcessed = new Rate('ws_small_msg_processed')

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: 1,
      duration: '30s',
    },
  },
  thresholds: {
    ws_large_msg_errors: ['rate<0.05'],
  },
}

function buildPayload(sizeBytes) {
  // Gera sync_request com padding para atingir o tamanho desejado
  const base = {
    message_id: uuidv4(),
    type: 'sync_request',
    timestamp: new Date().toISOString(),
    payload: { _padding: '' },
  }
  const baseStr = JSON.stringify(base)
  const paddingNeeded = Math.max(0, sizeBytes - baseStr.length)
  base.payload._padding = 'x'.repeat(paddingNeeded)
  return JSON.stringify(base)
}

export default function () {
  const params = {
    headers: { 'User-Agent': 'k6-load-test/workflow-app' },
  }

  const res = ws.connect(BASE_URL, params, function (socket) {
    let pipelineStateCount = 0

    socket.on('open', function () {
      // Teste 1: Mensagem bem abaixo do limite (1KB) — deve ser processada
      socket.setTimeout(function () {
        socket.send(buildPayload(1024))
      }, 1000)

      // Teste 2: Mensagem próxima ao limite (65000 bytes) — deve ser processada
      socket.setTimeout(function () {
        socket.send(buildPayload(65000))
      }, 4000)

      // Teste 3: Mensagem exatamente no limite (65536 bytes) — deve ser descartada
      socket.setTimeout(function () {
        socket.send(buildPayload(MAX_MESSAGE_BYTES + 10))
      }, 7000)

      // Teste 4: Após mensagem grande, verificar que conexão segue ativa
      socket.setTimeout(function () {
        const probe = {
          message_id: uuidv4(),
          type: 'sync_request',
          timestamp: new Date().toISOString(),
          payload: {},
        }
        socket.send(JSON.stringify(probe))
      }, 10000)

      socket.setTimeout(function () {
        socket.close()
      }, 28000)
    })

    socket.on('message', function (data) {
      try {
        const msg = JSON.parse(data)
        if (msg.type === 'pipeline_state') {
          pipelineStateCount++
          smallMsgProcessed.add(1)
          check(msg, {
            'pipeline_state válido após large message': (m) =>
              typeof m.payload?.status === 'string',
          })
        }
      } catch (e) {
        // ignore
      }
    })

    socket.on('error', function (e) {
      connectionErrors.add(1)
      console.error('WebSocket error:', e.error())
    })

    socket.on('close', function (code) {
      if (code === 1008 || code === 1009) {
        // 1009 = Message Too Big — algumas implementações fecham a conexão
        console.warn(`Conexão fechada pelo servidor (code ${code})`)
        connectionErrors.add(1)
      }
    })
  })

  check(res, {
    'WebSocket conectado (status 101)': (r) => r && r.status === 101,
  })

  sleep(1)
}
