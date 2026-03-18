# AUDIT-INVENTORY — Module-12 Integration

**Data:** 2026-03-15
**Módulo:** module-12-integration (TASK-0/ST001)
**Workspace:** ai-forge/workflow-app/

---

## Sumário

| Categoria | Total | ✅ Presente | ❌ Ausente | ⚠️ Divergência |
|-----------|-------|------------|-----------|----------------|
| Python Remote — Source | 13 | 13 | 0 | 1 |
| Python Remote — Tests | 15 | 15 | 0 | 0 |
| Android — Source | 28 | 28 | 0 | 0 |
| Android — Tests (unit) | 11 | 11 | 0 | 0 |
| Android — Tests (instrumented) | 3 | 3 | 0 | 0 |
| **TOTAL** | **70** | **70** | **0** | **1** |

---

## Python Remote — Source (`src/workflow_app/remote/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 1 | `__init__.py` | ✅ | Módulo inicializado |
| 2 | `constants.py` | ✅ | DEFAULT_PORT=18765, PORT_SCAN_RANGE, THROTTLE_PC_MS=100, MAX_BATCH_KB=4, PING_INTERVAL_S=30, RATE_LIMIT_MSG_PER_S=20, DEDUP_SET_LIMIT=10_000 |
| 3 | `dtos.py` | ✅ | DTOs de transferência |
| 4 | `heartbeat_manager.py` | ✅ | PONG_TIMEOUT_MS=10_000 (constante local, não em constants.py) |
| 5 | `ip_validator.py` | ✅ | Valida CGNAT 100.64.0.0/10 |
| 6 | `message_serializer.py` | ✅ | Serialização PT→EN |
| 7 | `metrics.py` | ✅ | Métricas de performance |
| 8 | `output_throttle.py` | ⚠️ | DIVERGÊNCIA: `_flush()` envia `{"text": text}` mas protocolo espera `{"lines": List[str]}` para tipo `output_chunk` |
| 9 | `protocol.py` | ✅ | WsEnvelope, MessageType (10), ControlAction (3), ResponseType (4), CommandStatus (6), PipelineStatus (8) |
| 10 | `remote_server.py` | ✅ | RemoteServer(signal_bus, parent=None) — API real difere da spec TASK (ver AUDIT-DEPENDENCIES.md) |
| 11 | `signal_bridge.py` | ✅ | SignalBridge com 12+ signals |
| 12 | `snapshot_builder.py` | ✅ | Snapshot para sync_request |
| 13 | `tailscale.py` | ✅ | TailscaleDetector, TailscaleResult |

---

## Python Remote — Tests (`tests/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 1 | `remote/__init__.py` | ✅ | |
| 2 | `remote/test_heartbeat_manager.py` | ✅ | |
| 3 | `remote/test_ip_validator.py` | ✅ | |
| 4 | `remote/test_message_serializer.py` | ✅ | |
| 5 | `remote/test_metrics.py` | ✅ | |
| 6 | `remote/test_output_throttle.py` | ✅ | |
| 7 | `remote/test_remote_server_feedback.py` | ✅ | |
| 8 | `remote/test_remote_server_guards.py` | ✅ | |
| 9 | `remote/test_remote_server.py` | ✅ | Padrão: mock TailscaleDetector → ip="100.64.0.1" |
| 10 | `remote/test_signal_bridge.py` | ✅ | |
| 11 | `remote/test_snapshot_builder.py` | ✅ | |
| 12 | `remote/test_tailscale.py` | ✅ | |
| 13 | `remote/test_toast_notifier.py` | ✅ | |
| 14 | `test_protocol_contract.py` | ✅ | Contrato Python↔Android (module-11) |
| 15 | `test_enum_compatibility.py` | ✅ | Compatibilidade de enums (module-11) |

**Total coletado pelo pytest (smoke check):** 192 testes, 0 erros de coleta.

---

## Android — Source

### Connection Layer (`android/app/src/main/java/com/workflowapp/remote/connection/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 1 | `BackoffStrategy.kt` | ✅ | Exponencial: 2s, 4s, 8s, 16s, cap 60s |
| 2 | `ConnectionManager.kt` | ✅ | |
| 3 | `MessageParser.kt` | ✅ | |
| 4 | `NetworkMonitor.kt` | ✅ | ConnectivityManager + NetworkCallback |
| 5 | `RemoteConstants.kt` | ✅ | |
| 6 | `WebSocketClient.kt` | ✅ | OkHttp 4.12+ |

### Data Layer (`android/app/src/main/java/com/workflowapp/remote/data/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 7 | `ConnectionPreferences.kt` | ✅ | SharedPreferences para IP/porta |

### Models (`android/app/src/main/java/com/workflowapp/remote/model/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 8 | `CommandItem.kt` | ✅ | |
| 9 | `ConnectionStatus.kt` | ✅ | |
| 10 | `LastPipelineSummary.kt` | ✅ | |
| 11 | `Messages.kt` | ✅ | |
| 12 | `PipelineViewState.kt` | ✅ | |
| 13 | `WsMessageType.kt` | ✅ | |

### UI Components (`android/app/src/main/java/com/workflowapp/remote/ui/components/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 14 | `CommandQueueList.kt` | ✅ | |
| 15 | `ConnectionBar.kt` | ✅ | |
| 16 | `ControlBar.kt` | ✅ | |
| 17 | `FeedbackSnackbar.kt` | ✅ | |
| 18 | `IdleState.kt` | ✅ | |
| 19 | `InteractionCard.kt` | ✅ | |
| 20 | `OutputArea.kt` | ✅ | |

### UI Theme (`android/app/src/main/java/com/workflowapp/remote/ui/theme/`)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 21 | `Color.kt` | ✅ | |
| 22 | `Theme.kt` | ✅ | Graphite Amber D19 / Material3 darkColorScheme |
| 23 | `Type.kt` | ✅ | |

### App Root

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 24 | `ui/WorkflowScreen.kt` | ✅ | Tela principal (180+ linhas) |
| 25 | `util/RemoteLogger.kt` | ✅ | |
| 26 | `viewmodel/PipelineViewModel.kt` | ✅ | |
| 27 | `MainActivity.kt` | ✅ | |
| 28 | `WorkflowApplication.kt` | ✅ | |

---

## Android — Tests (JVM Unit Tests)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 1 | `connection/BackoffStrategyTest.kt` | ✅ | |
| 2 | `connection/LifecycleTest.kt` | ✅ | |
| 3 | `connection/MessageParserTest.kt` | ✅ | |
| 4 | `connection/NetworkMonitorTest.kt` | ✅ | |
| 5 | `connection/WebSocketClientTest.kt` | ✅ | |
| 6 | `data/ConnectionPreferencesTest.kt` | ✅ | |
| 7 | `EnumCompatibilityTest.kt` | ✅ | Contrato cross-platform (module-11) |
| 8 | `model/StateMachineTest.kt` | ✅ | |
| 9 | `ProtocolContractTest.kt` | ✅ | Contrato cross-platform (module-11) |
| 10 | `ui/FeedbackSnackbarTest.kt` | ✅ | |
| 11 | `viewmodel/PipelineViewModelTest.kt` | ✅ | |

---

## Android — Tests (Instrumented)

| # | Arquivo | Status | Notas |
|---|---------|--------|-------|
| 1 | `ui/AccessibilityTest.kt` | ✅ | |
| 2 | `ui/ComponentTests.kt` | ✅ | |
| 3 | `ui/WorkflowScreenTest.kt` | ✅ | |

---

## Artefatos Faltantes

**Nenhum.** Todos os 70 arquivos esperados estão presentes no workspace.

---

## Divergência Identificada

| ID | Arquivo | Tipo | Descrição | Impacto |
|----|---------|------|-----------|---------|
| DIV-001 | `src/workflow_app/remote/output_throttle.py` | Payload | `_flush()` envia `{"text": text}` mas `WsEnvelope.validate_payload()` espera `{"lines": List[str]}` para tipo `output_chunk` | POTENCIAL BLOCKER — Android pode falhar ao parsear mensagens de output |
