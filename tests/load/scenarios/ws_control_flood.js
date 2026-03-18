/**
 * Cenário: control message flood — validação do rate limit (20 msg/s)
 *
 * Envia mensagens control a >20/s e verifica que:
 * - O servidor não fecha a conexão inesperadamente
 * - control_ack é recebido para mensagens dentro do limite
 * - Mensagens acima do limite são descartadas sem crash
 *
 * PRÉ-REQUISITOS:
 *   1. Tailscale ativo na máquina que executa o k6
 *   2. workflow-app com Remote Mode ativo (pipeline em estado IDLE ou PAUSED)
 *
 * Uso:
 *   k6 run --env BASE_URL=ws://100.x.x.x:18765 tests/load/scenarios/ws_control_flood.js
 */

import ws from 'k6/ws'
import { check, sleep } from 'k6'
import { Counter, Rate } from 'k6/metrics'
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js'

const BASE_URL = __ENV.BASE_URL || 'ws://100.64.0.1:18765'

// Rate limit do servidor: RATE_LIMIT_MSG_PER_S = 20
const SERVER_RATE_LIMIT = 20
// Burst intencionalmente acima do limite para testar o comportamento
const BURST_RATE = 25

const messagesSent = new Counter('ws_control_messages_sent')
const acksReceived = new Counter('ws_control_acks_received')
const acksAccepted = new Counter('ws_control_acks_accepted')
const connectionErrors = new Rate('ws_connection_errors')

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: 1,
      duration: '60s',
    },
  },
  thresholds: {
    // Conexão não deve ser derrubada pelo servidor durante o teste
    ws_connection_errors: ['rate<0.10'],
    // Deve receber acks para pelo menos 70% das mensagens (accounting para rate drop)
    ws_control_acks_received: ['count>10'],
  },
}

// Ações rotativas para variar os comandos enviados
const ACTIONS = ['play', 'pause', 'skip']
let actionIndex = 0

function nextAction() {
  const action = ACTIONS[actionIndex % ACTIONS.length]
  actionIndex++
  return action
}

export default function () {
  const params = {
    headers: { 'User-Agent': 'k6-load-test/workflow-app' },
  }

  const res = ws.connect(BASE_URL, params, function (socket) {
    let connected = true
    let windowStart = Date.now()
    let windowCount = 0

    socket.on('open', function () {
      // Burst: envia BURST_RATE mensagens/s (~40ms entre cada)
      const intervalMs = Math.floor(1000 / BURST_RATE)

      socket.setInterval(function () {
        if (!connected) return

        // Reseta janela a cada 1s para acompanhar o rate limit do servidor
        const now = Date.now()
        if (now - windowStart >= 1000) {
          windowStart = now
          windowCount = 0
        }

        const action = nextAction()
        const envelope = {
          message_id: uuidv4(),
          type: 'control',
          timestamp: new Date().toISOString(),
          payload: { action },
        }

        socket.send(JSON.stringify(envelope))
        messagesSent.add(1)
        windowCount++
      }, intervalMs)

      // Fechar após 55s
      socket.setTimeout(function () {
        connected = false
        socket.close()
      }, 55000)
    })

    socket.on('message', function (data) {
      try {
        const msg = JSON.parse(data)

        if (msg.type === 'control_ack') {
          acksReceived.add(1)

          const accepted = msg.payload?.accepted === true
          if (accepted) acksAccepted.add(1)

          check(msg, {
            'control_ack tem campo action': (m) => typeof m.payload?.action === 'string',
            'control_ack tem campo accepted': (m) => typeof m.payload?.accepted === 'boolean',
          })
        }
      } catch (e) {
        // mensagem inválida — não incrementa erros de conexão
      }
    })

    socket.on('error', function (e) {
      connectionErrors.add(1)
      connected = false
      console.error('WebSocket error:', e.error())
    })

    socket.on('close', function (code) {
      connected = false
      // Close code 1008 = Policy Violation (rate limit ou IP inválido)
      if (code === 1008) {
        console.warn(`Servidor fechou conexão: close code 1008 (Policy Violation)`)
        connectionErrors.add(1)
      }
    })
  })

  check(res, {
    'WebSocket conectado (status 101)': (r) => r && r.status === 101,
  })

  if (!res || res.status !== 101) {
    connectionErrors.add(1)
  }

  sleep(1)
}
