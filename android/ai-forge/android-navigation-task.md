# Android Navigation — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket

---

## 📋 Contexto

App single-screen WebSocket client. **Sem Navigation Component instalado** — decisão de
design deliberada. Auditoria confirma que a abordagem atual é correta e documentada.

---

## ✅ Phase 1: Code Review — Resultados

### Setup de Navigation

| Item | Status |
|------|--------|
| Navigation Compose na `build.gradle.kts` | ❌ Não instalado |
| `NavHost` / `NavController` | ❌ Não presente |
| Routes (sealed class / string) | ❌ Não aplicável |
| Deep links (`navDeepLink`, intent-filter BROWSABLE) | ❌ Não configurado |
| `navArgument` | ❌ Não aplicável |
| Navegação aninhada | ❌ Não aplicável |

### Abordagem Atual: Direct Composition

```kotlin
// MainActivity.kt
setContent {
    WorkflowAppTheme {
        WorkflowScreen(viewModel = viewModel(factory = PipelineViewModel.Factory))
    }
}
```

`MainActivity` instancia diretamente `WorkflowScreen` — a única tela do app.
Não há back stack, não há troca de destinos.

### Flag de Segurança

```kotlin
// MainActivity.kt — aplicado globalmente antes do setContent
window.setFlags(
    WindowManager.LayoutParams.FLAG_SECURE,
    WindowManager.LayoutParams.FLAG_SECURE,
)
```

`FLAG_SECURE` impede captura de tela e ocultação de thumbnail em Recent Apps.
Em um app com múltiplas telas isso precisaria ser configurado por tela — aqui,
aplicado globalmente na única Activity, cobre 100% do app.

---

### Análise: Por que Navigation Component NÃO é necessário aqui

| Critério | Este app | App que precisa de Navigation |
|----------|----------|-------------------------------|
| Telas | 1 | 3+ |
| Fluxos com back stack | 0 | Sim |
| Deep links | Nenhum | Notificações, links externos |
| Argumentos entre telas | N/A | Sim |
| Bottom Navigation | Não | Comum |
| `FLAG_SECURE` por tela | N/A | Necessário |

**Custo de adicionar Navigation Compose sem necessidade:**
- Dependência `androidx.navigation:navigation-compose`
- `NavHost` + `NavController` + routes boilerplate
- Passagem de lambdas de navegação para cada composable
- `SavedStateHandle` para argumentos que hoje são passados diretamente
- Build time maior sem benefício funcional

**Benefício:** zero — há apenas uma tela, sem destinos alternativos.

### Navegação Interna (Compose state-driven)

O app usa **navegação por estado** em vez de Navigation Component para transições
entre "modos" da única tela:

```kotlin
// WorkflowScreen.kt — transições por AnimatedContent/AnimatedVisibility
AnimatedContent(
    targetState = commandQueue.isEmpty() && connectionStatus == CONNECTED,
) { isIdle ->
    if (isIdle) IdleState(lastPipeline)
    else CommandQueueList(commands, ...)
}

AnimatedVisibility(visible = pendingInteraction != null) {
    InteractionCard(interaction, ...)
}
```

Esta é a abordagem correta para sub-estados dentro de uma única tela.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Observação |
|---|------|-----------|--------|-----------:|
| NAV1 | Manter sem Navigation Component | — | ✅ CORRETO | Não mudar sem crescimento do app |
| NAV2 | Avaliar Navigation Compose se app crescer | INFO | 📋 FUTURA | Trigger: +2 telas distintas |
| NAV3 | Deep link para conectar via QR/URL | INFO | 📋 FUTURA | Ex: `workflowapp://connect?ip=x&port=y` |

---

## ✅ Phase 3: Execução de Tasks

### Nenhuma tarefa executável nesta auditoria

O app não usa Navigation Component e **não precisa usar** dado o seu escopo atual.
A composição direta via `setContent { WorkflowScreen() }` é a abordagem correta
para um app single-screen.

---

## Roadmap: Migração para Navigation Compose (se app crescer)

Se o app ganhar novas telas (ex: configurações, histórico, scanner QR), seguir esta ordem:

### Passo 1: Adicionar dependência

```kotlin
// app/build.gradle.kts
dependencies {
    implementation("androidx.navigation:navigation-compose:2.8.x")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.x")
}
```

### Passo 2: Definir routes type-safe (Navigation 2.8+ / Kotlin Serialization)

```kotlin
// navigation/Routes.kt
@Serializable sealed class Route {
    @Serializable data object Main    : Route()
    @Serializable data object Settings : Route()
    @Serializable data class Connect(val ip: String, val port: Int) : Route()
}
```

### Passo 3: Migrar MainActivity

```kotlin
setContent {
    WorkflowAppTheme {
        val navController = rememberNavController()
        NavHost(navController, startDestination = Route.Main) {
            composable<Route.Main> {
                WorkflowScreen(
                    viewModel = viewModel(factory = PipelineViewModel.Factory),
                    onNavigateToSettings = { navController.navigate(Route.Settings) }
                )
            }
            composable<Route.Settings> { SettingsScreen() }
        }
    }
}
```

### Passo 4: Deep link para conexão via QR

```kotlin
// AndroidManifest.xml
<intent-filter android:autoVerify="false">
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="workflowapp" android:host="connect" />
</intent-filter>

// NavHost
composable<Route.Connect>(
    deepLinks = listOf(navDeepLink<Route.Connect>(
        basePath = "workflowapp://connect"
    ))
) { backStackEntry ->
    val route: Route.Connect = backStackEntry.toRoute()
    // Auto-preenche IP e porta
}
```

### Passo 5: Manter FLAG_SECURE

```kotlin
// Com Navigation: aplicar por tela ou globalmente na Activity
// Como há apenas uma Activity, a configuração atual já cobre todas as telas futuras
```

---

## Checklist Navigation

### Setup
- [x] Sem Navigation Component — decisão correta para escopo atual
- [x] Composição direta: `setContent { WorkflowScreen() }`
- [x] `FLAG_SECURE` aplicado globalmente na única Activity

### Navegação interna (state-driven)
- [x] `AnimatedContent` para transição CommandQueue ↔ IdleState
- [x] `AnimatedVisibility` para InteractionCard
- [x] `collectAsStateWithLifecycle` para estados de navegação

### Routes
- [x] Não aplicável — sem destinos

### Deep Links
- [x] Não configurado — sem requisito atual
- [ ] Deep link QR (`workflowapp://connect?ip=&port=`) — futura

### Back Stack
- [x] Não aplicável — single-screen

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Setup Navigation | N/A — não instalado | N/A | N/A |
| Routes | N/A | N/A | N/A |
| Deep links | 0 (nenhum requerido) | 0 | 0 |
| State-driven nav (AnimatedContent/Visibility) | 2 (corretos) | 0 | 0 |

---

**Gerado por `/android:navigation`**
**SystemForge — Documentation First Development**
