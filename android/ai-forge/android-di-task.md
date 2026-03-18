# Android Dependency Injection — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | OkHttp WebSocket

---

## 📋 Contexto

App single-screen WebSocket client. **Sem framework de DI instalado** — decisão de
design deliberada. Auditoria confirma que a abordagem atual é correta e documentada.

---

## ✅ Phase 1: Code Review — Resultados

### Setup de DI

| Item | Status |
|------|--------|
| Hilt / Dagger na `build.gradle.kts` | ❌ Não instalado |
| `@HiltAndroidApp` em WorkflowApplication | ❌ Não presente |
| `@AndroidEntryPoint` em MainActivity | ❌ Não presente |
| `@HiltViewModel` em PipelineViewModel | ❌ Não presente |
| Módulo `di/` | ❌ Não existe |
| `@Inject` constructor em qualquer classe | ❌ Não presente |

### Abordagem Atual: Manual Factory via CreationExtras

```kotlin
// PipelineViewModel.kt
val Factory: ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(
        modelClass: Class<T>,
        extras: CreationExtras,
    ): T {
        val app = extras[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]!!
        val savedStateHandle = extras.createSavedStateHandle()
        return PipelineViewModel(app, savedStateHandle) as T
    }
}

// MainActivity.kt
setContent {
    WorkflowAppTheme {
        WorkflowScreen(viewModel = viewModel(factory = PipelineViewModel.Factory))
    }
}
```

Esta é a **API oficial do Lifecycle 2.5+** para criação de ViewModels com parâmetros
customizados. O `SavedStateHandle` é injetado pela plataforma automaticamente via
`extras.createSavedStateHandle()`.

---

### Análise: Por que Hilt NÃO é necessário aqui

| Critério | Este app | App que precisa de Hilt |
|----------|----------|------------------------|
| ViewModels | 1 | 5+ |
| Telas | 1 | 5+ |
| Repositórios/UseCases | 0 | 5+ |
| Módulos de feature | 0 | 2+ |
| Overhead de adicionar Hilt | kapt/KSP + 5 arquivos + anotações | Justificado pelo escopo |

**Custo de adicionar Hilt:**
- Plugin `hilt-android-gradle-plugin` + `kapt` / `ksp`
- `@HiltAndroidApp` em Application
- `@AndroidEntryPoint` em MainActivity
- `@HiltViewModel` + `@Inject constructor` em PipelineViewModel
- `AppModule.kt` para prefs + connectionManager + wsClient
- Build time significativamente maior (kapt)

**Benefício:** zero — não há múltiplos consumidores das mesmas dependências.

---

### Construção de Dependências no ViewModel

```kotlin
class PipelineViewModel(app: Application, savedStateHandle: SavedStateHandle) {
    // Construção direta — correto para single-screen app
    private val prefs = app.getSharedPreferences("remote_settings", MODE_PRIVATE)
    internal val connectionPreferences = ConnectionPreferences(app)
    internal val parser = MessageParser()
    internal val networkMonitor = NetworkMonitor(app)
    internal val wsClient = WebSocketClient(parser, onMessage, onScheduleReconnect)
    internal val connectionManager = ConnectionManager(wsClient, viewModelScope, prefs, ...)
    internal val outboundChannel = Channel<String>(Channel.BUFFERED)
}
```

Campos `internal` permitem acesso direto em testes unitários sem necessidade de mocks
injetados via DI framework.

**Único issue conhecido:** `prefs = app.getSharedPreferences("remote_settings", MODE_PRIVATE)`
cria uma instância de plain `SharedPreferences` no ViewModel — já documentado como T3 em
`android-data-layer-task.md` e A3 em `android-architecture-task.md`.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Observação |
|---|------|-----------|--------|-----------|
| DI1 | Manter abordagem de factory manual | — | ✅ CORRETO | Não mudar sem crescimento do app |
| DI2 | Consolidar SharedPreferences → ConnectionPreferences | MEDIUM | 📋 PENDENTE | Vide T3/A3 em outras task files |
| DI3 | Avaliar adição de Hilt se app crescer | INFO | 📋 FUTURA | Trigger: +3 ViewModels ou +2 telas |

---

## ✅ Phase 3: Execução de Tasks

### Nenhuma tarefa executável nesta auditoria

O app não usa DI framework e **não precisa usar** dado o seu escopo atual.
A factory manual via `CreationExtras` está corretamente implementada e é a abordagem
recomendada pela Android Architecture Guide para apps de pequeno porte.

---

## Roadmap: Migração para Hilt (se app crescer)

Se o app ganhar novas telas ou features, seguir esta ordem:

### Passo 1: Adicionar dependências
```kotlin
// build.gradle.kts (projeto)
plugins {
    id("com.google.dagger.hilt.android") version "2.51" apply false
}

// app/build.gradle.kts
plugins {
    id("com.google.dagger.hilt.android")
    id("com.google.devtools.ksp") // ou id("kotlin-kapt")
}

dependencies {
    implementation("com.google.dagger:hilt-android:2.51")
    ksp("com.google.dagger:hilt-compiler:2.51")
}
```

### Passo 2: Anotar Application
```kotlin
@HiltAndroidApp
class WorkflowApplication : Application() { ... }
```

### Passo 3: Anotar MainActivity
```kotlin
@AndroidEntryPoint
class MainActivity : ComponentActivity() { ... }
```

### Passo 4: Migrar ViewModel
```kotlin
@HiltViewModel
class PipelineViewModel @Inject constructor(
    @ApplicationContext private val app: Application,
    savedStateHandle: SavedStateHandle,
    private val connectionPreferences: ConnectionPreferences,
    private val wsClient: WebSocketClient,
    private val connectionManager: ConnectionManager,
) : AndroidViewModel(app) { ... }
```

### Passo 5: Criar AppModule
```kotlin
@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides @Singleton
    fun provideConnectionPreferences(@ApplicationContext ctx: Context) =
        ConnectionPreferences(ctx)

    @Provides @Singleton
    fun provideMessageParser() = MessageParser()

    @Provides @Singleton
    fun provideNetworkMonitor(@ApplicationContext ctx: Context) =
        NetworkMonitor(ctx)
}
```

### Passo 6: Atualizar testes
```kotlin
// Substituir acesso por `internal` por injeção de fakes
@HiltAndroidTest
@UninstallModules(AppModule::class)
class PipelineViewModelTest { ... }
```

---

## Checklist DI

### Setup
- [x] Sem Hilt — decisão correta para escopo atual
- [x] Factory manual via `CreationExtras` API (Lifecycle 2.5+)
- [x] `SavedStateHandle` injetado pela plataforma via `extras.createSavedStateHandle()`
- [x] Campos `internal` permitem testes sem DI framework

### Módulos
- [x] Não aplicável — sem DI framework

### Qualifiers
- [x] Não aplicável — sem DI framework

### Testing
- [x] Testes unitários acessam campos `internal` diretamente
- [x] `@VisibleForTesting` documenta a intenção

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Setup Hilt | N/A — não instalado | N/A | N/A |
| Entry points | N/A | N/A | N/A |
| Manual factory | 1 (correto) | 0 (não mudar) | 0 |
| SharedPreferences no ViewModel | 1 | 0 | 1 (ver data-layer T3) |

---

**Gerado por `/android:di`**
**SystemForge — Documentation First Development**
