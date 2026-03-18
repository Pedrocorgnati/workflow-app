# Android Performance Testing Guide — module-12/TASK-3

**Data:** 2026-03-15
**Módulo:** module-12-integration

---

## Performance Budgets (INT-020, INT-042, INT-060)

| Métrica | Budget | Componente |
|---------|--------|------------|
| Latência output end-to-end | < 500ms (target 350ms) | PC 100ms + Tailscale 50ms + Android 200ms |
| Buffer output Android | max 5000 linhas (FIFO) | OutputArea.kt |
| Tempo de reconexão | < 30s | BackoffStrategy (max 14s = 2+4+8) |
| Throttle Android render | 200ms | OutputArea LazyColumn |

---

## Python Side: 27 testes passando

```
tests/remote/test_performance_budgets.py: 27 passed ✅
- TestOutputThrottleBudget: 11 testes (PC throttle 100ms, 4KB limit)
- TestRateLimiterBudget: 4 testes (20 msg/s)
- TestHeartbeatBudget: 4 testes (30s interval, 10s timeout)
- TestBufferAndDedupBudget: 5 testes (10k dedup, bytes tracking)
- TestTimingBudgetConstants: 3 testes (budget arithmetic)
```

---

## Android: Testes de Performance (JVM)

```bash
cd android
./gradlew test --tests "*BackoffStrategyTest*"
```

### BackoffStrategyTest — Reconnection Budget

```kotlin
@Test fun `backoff sequence stays under 30s budget`() {
    val strategy = BackoffStrategy()
    val delays = (1..3).map { strategy.nextDelayMs() }
    // 2000 + 4000 + 8000 = 14000ms << 30000ms
    assertThat(delays.sum()).isLessThan(30_000)
}
```

---

## Android: Benchmark de Rendering (Instrumented)

Para testar buffer de 5000 linhas (INT-042) e throttle 200ms (INT-059):

```kotlin
// app/src/androidTest/java/.../PerformanceBudgetTest.kt
@Test fun `output buffer capped at 5000 lines`() {
    // Inject 6000 lines into PipelineViewModel
    repeat(6000) { i -> viewModel.addOutputLine("line $i") }

    // Buffer must not exceed 5000
    assertThat(viewModel.uiState.value.outputLines.size).isAtMost(5000)
    // Oldest lines discarded (FIFO)
    assertThat(viewModel.uiState.value.outputLines.first()).contains("line 1000")
}
```

---

## Limitações dos Testes de Performance

Os testes Python (`test_performance_budgets.py`) validam:
- Constantes de configuração corretas
- Comportamento de throttle (batching, flush imediato em 4KB)
- Rate limiter (20 msg/s)
- Aritmética do budget (soma não ultrapassa 500ms)

**O que NÃO é testado automaticamente:**
- Latência real de rede (requer hardware Android + Tailscale ativo)
- Rendering frame rate no Android (requer Perfetto ou Android Studio Profiler)
- Memória Android durante streaming longo (requer MAT ou Android Studio Memory Profiler)

Para latência real: usar `ping tailscale-peer` e medir RTT antes do teste E2E.
