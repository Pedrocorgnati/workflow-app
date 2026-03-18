# Lifecycle Task List — workflow-app Android

**Gerado por:** `/android:lifecycle`
**Data:** 2026-03-16
**Repo:** `ai-forge/workflow-app/android/`

---

## Resumo da Análise

| Categoria | Status | Observação |
|-----------|--------|-----------|
| StateFlow everywhere | ✅ OK | 44 StateFlow, 0 LiveData |
| collectAsStateWithLifecycle | ✅ OK | Todos os 12 flows em WorkflowScreen |
| DefaultLifecycleObserver | ✅ OK | ConnectionManager via ProcessLifecycleOwner |
| onCleared() cleanup | ✅ OK | WebSocket + Channel + ConnectionManager |
| State machine guard | ✅ OK | canTransitionTo() em todas as transições |
| SharedPreferences persistence | ✅ OK | Sobrevive process death |
| Duplicate wsClient.state.collect | ⚠️ MÉDIO | Dois coroutines coletando o mesmo StateFlow |
| SavedStateHandle | ⚠️ BAIXO | IP/port não salvo se usuário digitar sem conectar |

---

## TASK-1: Consolidar coletores duplicados de wsClient.state [MÉDIO]

**Arquivo:** `app/src/main/java/com/workflowapp/remote/viewmodel/PipelineViewModel.kt`

**Problema:** Dois `viewModelScope.launch` no `init {}` coletam o mesmo `wsClient.state: StateFlow<ConnectionStatus>`:
- Linhas 188–192: chama `transitionConnectionStatus(status)`
- Linhas 205–214: chama `connectionManager.resetBackoff()` + `connectionPreferences.save()` quando `CONNECTED`

Dois coletores no mesmo StateFlow são redundantes — ambos recebem cada emissão, mas operam em duas goroutines separadas, criando overhead desnecessário e risco de ordering implícito (se o estado mudar entre as duas coletas).

**Fix:** Fundir em um único coletor que executa ambas as responsabilidades na mesma goroutine.

```kotlin
// ANTES (dois coletores separados)
viewModelScope.launch {
    wsClient.state.collect { status ->
        transitionConnectionStatus(status)
    }
}
// ... código no meio ...
viewModelScope.launch {
    wsClient.state.collect { status ->
        if (status == ConnectionStatus.CONNECTED) {
            connectionManager.resetBackoff()
            val ip   = _ipInput.value.trim()
            val port = _portInput.value.trim().toIntOrNull() ?: RemoteConstants.DEFAULT_PORT
            connectionPreferences.save(ip, port)
        }
    }
}

// DEPOIS (único coletor)
viewModelScope.launch {
    wsClient.state.collect { status ->
        transitionConnectionStatus(status)
        if (status == ConnectionStatus.CONNECTED) {
            connectionManager.resetBackoff()
            val ip   = _ipInput.value.trim()
            val port = _portInput.value.trim().toIntOrNull() ?: RemoteConstants.DEFAULT_PORT
            connectionPreferences.save(ip, port)
        }
    }
}
```

**Status:** [x] Concluído — merged into single collector in `init {}` (lines 200–211)

---

## TASK-2: Adicionar SavedStateHandle para IP/port não confirmados [BAIXO]

**Arquivos:**
- `app/src/main/java/com/workflowapp/remote/viewmodel/PipelineViewModel.kt`
- `app/src/main/java/com/workflowapp/remote/MainActivity.kt`

**Problema:** `_ipInput` e `_portInput` são inicializados a partir de `ConnectionPreferences` (SharedPreferences) na hora que a ViewModel é criada. Isso funciona bem quando o usuário já conectou ao menos uma vez. Porém, se o usuário digitar um novo IP mas não clicar em conectar antes do sistema matar o processo em background, o texto digitado se perde.

**Fix:** Adicionar `SavedStateHandle` como parâmetro da ViewModel para persistir o estado de formulário transiente.

### 2.1 — Constructor + SavedStateHandle

```kotlin
// ANTES
class PipelineViewModel(app: Application) : AndroidViewModel(app)

// DEPOIS
class PipelineViewModel(
    app: Application,
    private val savedStateHandle: SavedStateHandle,
) : AndroidViewModel(app)
```

### 2.2 — Init: usar savedStateHandle com fallback

```kotlin
// DEPOIS — no init block, substituir lógica de restauração:
// 1. SavedStateHandle tem prioridade (estado transiente de formulário)
val savedIp   = savedStateHandle.get<String>("ip_input")
val savedPort = savedStateHandle.get<String>("port_input")

if (savedIp != null) {
    _ipInput.value   = savedIp
    _portInput.value = savedPort ?: RemoteConstants.DEFAULT_PORT.toString()
} else {
    // Fallback: ConnectionPreferences (última conexão bem-sucedida)
    val lastIp   = connectionPreferences.loadIp()
    val lastPort = connectionPreferences.loadPort()
    if (lastIp.isNotEmpty()) {
        _ipInput.value   = lastIp
        _portInput.value = lastPort.toString()
    } else {
        val (savedHost, savedPortInt) = connectionManager.loadSettings()
        if (savedHost.isNotEmpty()) {
            _ipInput.value   = savedHost
            _portInput.value = savedPortInt.toString()
        }
    }
}
```

### 2.3 — updateIp/updatePort: persistir no savedStateHandle

```kotlin
fun updateIp(ip: String) {
    _ipInput.value = ip
    savedStateHandle["ip_input"] = ip   // persistir
    _ipValidationError.value = when {
        ip.isBlank()   -> null
        !isValidIp(ip) -> "Endereço IP inválido"
        else           -> null
    }
}

fun updatePort(port: String) {
    _portInput.value = port
    savedStateHandle["port_input"] = port   // persistir
    val portInt = port.toIntOrNull()
    _portValidationError.value = when {
        port.isBlank()      -> null
        portInt == null     -> "Porta deve ser um número"
        !isValidPort(portInt) -> "Porta fora do intervalo (1024–65535)"
        else                -> null
    }
}
```

### 2.4 — Factory: usar CreationExtras (API moderna Lifecycle 2.5+)

```kotlin
// Remover a classe Factory interna (ViewModelProvider.Factory)
// Substituir por:
companion object {
    val Factory: ViewModelProvider.Factory = object : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T {
            val app = extras[APPLICATION_KEY]!!
            val savedStateHandle = extras.createSavedStateHandle()
            @Suppress("UNCHECKED_CAST")
            return PipelineViewModel(app, savedStateHandle) as T
        }
    }
}
```

### 2.5 — MainActivity: passar a factory

```kotlin
// ANTES
WorkflowScreen(viewModel = viewModel())

// DEPOIS
WorkflowScreen(
    viewModel = viewModel(factory = PipelineViewModel.Factory)
)
```

**Status:** [x] Concluído — `SavedStateHandle` adicionado ao construtor + `CreationExtras` Factory + `MainActivity` atualizada

---

## Checklist de Validação

- [ ] `./gradlew assembleDebug` — build sem erros (requer Android SDK — não disponível nesta máquina)
- [ ] `./gradlew test` — testes unitários passando (requer Android SDK — não disponível nesta máquina)
- [x] Nenhum `LiveData` introduzido
- [x] `collectAsStateWithLifecycle` preservado em `WorkflowScreen`
- [x] `onCleared()` sem alterações
