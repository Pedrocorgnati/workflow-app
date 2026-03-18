# Android Architecture — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket | SharedPreferences

---

## 📋 Contexto

O app Android é um **cliente remoto leve de tela única** que controla pipelines via WebSocket.
A arquitetura segue MVVM com StateFlow + SharedFlow para side effects. Por ser uma app
single-screen, Clean Architecture completa com Use Cases e módulos seria over-engineering.

---

## ✅ Phase 1: Code Review — Resultados

### Estrutura de Pacotes

```
com.workflowapp.remote/
├── model/           ✅ Camada de modelo pura (enums, data classes)
├── data/            ✅ Persistência (ConnectionPreferences com EncryptedSharedPreferences)
├── connection/      ✅ Infraestrutura WebSocket (WebSocketClient, ConnectionManager, MessageParser)
├── viewmodel/       ✅ MVVM ViewModel (PipelineViewModel)
├── ui/              ✅ Composables (WorkflowScreen + components/)
└── util/            ✅ Utilitários (RemoteLogger)
```

**Avaliação:** Separação de camadas correta para o escopo do app. Dependências fluem no
sentido correto: ui → viewmodel → connection/data/model.

### Clean Architecture — Achados

#### ✅ Correto: Separação model/ui

- `ConnectionStatus.canTransitionTo()` — lógica de estado no model (não no ViewModel)
- `PipelineViewState.fromString()` — parser no model, defensivo com lowercase
- Composables delegam toda lógica ao ViewModel (sem business logic na UI)

#### ✅ Correto: MVVM com StateFlow

- Estado via `StateFlow` (não LiveData): `connectionStatus`, `pipelineState`, `commandQueue`, etc.
- Side effects one-shot via `SharedFlow` (`errorEvent`, `feedbackEvents`, `interactiveModeEndedEvent`)
- Unidirectional Data Flow: ViewModel → StateFlow → Composable

#### ✅ Correto: Fila de mensagens outbound

- `Channel<String>(Channel.BUFFERED)` para envio FIFO sem bloquear a UI thread
- Debounce de 1 segundo em `sendControl()` previne double-tap

#### ⚠️ Issue 1: Compose UI no model layer [HIGH] — ✅ CORRIGIDO

**Arquivos:** `model/ConnectionStatus.kt`, `model/PipelineViewState.kt`

```
Problema: badgeColor e statusColor estavam definidas como extension functions
no model layer, importando androidx.compose.ui.graphics.Color.
Resultado: model dependia de Compose UI — violação de Clean Architecture.
```

**Correção implementada:**
- Criado `ui/theme/StatusColors.kt` com ambas as extensions
- Removidos `import androidx.compose.ui.graphics.Color` e as extensions de ambos os models
- `StateMachineTest.kt` atualizado para importar de `com.workflowapp.remote.ui.theme`

#### ⚠️ Issue 2: SharedPreferences criado diretamente no ViewModel [MEDIUM]

**Arquivo:** `viewmodel/PipelineViewModel.kt:76-78`

```kotlin
// ATUAL (anti-pattern)
private val prefs = app.getSharedPreferences(
    "remote_settings", android.content.Context.MODE_PRIVATE
)
```

**Root cause:** `ConnectionManager` recebe `prefs: SharedPreferences` para gerenciar
reconexão, mas `ConnectionPreferences` (EncryptedSharedPreferences) já cobre o mesmo
dado de forma mais segura. Há dois repositórios distintos para o mesmo dado (ver TASK-T3
em `android-data-layer-task.md`).

**Fix recomendado (sprint futura, vinculado a T3 do data-layer):**
- Injetar `ConnectionPreferences` em `ConnectionManager` ao invés de `SharedPreferences`
- Remover `prefs` direto do ViewModel

#### ℹ️ Issue 3: Sem DI Framework [LOW]

**Arquivo:** `viewmodel/PipelineViewModel.kt`

```kotlin
// Infraestrutura construída diretamente no ViewModel
internal val parser = MessageParser()
internal val networkMonitor = NetworkMonitor(app)
internal val wsClient = WebSocketClient(...)
internal val connectionManager = ConnectionManager(...)
```

**Avaliação:** Para app single-screen sem modularização, construção direta é aceitável.
Campos `internal` permitem testes unitários sem DI framework. Hilt/Dagger seria
recomendado apenas se o app crescer em complexidade.

#### ℹ️ Issue 4: Sem Use Cases [LOW]

**Arquivo:** `viewmodel/PipelineViewModel.kt`

Lógica de negócio (validação de IP/porta, substituição PLAY→RESUME, mensagens de feedback)
está no ViewModel. Para app single-screen, esta é a arquitetura correta — Use Cases
introduziriam complexidade desnecessária sem benefício tangível.

#### ℹ️ Issue 5: Cores hardcoded [LOW]

**Arquivo:** `ui/theme/StatusColors.kt` (e comentário TODO em `model/PipelineViewState.kt`)

Cores definidas como `Color(0xFF...)` em vez de tokens do MaterialTheme.
Marcado com `TODO module-8` no código. Não afeta corretude, apenas manutenibilidade de tema.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Arquivo(s) |
|---|------|-----------|--------|-----------:|
| A1 | ~~Mover color extensions para ui/theme (Compose no model)~~ | HIGH | ✅ FEITO | model/*.kt, ui/theme/StatusColors.kt |
| A2 | ~~Atualizar StateMachineTest para novo import de theme~~ | HIGH | ✅ FEITO | StateMachineTest.kt |
| A3 | Consolidar SharedPreferences em ConnectionPreferences (vinculado a T3 do data-layer) | MEDIUM | 📋 PENDENTE | PipelineViewModel.kt, ConnectionManager.kt |
| A4 | Avaliar Hilt para DI se app crescer em complexidade | LOW | 📋 FUTURA | — |
| A5 | Migrar cores hardcoded para MaterialTheme tokens (module-8) | LOW | 📋 FUTURA | ui/theme/StatusColors.kt |

---

## ✅ Phase 3: Execução de Tasks

### A1 + A2: CONCLUÍDAS ✅

**Arquivos modificados:**

**`model/ConnectionStatus.kt`**
- Removido: `import androidx.compose.ui.graphics.Color`
- Removido: `val ConnectionStatus.badgeColor: Color` extension function
- Adicionado: comentário referenciando `ui/theme/StatusColors.kt`

**`model/PipelineViewState.kt`**
- Removido: `import androidx.compose.ui.graphics.Color`
- Removido: `val PipelineViewState.statusColor: Color` extension function
- Adicionado: comentário referenciando `ui/theme/StatusColors.kt`

**`ui/theme/StatusColors.kt`** (arquivo NOVO)
- Criado com ambas as extensions `badgeColor` e `statusColor`
- Pacote: `com.workflowapp.remote.ui.theme`
- Importa de `model` (direção correta de dependência)

**`src/test/java/.../model/StateMachineTest.kt`**
- Adicionados: `import com.workflowapp.remote.ui.theme.badgeColor`
- Adicionados: `import com.workflowapp.remote.ui.theme.statusColor`
- Atualizado KDoc para referenciar `ui/theme/StatusColors.kt`

### A3: PENDENTE

Requer refatoração coordenada com T3 do `android-data-layer-task.md`:
1. Injetar `ConnectionPreferences` em `ConnectionManager`
2. Remover `prefs: SharedPreferences` do `ConnectionManager`
3. Remover `prefs = app.getSharedPreferences(...)` do ViewModel
4. Atualizar `LifecycleTest` — usa Robolectric mock de SharedPreferences

---

## Checklist Architecture

### Clean Architecture
- [x] Camadas separadas (model, data, connection, viewmodel, ui)
- [x] Dependências corretas (ui → viewmodel → model/data, model não depende de Compose)
- [x] ~~Color extensions fora do model layer~~ ✅ corrigido
- [ ] Repository pattern (A3 — consolidar SSOT)

### MVVM/MVI
- [x] Estado via StateFlow (não LiveData)
- [x] Side effects via SharedFlow/Channel (errorEvent, feedbackEvents)
- [x] Unidirectional Data Flow (ViewModel → StateFlow → Composable)
- [x] State machine guard (ConnectionStatus.canTransitionTo)

### Modelos
- [x] Enums com companion object para parsing (PipelineViewState.fromString)
- [x] Data classes imutáveis (val, não var)
- [x] Model puro sem dependências de Compose

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Compose no model layer | 1 | 1 | 0 |
| SharedPreferences duplicado | 1 | 0 | 1 |
| DI (avaliação futura) | 1 | 0 | 1 |
| Cores hardcoded (module-8) | 1 | 0 | 1 |
| **Total** | **4** | **1** | **3** |

---

**Gerado por `/android:architecture`**
**SystemForge — Documentation First Development**
