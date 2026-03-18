# Android Testing Task List — workflow-app

> Gerado por `/android:testing` em 2026-03-16
> REPO_PATH: `ai-forge/workflow-app/android`

---

## RESUMO DO ESTADO ATUAL

| Categoria | Arquivos | Estimativa de testes |
|-----------|----------|---------------------|
| Unit tests (`src/test/`) | 11 | ~130+ |
| UI tests (`src/androidTest/`) | 3 | ~25 |
| Integration tests | 0 formal | — |
| Cobertura configurada | ❌ | — |

**Stack de teste:**
- JUnit 4.13.2
- MockK 1.13.10
- Turbine 1.1.0
- Coroutines Test 1.8.1
- Compose UI Test (via BOM)
- Robolectric — ⚠️ AUSENTE nas deps mas usado em `NetworkMonitorTest`

---

## TASKS

### TASK-1 [CRÍTICO] — Adicionar Robolectric às dependências

**Problema:** `NetworkMonitorTest.kt` usa `@RunWith(RobolectricTestRunner::class)` e
imports `org.robolectric.*`, mas Robolectric **não está declarado** em
`libs.versions.toml` nem em `build.gradle.kts`. O teste não compila.

**Arquivos a modificar:**
- `android/gradle/libs.versions.toml`
- `android/app/build.gradle.kts`

**Mudanças necessárias:**

Em `libs.versions.toml`, adicionar:
```toml
[versions]
robolectric = "4.13"

[libraries]
robolectric = { group = "org.robolectric", name = "robolectric", version.ref = "robolectric" }
```

Em `build.gradle.kts`, adicionar na seção `dependencies`:
```kotlin
testImplementation(libs.robolectric)
```

E na seção `android { testOptions { unitTests { ... } } }`:
```kotlin
testOptions {
    unitTests {
        isReturnDefaultValues = true
        isIncludeAndroidResources = true  // necessário para Robolectric
    }
}
```

**Validação:** `./gradlew :app:testDevDebugUnitTest --tests "*.NetworkMonitorTest"`

---

### TASK-2 [ALTO] — Corrigir artefato mockk para unit tests

**Problema:** `libs.versions.toml` mapeia `mockk` para `io.mockk:mockk-android`.
Para testes JVM (`testImplementation`), o artefato correto é `io.mockk:mockk`
(sem sufixo `-android`). O `-android` é para `androidTestImplementation`.

**Arquivo a modificar:** `android/gradle/libs.versions.toml`

**Mudança:**
```toml
# ANTES:
mockk = { group = "io.mockk", name = "mockk-android", version.ref = "mockk" }

# DEPOIS:
mockk = { group = "io.mockk", name = "mockk", version.ref = "mockk" }
mockk-android = { group = "io.mockk", name = "mockk-android", version.ref = "mockk" }
```

Em `build.gradle.kts`, separar os usos:
```kotlin
// Unit tests (JVM)
testImplementation(libs.mockk)
testImplementation(libs.mockk.agent)

// Android instrumented tests
androidTestImplementation(libs.mockk.android)
```

**Validação:** `./gradlew :app:testDevDebugUnitTest`

---

### TASK-3 [MÉDIO] — Configurar Kover para cobertura de código

**Problema:** Nenhuma ferramenta de cobertura configurada. Impossível medir
cobertura atual nem definir targets de CI.

**Arquivo a modificar:** `android/app/build.gradle.kts`
**Arquivo a modificar:** `android/build.gradle.kts` (root)

**Mudanças no root `build.gradle.kts`:**
```kotlin
plugins {
    alias(libs.plugins.kover) apply false
}
```

**Mudanças no `app/build.gradle.kts`:**
```kotlin
plugins {
    // adicionar:
    alias(libs.plugins.kover)
}

kover {
    reports {
        filters {
            excludes {
                classes(
                    "*.BuildConfig",
                    "*_HiltComponents*",
                    "*Hilt_*",
                )
            }
        }
        verify {
            rule {
                minBound(60)  // 60% mínimo inicial
            }
        }
    }
}
```

Em `libs.versions.toml`:
```toml
[versions]
kover = "0.8.3"

[plugins]
kover = { id = "org.jetbrains.kotlinx.kover", version.ref = "kover" }
```

**Validação:** `./gradlew koverHtmlReportDevDebug`

---

### TASK-4 [BAIXO] — Expandir WorkflowScreenTest após integração do ViewModel

**Contexto:** `WorkflowScreenTest.kt` tem TODO explícito:
> "TODO: Expand after /auto-flow execute populates ViewModel with real logic."

**Ação:** Quando ViewModel estiver completo, adicionar testes para:
- Estado CONNECTING (spinner/feedback)
- Estado CONNECTED (ConnectionBar mostra IP/porta)
- Estado RECONNECTING (badge amarelo)
- Teste de interação: digitar IP + porta + tap Conectar → ConnectionStatus muda

**Arquivo:** `android/app/src/androidTest/java/com/workflowapp/remote/ui/WorkflowScreenTest.kt`

**Validação:** `./gradlew :app:connectedDevDebugAndroidTest --tests "*.WorkflowScreenTest"`

---

### TASK-5 [BAIXO] — Adicionar teste de integração para ConnectionPreferences (EncryptedSharedPreferences)

**Contexto:** `ConnectionPreferencesTest` cobre apenas helpers pure-Kotlin.
O fluxo de save/load com EncryptedSharedPreferences não tem cobertura.

**Criar:** `android/app/src/androidTest/java/com/workflowapp/remote/data/ConnectionPreferencesIntegrationTest.kt`

```kotlin
@RunWith(AndroidJUnit4::class)
class ConnectionPreferencesIntegrationTest {

    private lateinit var prefs: ConnectionPreferences

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        prefs = ConnectionPreferences(context)
        prefs.clear()
    }

    @Test
    fun saveAndLoadIp_roundtrip() {
        prefs.saveIp("192.168.1.100")
        assertEquals("192.168.1.100", prefs.loadIp())
    }

    @Test
    fun saveAndLoadPort_roundtrip() {
        prefs.savePort(18765)
        assertEquals(18765, prefs.loadPort())
    }

    @Test
    fun defaults_whenNotSet() {
        assertNull(prefs.loadIp())
        assertEquals(18765, prefs.loadPort())
    }
}
```

**Validação:** `./gradlew :app:connectedDevDebugAndroidTest --tests "*.ConnectionPreferencesIntegrationTest"`

---

## CHECKLIST DE EXECUÇÃO

### Unit Tests
- [x] ViewModel tests (PipelineViewModelTest — 17 testes)
- [x] WebSocketClient tests (8 testes)
- [x] BackoffStrategy tests (7 testes)
- [x] MessageParser tests (12 testes)
- [ ] NetworkMonitorTest — **BLOQUEADO por Robolectric ausente (TASK-1)**
- [x] LifecycleTest (5 testes)
- [x] ProtocolContractTest (~15 testes)
- [x] EnumCompatibilityTest (~10 testes)
- [x] ConnectionPreferencesTest (12 testes)
- [x] StateMachineTest (22 testes)
- [x] FeedbackSnackbarTest (10 testes)

### UI Tests
- [x] WorkflowScreenTest (2 testes mínimos, TODO pendente)
- [x] ComponentTests (11 testes)
- [x] AccessibilityTest (11 testes)

### Integration
- [ ] Hilt testing — N/A (projeto não usa Hilt)
- [ ] Room testing — N/A (projeto não usa Room)
- [ ] ConnectionPreferences integration — **TASK-5**

### Coverage
- [ ] Kover configurado — **TASK-3**
- [ ] CI/CD integration — pendente TASK-3

---

## PRIORIDADE DE EXECUÇÃO

1. **TASK-1** (Robolectric) — bloqueante para compilação
2. **TASK-2** (mockk artefato) — pode causar erros de runtime em unit tests
3. **TASK-3** (Kover) — habilitador de métricas
4. **TASK-4** e **TASK-5** — melhorias incrementais
