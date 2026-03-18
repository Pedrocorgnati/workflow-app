# Android Jetpack Compose — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | Material3 | Coroutines/Flow

---

## 📋 Contexto

App single-screen com WebSocket. Todos os composables são stateless (estado no ViewModel),
com StateFlows expostos e `collectAsStateWithLifecycle()`. Sem Room, sem Paging.

---

## ✅ Phase 1: Code Review — Resultados

### O que já estava correto

| Padrão | Status |
|--------|--------|
| `collectAsStateWithLifecycle()` em todos os StateFlows | ✅ |
| `derivedStateOf { }` para `isAtBottom` em OutputArea | ✅ |
| `itemsIndexed(key = { _, item -> item.index })` em CommandQueueList | ✅ |
| `animateColorAsState`/`rememberInfiniteTransition` com `label` params | ✅ |
| `remember { SnackbarHostState() }` e `rememberLazyListState()` | ✅ |
| State hoisting: composables stateless, estado no ViewModel | ✅ |
| `CommandItem` é `data class` com primitivos — inferido como estável | ✅ |
| `LaunchedEffect` com keys corretas: `Unit`, `userId`, `connectionStatus` | ✅ |
| `AnimatedContent` com `label` em WorkflowScreen e OutputArea | ✅ |

---

### Issues Encontradas

#### Issue 1: LaunchedEffect com key Boolean em vez do objeto [MEDIUM]
**Arquivo:** `ui/components/InteractionCard.kt:59`

```kotlin
// ANTES: key = Boolean (interaction != null)
// Se segunda interaction substitui a primeira enquanto card está visível,
// o booleano não muda (true → true) → requestFocus() não é chamado novamente
LaunchedEffect(interaction != null) {
    if (interaction != null) {
        delay(300L)
        runCatching { focusRequester.requestFocus() }
    }
}
```

**Cenário do bug:** Pipeline emite interaction request → usuário não responde a tempo →
PC emite segunda interaction request → card já estava visível → key não muda →
campo de texto não é refocado para a nova prompt.

#### Issue 2: FAB condicional sem animação de entrada/saída [LOW]
**Arquivo:** `ui/components/OutputArea.kt:136`

```kotlin
// ANTES: Aparecimento/desaparecimento abrupto (pop-in/pop-out)
if (!autoScrollEnabled) {
    FloatingActionButton(...) { ... }
}
```

Todos os outros elementos condicionais da tela usam `AnimatedVisibility`
(InteractionCard usa `AnimatedVisibility` com slide+fade, AnimatedContent em
WorkflowScreen e OutputArea). O FAB era o único sem transição suave.

#### Issue 3: Informacional — sem @Stable/@Immutable [INFO]
**Arquivos:** `model/*.kt`

Nenhuma classe de modelo usa anotações de estabilidade Compose.

**Por que não é problema:**
- `CommandItem(Int, String, String)` — primitivos, Compose infere como estável
- `InteractionRequestMsg(String, String, String, List<String>)` — o `List<String>` é
  tecnicamente instável, mas esta classe só é passada como parâmetro em `InteractionCard`,
  que é chamado uma vez por tela. O overhead de recomposição extra é imperceptível.
- `FeedbackMessage` — sealed class/objects, estáveis
- Para o escopo atual (single-screen, lista pequena), anotações são desnecessárias.

#### Issue 4: Informacional — animação infinita em todas as linhas [INFO]
**Arquivo:** `ui/components/CommandQueueList.kt`

```kotlin
// rememberInfiniteTransition criado para TODA CommandItemRow,
// mas pulseAlpha só é aplicado quando status == "running"
val infiniteTransition = rememberInfiniteTransition(label = "runningPulse")
val pulseAlpha by infiniteTransition.animateFloat(...)

// Uso: apenas para running
.alpha(if (command.status == "running") pulseAlpha else 1f)
```

**Por que não é problema prático:** O pipeline típico tem < 20 comandos. O custo de
N animações infinitas simultâneas é negligível nessa escala. Além disso, Compose não
permite chamar `rememberInfiniteTransition` condicionalmente — uma refatoração não
traria benefício mensurável sem adicionar complexidade.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Arquivo(s) |
|---|------|-----------|--------|-----------:|
| CP1 | ~~Corrigir key do LaunchedEffect em InteractionCard~~ | MEDIUM | ✅ FEITO | InteractionCard.kt |
| CP2 | ~~Adicionar AnimatedVisibility ao FAB de OutputArea~~ | LOW | ✅ FEITO | OutputArea.kt |
| CP3 | Avaliar @Stable/@Immutable se app crescer | INFO | 📋 FUTURA | model/*.kt |

---

## ✅ Phase 3: Execução de Tasks

### CP1: LaunchedEffect key corrigida ✅

**Arquivo:** `ui/components/InteractionCard.kt`

**Antes:**
```kotlin
LaunchedEffect(interaction != null) {
    if (interaction != null) { ... }
}
```

**Depois:**
```kotlin
// Key é o objeto completo — segunda interaction também dispara re-focus
LaunchedEffect(interaction) {
    if (interaction != null) { ... }
}
```

### CP2: AnimatedVisibility no FAB ✅

**Arquivo:** `ui/components/OutputArea.kt`

**Antes:**
```kotlin
if (!autoScrollEnabled) {
    FloatingActionButton(
        modifier = Modifier.align(Alignment.BottomEnd).padding(8.dp).size(40.dp),
        ...
    )
}
```

**Depois:**
```kotlin
AnimatedVisibility(
    visible  = !autoScrollEnabled,
    enter    = fadeIn(tween(200)),
    exit     = fadeOut(tween(150)),
    modifier = Modifier.align(Alignment.BottomEnd),
) {
    FloatingActionButton(
        modifier = Modifier.padding(8.dp).size(40.dp),
        ...
    )
}
```

Imports adicionados: `AnimatedVisibility`, `fadeIn`, `fadeOut` (duplicatas removidas).

---

## Checklist Compose

### State Management
- [x] `remember` para objetos que não precisam sobreviver a configuration change (SnackbarHostState, FocusRequester, coroutineScope)
- [x] State hoisting: todos os composables recebem estado do ViewModel
- [x] `derivedStateOf { }` para computação derivada (isAtBottom em OutputArea)

### Recomposition
- [x] Keys em LazyColumn (`itemsIndexed` com `key = { _, item -> item.index }`)
- [x] Animações com `label` para Compose Layout Inspector
- [x] `collectAsStateWithLifecycle()` (não `collectAsState()` direto)

### Side Effects
- [x] `LaunchedEffect(Unit)` para efeitos únicos (coleta de errorEvent, feedbackEvents)
- [x] `LaunchedEffect(connectionStatus)` para reação a mudanças de estado
- [x] `LaunchedEffect(interaction)` (corrigido de `interaction != null`)
- [x] `LaunchedEffect(isAtBottom)` e `LaunchedEffect(listState.isScrollInProgress)` com keys corretas

### Performance
- [x] `AnimatedVisibility` para FAB (corrigido de `if()` puro)
- [x] `AnimatedContent` para transições de estado em WorkflowScreen e OutputArea
- [x] Sem allocations desnecessárias em recomposition (cores via AppColors/MaterialTheme)
- [x] `remember` para `reconnectingHolder` evita recriação em recomposição

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| LaunchedEffect key incorreto | 1 | 1 | 0 |
| Ausência de AnimatedVisibility | 1 | 1 | 0 |
| Estabilidade (@Stable/@Immutable) | 1 | 0 | 1 (futura) |
| Animação desnecessária | 1 | 0 | 0 (aceitável) |
| **Total** | **4** | **2** | **1** |

---

**Gerado por `/android:compose`**
**SystemForge — Documentation First Development**
