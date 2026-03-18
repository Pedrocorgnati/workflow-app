# Android Resilience Testing Guide — module-12/TASK-2

**Data:** 2026-03-15
**Módulo:** module-12-integration

---

## Visão Geral

Este documento descreve como testar os cenários de resiliência do Android
(reconexão, perda de rede, lifecycle e backoff).

**Python side:** `tests/remote/test_resilience.py` — 37 testes passando

---

## Testes JVM (Sem Emulador)

```bash
cd android
./gradlew test
```

### Testes de Resiliência Existentes

| Classe | Arquivo | O que testa |
|--------|---------|-------------|
| `BackoffStrategyTest` | `connection/BackoffStrategyTest.kt` | Exponencial 2s→4s→8s→16s, cap 60s, reset |
| `WebSocketClientTest` | `connection/WebSocketClientTest.kt` | Reconexão, códigos de fechamento 1000-1008 |
| `NetworkMonitorTest` | `connection/NetworkMonitorTest.kt` | ConnectivityManager + NetworkCallback |
| `LifecycleTest` | `connection/LifecycleTest.kt` | Background/foreground + onCleared() |
| `PipelineViewModelTest` | `viewmodel/PipelineViewModelTest.kt` | State machine com reconexão |

---

## Cenários de Resiliência (Manual + Emulador)

### Cenário 1: Desconexão Abrupta

**Steps:**
1. Conectar Android ao servidor PC
2. Matar processo do servidor no PC (`Ctrl+C` ou fechar app)
3. Aguardar

**Resultado esperado:**
- Badge muda para amarelo "Reconectando..."
- Backoff: 2s → 4s → 8s → 16s → 32s → 60s
- Após 3 tentativas: badge vermelho + snackbar "Não foi possível conectar"

```kotlin
// BackoffStrategyTest deve cobrir:
@Test fun `exponential delays 2 4 8 16 32 60`() {
    val strategy = BackoffStrategy()
    assertThat(strategy.nextDelayMs()).isEqualTo(2_000)
    assertThat(strategy.nextDelayMs()).isEqualTo(4_000)
    assertThat(strategy.nextDelayMs()).isEqualTo(8_000)
    assertThat(strategy.nextDelayMs()).isEqualTo(16_000)
    assertThat(strategy.nextDelayMs()).isEqualTo(32_000)
    assertThat(strategy.nextDelayMs()).isEqualTo(60_000) // cap
}

@Test fun `after 3 failures shows error and stops`() {
    val strategy = BackoffStrategy()
    for (i in 1..3) { strategy.recordFailure() }
    assertThat(strategy.shouldRetry()).isFalse()
}
```

### Cenário 2: Perda de Rede (NetworkCallback)

**Steps:**
1. Conectar normalmente
2. Ativar Modo Avião
3. Desativar Modo Avião

**Resultado esperado:**
- Modo Avião ON: badge amarelo, reconexão suspensa (sem rede)
- Modo Avião OFF: NetworkCallback detecta rede disponível → reconectar automaticamente

```kotlin
// NetworkMonitorTest deve cobrir:
@Test fun `network lost triggers state update`()
@Test fun `network available triggers reconnection attempt`()
```

### Cenário 3: Background 5 Minutos

**Steps:**
1. Conectar normalmente com pipeline ativo
2. Pressionar Home (app em background)
3. Aguardar > 5 minutos

**Resultado esperado:**
- App desconecta proativamente após 5min (antes do Doze mode)
- Ao trazer app para foreground: reconexão automática

```kotlin
// LifecycleTest deve cobrir:
@Test fun `background for 5min triggers proactive disconnect`() {
    connectionManager.onStop()
    // Advance timer 5min
    assertThat(wsClient.wasClosed).isTrue()
}

@Test fun `foreground after background triggers reconnect`() {
    connectionManager.onStop()
    connectionManager.onStart()
    assertThat(connectionManager.isReconnecting).isTrue()
}
```

### Cenário 4: Servidor Reinicia

**Steps:**
1. Conectar normalmente
2. Fechar e reabrir app PC (reiniciar servidor)
3. Aguardar reconexão

**Resultado esperado:**
- Android detecta desconexão (código 1000-1003 ou 1006)
- Inicia backoff e reconecta ao servidor disponível

### Cenário 5: Rate Limiting

**PC side:** `RATE_LIMIT_MSG_PER_S = 20`

**Android behavior se rate limit atingido:**
- Android NÃO implementa throttle de envio de controle (design intencional)
- PC rejeita mensagens além de 20/s silenciosamente
- Debounce de 1s nos controles evita envio duplicado

```kotlin
// PipelineViewModelTest deve cobrir:
@Test fun `rapid control taps debounced to 1s`() {
    viewModel.sendControl(ControlAction.PLAY)
    viewModel.sendControl(ControlAction.PLAY) // imediato — ignorado por debounce
    assertThat(sentMessages.size).isEqualTo(1)
}
```

---

## Códigos de Fechamento WebSocket

| Código | Comportamento Android |
|--------|----------------------|
| 1000 (Normal) | NÃO reconectar |
| 1001 (Going Away) | NÃO reconectar |
| 1002-1003 (Protocol/Data) | NÃO reconectar |
| 1006 (Abnormal) | Reconectar com backoff |
| 1008 (Policy Violation) | NÃO reconectar + snackbar de erro |
| Outros | Reconectar com backoff |

---

## Status Python Side

```
tests/remote/test_resilience.py: 37 passed ✅
- TestAbruptDisconnect: 7 testes
- TestHeartbeatResilience: 9 testes
- TestServerRestartCycle: 5 testes
- TestRateLimiting: 6 testes
- TestMessageDeduplication: 4 testes
- TestOversizedMessages: 3 testes
- TestIPResilienceFlow: 2 testes (+ 1 bônus)
```
