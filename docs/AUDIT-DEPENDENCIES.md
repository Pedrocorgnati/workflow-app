# AUDIT-DEPENDENCIES — Cross-Module Dependencies

**Data:** 2026-03-15
**Módulo:** module-12-integration (TASK-0/ST003)
**Workspace:** ai-forge/workflow-app/

---

## 1. Status de Importações Cross-Module

Todos os 8 pares de importação verificados passam sem erro:

| # | Importação | Status |
|---|------------|--------|
| 1 | `from workflow_app.remote.protocol import MessageType, WsEnvelope` | ✅ OK |
| 2 | `from workflow_app.remote.constants import DEFAULT_PORT, THROTTLE_PC_MS` | ✅ OK |
| 3 | `from workflow_app.remote.remote_server import RemoteServer` | ✅ OK |
| 4 | `from workflow_app.remote.signal_bridge import SignalBridge` | ✅ OK |
| 5 | `from workflow_app.remote.output_throttle import OutputThrottle` | ✅ OK |
| 6 | `from workflow_app.remote.heartbeat_manager import HeartbeatManager` | ✅ OK |
| 7 | `from workflow_app.remote.tailscale import TailscaleDetector` | ✅ OK |
| 8 | `from workflow_app.remote.ip_validator import IPValidator` | ✅ OK |

**Coleta pytest:** 192 testes coletados, 0 erros de importação.

---

## 2. Divergências de Contrato de Protocolo (BLOQUEADORES)

### DIV-001 — OutputThrottle: payload `output_chunk` incorreto

**Severidade:** P0 BLOCKER
**Arquivo:** `src/workflow_app/remote/output_throttle.py`, linha 95

**Problema:**
```python
# ATUAL (INCORRETO):
self._bridge._send_message("output_chunk", {"text": text})

# ESPERADO pelo protocolo (protocol.py linha 144-148):
# payload deve conter "lines": List[str]
# validate_payload() levanta KeyError se "lines" não estiver presente
```

**Impacto no Android (`android/app/src/main/java/.../connection/MessageParser.kt`, linha 161):**
```kotlin
// Android espera:
val lines = payload?.get("lines")?.jsonArray?.map { it.jsonPrimitive.content } ?: emptyList()
OutputChunkMsg(messageId, lines)
```

**Consequência:** Todo output enviado do PC resulta em `lines = emptyList()` no Android. A área de output sempre aparece vazia. Funcionalidade central quebrada.

**Correção necessária em `output_throttle.py`:**
```python
# Em _flush(), linha 94-95:
# Antes: text = "\n".join(self._buffer)
#        self._bridge._send_message("output_chunk", {"text": text})
# Depois:
lines = list(self._buffer)
self._bridge._send_message("output_chunk", {"lines": lines})
```

---

### DIV-002 — OutputThrottle: payload `output_truncated` com chave errada

**Severidade:** P0 BLOCKER
**Arquivo:** `src/workflow_app/remote/output_throttle.py`, linha 102

**Problema:**
```python
# ATUAL (INCORRETO):
self._bridge._send_message("output_truncated", {"lines_skipped": count})

# ESPERADO pelo protocolo (protocol.py linha 150-151):
# payload deve conter "lines_omitted"
# validate_payload() levanta KeyError se "lines_omitted" não estiver presente
```

**Impacto no Android (`MessageParser.kt`, linha 168):**
```kotlin
// Android espera:
val linesOmitted = payload?.get("lines_omitted")?.jsonPrimitive?.intOrNull ?: 0
OutputTruncatedMsg(messageId, linesOmitted)
```

**Consequência:** Indicador de truncamento no Android sempre exibe "0 linhas omitidas" mesmo quando há truncamento real.

**Correção necessária em `output_throttle.py`:**
```python
# Em _emit_truncated(), linha 102:
# Antes: self._bridge._send_message("output_truncated", {"lines_skipped": count})
# Depois:
self._bridge._send_message("output_truncated", {"lines_omitted": count})
```

---

## 3. Divergências de API da Spec vs Código Real

As seguintes divergências foram encontradas entre as specs das TASKs e a API real implementada. **Não são bugs** — são diferenças entre a spec original do WBS e a implementação real que os testes de integração precisam respeitar.

| # | Spec TASK | Código Real | Impacto nos Testes |
|---|-----------|-------------|-------------------|
| 1 | `RemoteServer(port=18765, bind_host="127.0.0.1")` | `RemoteServer(signal_bus, parent=None)` | Testes devem usar `RemoteServer(signal_bus)` |
| 2 | `ServerState.LISTENING / ServerState.CONNECTED` | `RemoteServerState.LISTENING / RemoteServerState.CONNECTED_CLIENT` | Importar `RemoteServerState` de `remote_server.py` |
| 3 | `src/remote/protocol.py` | `src/workflow_app/remote/protocol.py` | Path correto para imports |
| 4 | `PING_TIMEOUT_S` em `constants.py` | `PONG_TIMEOUT_MS = 10_000` em `heartbeat_manager.py` (constante local) | Importar de `heartbeat_manager`, não de `constants` |
| 5 | `RATE_LIMIT_MSG_S` | `RATE_LIMIT_MSG_PER_S` em `constants.py` | Nome correto para importação |

---

## 4. Padrão de Mock para Testes E2E

Para testes que instanciam `RemoteServer` com IP real Tailscale (100.x.x.x), é necessário mockar:

```python
# Mock 1: TailscaleDetector — retornar IP local em vez de IP Tailscale
from unittest.mock import patch
from workflow_app.remote.tailscale import TailscaleResult

with patch("workflow_app.remote.remote_server.TailscaleDetector") as mock_tailscale:
    mock_tailscale.return_value.detect.return_value = TailscaleResult(
        success=True, ip="127.0.0.1"
    )
    # instanciar RemoteServer aqui

# Mock 2: IPValidator — aceitar 127.0.0.1 (não está no range CGNAT 100.64.0.0/10)
from unittest.mock import patch

with patch("workflow_app.remote.remote_server.IPValidator") as mock_validator:
    mock_validator.return_value.is_valid_tailscale_ip.return_value = True
    # servidor aceita conexões de 127.0.0.1
```

**Porta para testes:** usar `18765` (DEFAULT_PORT) pois testes rodam isolados.

---

## 5. Constante `PONG_TIMEOUT_MS` — Não em constants.py

`PONG_TIMEOUT_MS = 10_000` está definida localmente em `heartbeat_manager.py` e não exportada em `constants.py`. Isso é consistente com o design (só o HeartbeatManager precisa dela), mas testes que verificam o timeout de pong devem importar/referenciar de `heartbeat_manager`.

---

## 6. Resumo de Ações Necessárias

| ID | Tipo | Arquivo | Ação | Prioridade |
|----|------|---------|------|------------|
| DIV-001 | BUG | `output_throttle.py:95` | Trocar `{"text": text}` por `{"lines": list(self._buffer)}` | P0 |
| DIV-002 | BUG | `output_throttle.py:102` | Trocar `"lines_skipped"` por `"lines_omitted"` | P0 |
| API-1 | INFO | Testes | Usar `RemoteServer(signal_bus)` não `RemoteServer(port=...)` | — |
| API-2 | INFO | Testes | Usar `RemoteServerState.CONNECTED_CLIENT` não `ServerState.CONNECTED` | — |
| API-3 | INFO | Testes | Mock TailscaleDetector + IPValidator para testes locais | — |
