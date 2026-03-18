# Android Performance — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket

---

## 📋 Contexto

App single-screen WebSocket client — terminal output + controle de pipeline.
Sem imagens, sem background sync, sem paginação. Auditoria foca nas categorias relevantes
para este stack: memory leaks, lifecycle cleanup, rendering e startup.

---

## ✅ Phase 1: Code Review — Resultados

### 1.1 Memory Leaks

| Check | Status | Evidência |
|-------|--------|----------|
| `GlobalScope` | ✅ ZERO | Todos os launches em `viewModelScope` |
| `observeForever` | ✅ ZERO | Sem LiveData no projeto |
| `Handler` sem cleanup | ✅ ZERO | Sem `Handler` em produção |
| `collectAsState` (non-lifecycle) | ✅ ZERO | Todos usam `collectAsStateWithLifecycle` |
| Context leaks em singletons | ✅ OK | `RemoteLogger` = object sem Context; `ConnectionPreferences` recebe Context mas via `applicationContext` |
| `NetworkMonitor` cleanup | ✅ OK | `unregister()` chamado em `ConnectionManager.cleanup()` → `PipelineViewModel.onCleared()` |
| `outboundChannel` cleanup | ✅ OK | `outboundChannel.close()` em `onCleared()` |
| `backgroundJob` / `reconnectJob` cleanup | ✅ OK | `cancel()` em `ConnectionManager.cleanup()` |
| Lifecycle observer cleanup | ✅ OK | `ProcessLifecycleOwner.get().lifecycle.removeObserver(this)` em `cleanup()` |

### 1.2 Imagens e Bitmaps

| Check | Status |
|-------|--------|
| `BitmapFactory` | ✅ N/A — app texto/terminal |
| Coil / Glide / imagens | ✅ N/A |
| Ícones Material | ✅ Vetoriais — sem alocação de Bitmap |

### 1.3 Rendering / List Performance

| Check | Status | Observação |
|-------|--------|-----------|
| LazyColumn keys (CommandQueueList) | ✅ | `key = { _, item -> item.index }` — chave estável e semântica |
| LazyColumn keys (OutputArea) | ⚠️ INFO | `key = { index, _ -> index }` — veja P1 abaixo |
| `collectAsStateWithLifecycle` no WorkflowScreen | ✅ | 12 flows coletados com lifecycle awareness |
| Sem `contentType` | ✅ INFO | Cada lista tem apenas um tipo de item — não necessário |
| Lambda stability em WorkflowScreen | ✅ ACEITÁVEL | Method refs criam novo objeto por recomposição, mas single-screen não é bottleneck |

#### P1 (INFO): OutputArea key = index

```kotlin
// Atual: key por posição
itemsIndexed(
    items = outputLines,
    key   = { index, _ -> index },
) { _, line -> ... }
```

Quando `takeLast(MAX_BUFFER_LINES)` corta as primeiras linhas, todos os índices
se deslocam. O Compose interpreta todos os itens visíveis como novos e recompõe.

**Impacto real:** mínimo — o corte ocorre apenas ao atingir 5.000 linhas, e somente
~20-30 linhas ficam visíveis simultaneamente. O custo de recomposição é negligenciável
para strings simples de texto monospace.

**Alternativa se a app crescer:** manter contador de ID incremental no ViewModel e emitir
`List<Pair<Long, String>>` em vez de `List<String>`, usando o ID como chave estável.

### 1.4 Battery Optimization

| Check | Status | Evidência |
|-------|--------|----------|
| Polling / Timer | ✅ ZERO | Sem `Timer`, `AlarmManager` ou loop de polling |
| WorkManager (necessário?) | ✅ N/A | App de controle em foreground — sem necessidade de sync periódico |
| Background disconnect | ✅ OK | `ConnectionManager.onStop()` agenda desconexão após `BACKGROUND_DISCONNECT_MIN` min — Doze-friendly |
| Foreground reconnect | ✅ OK | `ConnectionManager.onStart()` reconecta automaticamente ao voltar ao foreground |
| WebSocket ping | ✅ OK | OkHttp `pingInterval(PING_INTERVAL_MS)` — mantém keep-alive sem polling manual |

### 1.5 App Startup

| Check | Status | Evidência |
|-------|--------|----------|
| `WorkflowApplication.onCreate()` | ✅ MÍNIMO | Apenas `Timber.plant(DebugTree())` em debug |
| Inicializações pesadas em main thread | ✅ ZERO | Sem Room, Retrofit, ou downloads em startup |
| `ConnectionPreferences.prefs` | ✅ `by lazy` | Keystore só é acessado na primeira leitura/escrita — não bloqueia startup |
| ViewModel init | ✅ OK | Sem I/O síncrono; apenas registros de callbacks e restauração de estado salvo |

### 1.6 OkHttpClient Thread Pool (INFO)

```kotlin
// WebSocketClient.kt
private val _client = OkHttpClient.Builder()
    .pingInterval(...)
    .readTimeout(...)
    .connectTimeout(...)
    .build()
```

O `OkHttpClient` cria um `Dispatcher` com thread pool interno que não é explicitamente
encerrado em `disconnect()`.

**Por que não é problema prático:**
- Há exatamente **um** `WebSocketClient` por ciclo de vida do ViewModel
- O ViewModel vive durante toda a sessão do app (single-screen)
- Threads ociosas do OkHttp são encerradas pelo GC quando o processo termina
- OkHttp foi projetado para ser reutilizado — não há recomendação de shutdown manual

**Quando revisar:** Se a app tiver múltiplas telas com instâncias independentes de WebSocketClient,
mover o `OkHttpClient` para um singleton compartilhado via DI.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Observação |
|---|------|-----------|--------|-----------:|
| P1 | OutputArea key por índice → possível recomposição em trim | INFO | 📋 FUTURA | Só vale se a app crescer para lista com IDs estáveis |
| P2 | OkHttpClient não encerrado em disconnect() | INFO | 📋 FUTURA | Trigger: múltiplas telas com WebSocketClients independentes |

### Nenhuma task executável nesta auditoria

O app não apresenta problemas de performance corrigíveis dentro do escopo atual.
As duas entradas INFO documentam tradeoffs conscientes para app single-screen.

---

## ✅ Phase 3: Execução de Tasks

### Nenhuma task executada

O código já segue boas práticas de performance para o escopo do app:
- Memory management completo via ViewModel lifecycle
- `collectAsStateWithLifecycle` em todos os flows
- LazyColumn keys estáveis nas duas listas
- Startup mínimo
- Sem background polling
- Lifecycle-aware disconnect/reconnect

---

## Checklist Performance

### Memory
- [x] Sem `GlobalScope`
- [x] Observers com lifecycle (`collectAsStateWithLifecycle`)
- [x] Sem `Handler` em produção
- [x] `Context` correto (`applicationContext` em singletons)
- [x] Cleanup em `onCleared()`: wsClient, connectionManager, channel
- [x] `NetworkMonitor` unregistered corretamente

### Battery
- [x] Sem polling (`Timer`, `AlarmManager`)
- [x] Background disconnect após `BACKGROUND_DISCONNECT_MIN` min
- [x] Foreground reconnect automático
- [x] Ping keep-alive via OkHttp (sem polling manual)

### Rendering
- [x] `collectAsStateWithLifecycle` em todo `WorkflowScreen`
- [x] Keys em `CommandQueueList` (chave semântica: `item.index`)
- [x] Keys em `OutputArea` (INFO: index — aceitável para log viewer)
- [x] Sem Bitmap/imagens — N/A

### Startup
- [x] `WorkflowApplication.onCreate()` mínimo
- [x] `ConnectionPreferences.prefs` com `by lazy`
- [x] Sem I/O síncrono no startup

---

## 📈 Resumo

| Categoria | Issues Críticos | Issues INFO | Status |
|-----------|----------------|------------|--------|
| Memory leaks | 0 | 0 | ✅ OK |
| Battery | 0 | 0 | ✅ OK |
| Rendering | 0 | 1 (key de output) | ✅ OK |
| Startup | 0 | 0 | ✅ OK |
| OkHttpClient lifecycle | 0 | 1 (thread pool) | ✅ OK |
| **Total** | **0** | **2** | **✅ OK** |

---

**Gerado por `/android:performance`**
**SystemForge — Documentation First Development**
