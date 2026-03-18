# Android Hardcodes — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket

---

## 📋 Contexto

App single-screen WebSocket. Constantes de protocolo/rede já estão centralizadas em
`connection/RemoteConstants.kt` (mirror do Python constants.py). Auditoria foca em
valores que escaparam deste sistema.

---

## ✅ Phase 1: Code Review — Resultados

### O que já estava correto

| Área | Status |
|------|--------|
| `RemoteConstants.kt` — centraliza 12+ constantes de protocolo | ✅ |
| `BackoffStrategy` usa `RemoteConstants.INITIAL_BACKOFF_S`, `MAX_BACKOFF_S`, `MAX_RETRY_ATTEMPTS` | ✅ |
| `ConnectionManager` usa `RemoteConstants.BACKGROUND_DISCONNECT_MIN`, `DEFAULT_HOST_PREF_KEY` | ✅ |
| `PipelineViewModel` usa `RemoteConstants.MAX_BUFFER_LINES`, `DEFAULT_PORT` | ✅ |
| `WebSocketClient` usa `RemoteConstants.PING_INTERVAL_MS` | ✅ |
| Sem URLs externas hardcoded (app é peer-to-peer local) | ✅ |
| Sem credenciais ou secrets no código | ✅ |

---

### Issues Encontradas

#### Issue 1: Constante duplicada e morta em OutputArea [HIGH]
**Arquivo:** `ui/components/OutputArea.kt:48`

```kotlin
// DUPLICATA: RemoteConstants.MAX_BUFFER_LINES já existe com o mesmo valor
// Não é referenciada em nenhum lugar do arquivo — constante morta
const val MAX_BUFFER_LINES = 5000
```

O ViewModel já usa `RemoteConstants.MAX_BUFFER_LINES` corretamente.

#### Issue 2: connectTimeout não extraído para RemoteConstants [MEDIUM]
**Arquivo:** `connection/WebSocketClient.kt:52`

```kotlin
// Único timeout de rede sem constante nomeada
.connectTimeout(10, TimeUnit.SECONDS)  // ← magic number
```

Todos os outros timeouts (`PING_INTERVAL_MS`, `PING_TIMEOUT_MS`) já estão em RemoteConstants.

#### Issue 3: delay(1000L) de debounce sem constante [MEDIUM]
**Arquivo:** `viewmodel/PipelineViewModel.kt:397`

```kotlin
// 1 segundo de debounce para sendControl() — sem contexto pelo nome
delay(1000L)
```

Leitores do código precisam inferir o propósito pelo contexto. Com constante nomeada,
a intenção fica explícita.

#### Issue 4: Jitter máximo hardcoded no BackoffStrategy [LOW]
**Arquivo:** `connection/BackoffStrategy.kt:35`

```kotlin
// 500ms de jitter máximo — sem nome nem referência a RemoteConstants
val jitter = Random.nextLong(0, 500)
```

O KDoc da classe menciona "500ms of random jitter" mas o valor não está em RemoteConstants
onde os demais parâmetros de backoff vivem.

#### Issue 5: Strings de UI não extraídas para strings.xml [INFO]
**Arquivos:** todos os composables

Strings de UI hardcoded em Kotlin (ex: "IP do servidor", "Conectar", "Resposta", "Enviar").

**Por que não é problema crítico:** App single-screen de controle interno, sem
requisito de localização (i18n). Extração para strings.xml traria overhead de
manutenção sem benefício prático para o escopo atual.

**Quando extrair:** Se houver plano de distribuição pública ou suporte a múltiplos idiomas.

#### Issue 6: Dimensões dp/sp não sistematizadas [INFO]
**Arquivos:** todos os composables

Valores de dimensão hardcoded (48.dp para touch targets, 8.dp/16.dp/24.dp para padding,
24.dp para ícones). São valores Material Design padrão, mas sem `MaterialTheme.spacing`.

**Por que não é problema crítico:** Valores consistentes com Material3 guidelines.
Sistema de spacing só vale a pena para app com múltiplas telas e design system completo.
Documentado como `TODO module-8` no codebase.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Arquivo(s) |
|---|------|-----------|--------|-----------:|
| HC1 | ~~Remover constante morta MAX_BUFFER_LINES de OutputArea~~ | HIGH | ✅ FEITO | OutputArea.kt |
| HC2 | ~~Extrair connectTimeout para RemoteConstants.CONNECT_TIMEOUT_S~~ | MEDIUM | ✅ FEITO | RemoteConstants.kt, WebSocketClient.kt |
| HC3 | ~~Extrair delay(1000L) para RemoteConstants.CONTROL_DEBOUNCE_MS~~ | MEDIUM | ✅ FEITO | RemoteConstants.kt, PipelineViewModel.kt |
| HC4 | ~~Extrair jitter 500L para RemoteConstants.MAX_JITTER_MS~~ | LOW | ✅ FEITO | RemoteConstants.kt, BackoffStrategy.kt |
| HC5 | Extrair strings para strings.xml | INFO | 📋 FUTURA | todos composables |
| HC6 | Sistema de spacing MaterialTheme (module-8) | INFO | 📋 FUTURA | todos composables |

---

## ✅ Phase 3: Execução de Tasks

### HC1: Constante morta removida ✅

`const val MAX_BUFFER_LINES = 5000` removida de `OutputArea.kt`.
`RemoteConstants.MAX_BUFFER_LINES` já é usado no ViewModel.

### HC2 + HC3 + HC4: RemoteConstants expandido ✅

**`RemoteConstants.kt`** — 3 constantes adicionadas:

```kotlin
const val CONNECT_TIMEOUT_S: Long    = 10L
/** Debounce applied to control commands (play/pause/skip) to prevent double-tap spam. */
const val CONTROL_DEBOUNCE_MS: Long  = 1_000L
/** Maximum random jitter added to each backoff interval to prevent thundering herd. */
const val MAX_JITTER_MS: Long        = 500L
```

**`WebSocketClient.kt`:**
```kotlin
// Antes
.connectTimeout(10, TimeUnit.SECONDS)

// Depois
.connectTimeout(RemoteConstants.CONNECT_TIMEOUT_S, TimeUnit.SECONDS)
```

**`PipelineViewModel.kt`:**
```kotlin
// Antes
delay(1000L)

// Depois
delay(RemoteConstants.CONTROL_DEBOUNCE_MS)
```

**`BackoffStrategy.kt`:**
```kotlin
// Antes
val jitter = Random.nextLong(0, 500)

// Depois
val jitter = Random.nextLong(0, RemoteConstants.MAX_JITTER_MS)
```

---

## Estado do RemoteConstants.kt (pós-auditoria)

```kotlin
object RemoteConstants {
    const val DEFAULT_PORT: Int          = 18765   // ← protocolo
    const val THROTTLE_PC_MS: Int        = 100     // ← protocolo
    const val THROTTLE_ANDROID_MS: Int   = 200     // ← protocolo
    const val MAX_BATCH_KB: Int          = 4       // ← protocolo
    const val MAX_BUFFER_LINES: Int      = 5000    // ← UI buffer
    const val INITIAL_BACKOFF_S: Long    = 2L      // ← reconexão
    const val MAX_BACKOFF_S: Long        = 60L     // ← reconexão
    const val MAX_RETRY_ATTEMPTS: Int    = 3       // ← reconexão
    const val BACKGROUND_DISCONNECT_MIN: Int = 5  // ← lifecycle
    const val PING_INTERVAL_MS: Long     = 30_000L // ← WebSocket
    const val PING_TIMEOUT_MS: Long      = 10_000L // ← WebSocket
    const val CONNECT_TIMEOUT_S: Long    = 10L     // ← WebSocket ✅ NOVO
    const val CONTROL_DEBOUNCE_MS: Long  = 1_000L  // ← ViewModel ✅ NOVO
    const val MAX_JITTER_MS: Long        = 500L    // ← backoff   ✅ NOVO
    const val SYNC_OUTPUT_LINES: Int     = 500     // ← protocolo
    const val RATE_LIMIT_MSG_PER_S: Int  = 20      // ← protocolo
    const val DEFAULT_HOST_PREF_KEY: String = "last_host"
    const val DEFAULT_PORT_PREF_KEY: String = "last_port"
}
```

---

## Checklist Hardcodes

### Strings
- [x] Sem credenciais ou secrets hardcoded
- [x] Sem URLs externas hardcoded (peer-to-peer local)
- [ ] Strings de UI em strings.xml (futura — sem requisito de i18n atual)

### Números
- [x] Constantes de protocolo em RemoteConstants
- [x] Timeouts de rede em RemoteConstants
- [x] Delays de debounce em RemoteConstants
- [x] Parâmetros de backoff em RemoteConstants
- [x] Constante morta duplicada removida (MAX_BUFFER_LINES em OutputArea)

### Dimensões
- [x] Touch targets: 48.dp (Material3 standard) — aceitável sem design system
- [ ] Sistema de spacing MaterialTheme (module-8 — futura)

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Constante duplicada/morta | 1 | 1 | 0 |
| Magic numbers em constantes de rede | 3 | 3 | 0 |
| Strings de UI (i18n) | 1 | 0 | 1 (futura) |
| Sistema de spacing | 1 | 0 | 1 (module-8) |
| **Total** | **6** | **4** | **2** |

---

**Gerado por `/android:hardcodes`**
**SystemForge — Documentation First Development**
