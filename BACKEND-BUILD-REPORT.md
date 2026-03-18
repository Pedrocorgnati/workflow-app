# Backend Build Report

**Projeto:** workflow-app / feature: workflow-mobile
**Stack:** Python/PySide6 + QWebSocketServer (PC) · Kotlin/OkHttp (Android)
**Modo:** COMPLEMENTAR — arquivos existentes não foram sobrescritos
**Data:** 2026-03-15

---

## Estrutura Gerada

### DTOs / Schemas (1 arquivo)

| Arquivo | Entidades |
|---------|-----------|
| `src/workflow_app/remote/dtos.py` | WsEnvelope, QueueItem, InteractionPayload, PipelineSnapshot, ControlPayload, InteractionResponsePayload, OutputTruncatedPayload, ErrorPayload |

### Componentes PC — Python (6 arquivos novos + 1 modificado)

| Arquivo | Responsabilidade |
|---------|-----------------|
| `src/workflow_app/remote/__init__.py` | Expõe RemoteServer e SignalBridge |
| `src/workflow_app/remote/constants.py` | Constantes de protocolo (sync com Android RemoteConstants.kt) |
| `src/workflow_app/remote/message_serializer.py` | Serialização JSON, tradução PT→EN de status |
| `src/workflow_app/remote/heartbeat_manager.py` | QTimer → QWebSocket.ping() a cada 30 s |
| `src/workflow_app/remote/output_throttle.py` | Buffer de output, flush 100 ms / 4 KB |
| `src/workflow_app/remote/remote_server.py` | QWebSocketServer, conexão única, RemoteServerState |
| `src/workflow_app/remote/signal_bridge.py` | Bridge bidirecional SignalBus ↔ protocolo WebSocket |
| `src/workflow_app/pipeline/pipeline_manager.py` | **Modificado:** adicionado `send_interactive_response()` |

### Componentes Android — Kotlin (3 arquivos novos)

| Arquivo | Responsabilidade |
|---------|-----------------|
| `android/.../connection/MessageParser.kt` | Parse/serialize envelopes JSON (org.json) |
| `android/.../connection/WebSocketClient.kt` | OkHttp WebSocket, reconexão, ping 30 s |
| `android/.../connection/ConnectionManager.kt` | Backoff, NetworkCallback, Doze mode, SharedPreferences |

### Testes (2 arquivos)

| Arquivo | Cobertura |
|---------|-----------|
| `tests/remote/test_message_serializer.py` | 12 testes — serialize, deserialize, traduções de status |
| `tests/remote/test_output_throttle.py` | 9 testes — buffer, flush, truncation, batch limit |

---

## Stubs Pendentes

Os seguintes métodos são stubs aguardando implementação via `/auto-flow execute`:

| Componente | Método | Módulo WBS |
|-----------|--------|------------|
| `RemoteServer._detect_tailscale_ip` | Detecção de IP via `netifaces` (fallback funcional via socket) | module-2/TASK-1 |
| `PipelineViewModel` (Android) | `_onMessage`, `sendControl`, `sendInteractionResponse` | module-7/TASK-1,2,3 |
| `WorkflowScreen` (Android) | Compose UI completo | module-8 |

---

## Próximos Passos

1. `/auto-flow execute module-2` — implementar RemoteServer (integrar ao MainWindow toggle)
2. `/auto-flow execute module-3` — completar SignalBridge com testes de integração
3. `/auto-flow execute module-4` — validar OutputThrottle end-to-end
4. `/auto-flow execute module-5` — UI feedback no PC (toggle button, ícone verde)
5. `/auto-flow execute module-6,7,8,9` — Android: WebSocketClient → ViewModel → UI
6. `/env-creation` — configurar variáveis de ambiente se necessário
7. `/integration-test-create` — testes de contrato WebSocket (module-11)
