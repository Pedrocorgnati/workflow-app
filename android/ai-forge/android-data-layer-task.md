# Android Data Layer — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket | SharedPreferences

---

## 📋 Contexto

O app Android é um **cliente remoto leve** que controla pipelines via WebSocket (OkHttp).
Não usa Room Database nem Retrofit (correto — WebSocket puro é a stack certa para este caso).

---

## ✅ Phase 1: Code Review — Resultados

### Room Database
**Status:** ⏭️ Não aplicável
- App é cliente WebSocket puro — persistência local não é necessária
- Dados de pipeline são temporários (in-memory via StateFlow)
- **Decisão correta:** não usar Room para dados efêmeros de streaming

### DataStore / SharedPreferences
**Status:** ⚠️ 2 issues encontrados

#### Issue 1: Dual SharedPreferences para os mesmos dados [HIGH]
**Arquivos:** `ConnectionPreferences.kt`, `ConnectionManager.kt`, `PipelineViewModel.kt`

```
Problema: IP/porta são persistidos em DOIS lugares distintos:
  1. "connection_prefs_encrypted" — EncryptedSharedPreferences (ConnectionPreferences)
     → salvo após CONNECTED (endereço confirmado funcional)
  2. "remote_settings" — plain SharedPreferences (ConnectionManager via ViewModel)
     → salvo antes de conectar (intenção de conexão)

Resultado: ViewModel tem fallback 3-way no init:
  SavedStateHandle → ConnectionPreferences → connectionManager.loadSettings()
```

**Root cause:** `ConnectionManager` recebe `prefs: SharedPreferences` para gerenciar reconexão,
mas `ConnectionPreferences` (encrypted) já cobre o mesmo dado de forma mais segura.

**Fix recomendado (para sprint futura):**
1. Injetar `ConnectionPreferences` em `ConnectionManager` ao invés de `SharedPreferences`
2. `ConnectionManager.saveSettings()` → delegar a `ConnectionPreferences`
3. Remover `prefs: SharedPreferences` do `ConnectionManager`
4. Simplificar init do ViewModel para fallback 2-way: `SavedStateHandle → ConnectionPreferences`
5. Atualizar `LifecycleTest` para usar Robolectric ou mock de `ConnectionPreferences`

**Impacto:** Segurança (dados não encriptados em "remote_settings") + manutenibilidade

#### Issue 2: SharedPreferences criado diretamente no ViewModel [MEDIUM]
**Arquivo:** `PipelineViewModel.kt:76-78`

```kotlin
// ATUAL (anti-pattern)
private val prefs = app.getSharedPreferences(
    "remote_settings", android.content.Context.MODE_PRIVATE
)
```

**Fix recomendado:** Extrair para `ConnectionRepository` e injetar no ViewModel.

### Network (Retrofit/OkHttp)
**Status:** ✅ 1 fix implementado, 1 recomendação

#### Issue 3: Dual JSON libraries [LOW] — ✅ CORRIGIDO
**Arquivo:** `MessageParser.kt`, `WebSocketClient.kt`

O código usava `org.json.JSONObject` para serialização outbound e `kotlinx.serialization.json`
para deserialização inbound — duas bibliotecas para o mesmo propósito.

**Correções implementadas:**
- `MessageParser.parse()`: migrado de `org.json.JSONObject` → `kotlinx.serialization.json`
- `MessageParser.serialize()`: migrado de `JSONObject.apply{}` → `buildJsonObject{}`
- `WsEnvelope.payload()`: removido (dead code — nenhum caller encontrado)
- `WebSocketClient.send(type, JSONObject)`: removido (dead code — nenhum caller encontrado)
- `import org.json.JSONObject` removido de ambos os arquivos

**Antes:**
```kotlin
// serialize (org.json)
fun serialize(type: String, payload: JSONObject): String {
    val envelope = JSONObject().apply {
        put("message_id", UUID.randomUUID().toString())
        ...
    }
    return envelope.toString()
}

// parse (org.json)
val obj = org.json.JSONObject(raw)
val messageId = obj.optString("message_id", "")
```

**Depois:**
```kotlin
// serialize (kotlinx)
fun serialize(type: String, payload: JsonObject): String {
    val envelope = buildJsonObject {
        put("message_id", UUID.randomUUID().toString())
        ...
    }
    return envelope.toString()
}

// parse (kotlinx)
val root = Json.parseToJsonElement(raw).jsonObject
val messageId = root["message_id"]?.jsonPrimitive?.contentOrNull ?: ""
```

### Repository Pattern
**Status:** ⚠️ Ausente — recomendado para sprint futura

**Atual:** ViewModel acessa `SharedPreferences` diretamente via `ConnectionManager` e `ConnectionPreferences`.

**Recomendado:**
```kotlin
// Adicionar:
interface ConnectionRepository {
    fun loadLastEndpoint(): Pair<String, Int>?  // ip to port
    fun saveEndpoint(ip: String, port: Int)
    fun clearEndpoint()
}

class ConnectionRepositoryImpl @Inject constructor(
    private val prefs: ConnectionPreferences
) : ConnectionRepository {
    override fun loadLastEndpoint(): Pair<String, Int>? {
        val ip = prefs.loadIp().takeIf { it.isNotEmpty() } ?: return null
        return ip to prefs.loadPort()
    }
    override fun saveEndpoint(ip: String, port: Int) = prefs.save(ip, port)
    override fun clearEndpoint() = prefs.clear()
}
```

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Arquivo(s) |
|---|------|-----------|--------|-----------|
| T1 | ~~Migrar org.json → kotlinx.serialization~~ | LOW | ✅ FEITO | MessageParser.kt, WebSocketClient.kt |
| T2 | ~~Remover dead code (payload(), send(JSONObject))~~ | LOW | ✅ FEITO | MessageParser.kt, WebSocketClient.kt |
| T3 | Consolidar dual SharedPreferences em ConnectionPreferences | HIGH | 📋 PENDENTE | ConnectionManager.kt, PipelineViewModel.kt, LifecycleTest.kt |
| T4 | Extrair ConnectionRepository | MEDIUM | 📋 PENDENTE | Nova classe + ViewModel |
| T5 | Migrar SharedPreferences → DataStore Preferences | MEDIUM | 📋 PENDENTE | ConnectionPreferences.kt |

---

## ✅ Phase 3: Execução de Tasks

### T1 + T2: CONCLUÍDAS ✅

**Arquivos modificados:**

**`MessageParser.kt`**
- Removido: `import org.json.JSONObject`
- Adicionado: `import kotlinx.serialization.json.JsonObject`, `buildJsonObject`, `put`
- Migrado: `parse()` de org.json → kotlinx
- Migrado: `serialize(type, JSONObject)` → `serialize(type, JsonObject)`
- Migrado: `serialize(type, Map)` — usa `buildJsonObject` internamente
- Migrado: `serialize(type)` — usa `buildJsonObject {}` como empty payload
- Removido: `WsEnvelope.payload(): JSONObject` (dead code)

**`WebSocketClient.kt`**
- Removido: `import org.json.JSONObject`
- Removido: `fun send(type: String, payload: JSONObject)` (dead code)

### T3-T5: PENDENTES

Requerem:
- T3: Refatoração de `ConnectionManager` + atualização de `LifecycleTest`
- T4: Criação de nova interface + impl + DI wiring
- T5: Migração de EncryptedSharedPreferences → DataStore (requer `androidx.datastore:datastore-preferences-core` + wrapper de criptografia)

---

## Checklist Data Layer

### Room
- [x] ⏭️ Room não aplicável (WebSocket client, sem dados locais)

### DataStore / SharedPreferences
- [ ] T3: Consolidar dual SharedPreferences
- [ ] T4: Extrair ConnectionRepository
- [ ] T5: Migrar para DataStore Preferences

### Network
- [x] T1: Serialização unificada (kotlinx.serialization) ✅
- [x] T2: Dead code removido (WsEnvelope.payload, WebSocketClient.send) ✅
- [x] Error handling: WsEnvelope whitelist + dedup em MessageParser ✅
- [x] Reconnect: BackoffStrategy com exponential backoff ✅
- [x] Ping: OkHttp ping interval configurado ✅

### Repository
- [ ] T4: ConnectionRepository (Single Source of Truth)

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Serialização JSON | 1 | 1 | 0 |
| Dead Code | 2 | 2 | 0 |
| SharedPreferences | 2 | 0 | 2 |
| Repository Pattern | 1 | 0 | 1 |
| **Total** | **6** | **3** | **3** |

---

**Gerado por `/android:data-layer`**
**SystemForge — Documentation First Development**

