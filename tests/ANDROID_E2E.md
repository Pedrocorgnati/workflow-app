# Android E2E Testing Guide — module-12/TASK-1

**Data:** 2026-03-15
**Módulo:** module-12-integration

---

## Visão Geral

Este documento descreve como executar os testes E2E do lado Android que validam
a comunicação cross-platform com o servidor Python.

O protocolo é validado em dois níveis:
1. **Python side** (automatizado): `tests/remote/test_e2e_cross_platform.py` — 43 testes passando
2. **Android side** (manual + JVM): testes descritos abaixo

---

## Pré-requisitos

- Android Studio Ladybug (ou mais recente)
- Gradle sync concluído
- Emulador API 26+ ou dispositivo físico

---

## Testes JVM Existentes (Sem Emulador)

Execute via Android Studio → Run Tests ou linha de comando:

```bash
cd android
./gradlew test
```

### Testes de Contrato de Protocolo

| Classe | Arquivo | O que testa |
|--------|---------|-------------|
| `ProtocolContractTest` | `src/test/.../ProtocolContractTest.kt` | Wire format Python↔Android |
| `EnumCompatibilityTest` | `src/test/.../EnumCompatibilityTest.kt` | Compatibilidade de enums |
| `MessageParserTest` | `src/test/.../connection/MessageParserTest.kt` | Parsing de cada tipo de mensagem |

### Casos Críticos a Validar

#### 1. output_chunk — DIV-001 (BLOCKER)

```kotlin
// MessageParserTest deve cobrir:
@Test fun `output_chunk with text field returns empty lines`() {
    // ATENÇÃO: este é o comportamento ATUAL (bug DIV-001)
    // O Python atualmente envia {"text": "..."} em vez de {"lines": [...]}
    val json = """{"message_id":"1","type":"output_chunk","timestamp":"T","payload":{"text":"line1\nline2"}}"""
    val result = parser.parseMessage(json) as? OutputChunkMsg
    // Com o bug DIV-001, result.lines será emptyList()
    assertThat(result?.lines).isEmpty()
}

@Test fun `output_chunk with lines field parses correctly`() {
    // Este é o formato CORRETO (após fix do DIV-001)
    val json = """{"message_id":"2","type":"output_chunk","timestamp":"T","payload":{"lines":["line1","line2"]}}"""
    val result = parser.parseMessage(json) as? OutputChunkMsg
    assertThat(result?.lines).containsExactly("line1", "line2")
}
```

#### 2. output_truncated — DIV-002 (BLOCKER)

```kotlin
@Test fun `output_truncated with lines_skipped field defaults to zero`() {
    // ATENÇÃO: comportamento ATUAL (bug DIV-002)
    val json = """{"message_id":"3","type":"output_truncated","timestamp":"T","payload":{"lines_skipped":42}}"""
    val result = parser.parseMessage(json) as? OutputTruncatedMsg
    // Com o bug DIV-002, result.linesOmitted será 0 (campo ignorado)
    assertThat(result?.linesOmitted).isEqualTo(0)
}

@Test fun `output_truncated with lines_omitted field parses correctly`() {
    // Este é o formato CORRETO (após fix do DIV-002)
    val json = """{"message_id":"4","type":"output_truncated","timestamp":"T","payload":{"lines_omitted":42}}"""
    val result = parser.parseMessage(json) as? OutputTruncatedMsg
    assertThat(result?.linesOmitted).isEqualTo(42)
}
```

---

## Testes Instrumentados (Requerem Emulador)

```bash
cd android
./gradlew connectedAndroidTest
```

### WorkflowScreenTest

Testa renderização da UI com estados simulados:

```kotlin
// Cenários obrigatórios:
// - Estado IDLE: "Nenhum pipeline ativo" visível
// - Estado RUNNING: fila de comandos visível, OutputArea com output
// - Estado WAITING_INTERACTION: InteractionCard visível
// - ConectionBar: badge verde/amarelo/vermelho por estado
```

---

## Fluxo de Teste Manual com PC Ligado

### Setup

1. Instalar APK no Android:
   ```bash
   cd android && ./gradlew assembleDebug
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```

2. Iniciar servidor Python no PC:
   ```bash
   cd ai-forge/workflow-app
   python3 -m workflow_app.main
   ```

3. Ativar Tailscale em ambos os dispositivos

### Cenários a Testar Manualmente

| # | Cenário | Passos | Resultado Esperado |
|---|---------|--------|--------------------|
| E2E-01 | Primeira conexão | Digitar IP Tailscale + porta, tocar Conectar | Badge verde, pipeline sincronizado |
| E2E-02 | Pipeline em execução | Iniciar pipeline no PC | Fila de comandos atualizada em tempo real |
| E2E-03 | Output streaming | Executar comando com output longo | Área de output atualizada a cada ~200ms |
| E2E-04 | Controle Play/Pause | Pipeline pausado, tocar Play | Status muda para RUNNING |
| E2E-05 | Interação | Pipeline aguardando input, responder "yes" | Pipeline continua |
| E2E-06 | Desconexão de rede | Desligar WiFi com pipeline ativo | Badge amarelo "Reconectando..." |
| E2E-07 | Reconexão | Religar WiFi | Badge verde em < 30s |
| E2E-08 | Background 5min | App em background por 5 min | Desconexão proativa (Doze mode prevention) |
| E2E-09 | Sync ao reconectar | Reconectar após desconexão | Pipeline state reconstruído corretamente |
| E2E-10 | IP inválido | Digitar IP não-Tailscale, conectar | Erro "IP não autorizado" |

---

## Blockers Conhecidos (Pré-Fix)

| ID | Impacto | Sintoma no Android | Arquivo Python a Corrigir |
|----|---------|-------------------|--------------------------|
| DIV-001 | Área de output sempre vazia | `OutputChunkMsg.lines = []` | `output_throttle.py:95` |
| DIV-002 | Contador de truncamento sempre 0 | `OutputTruncatedMsg.linesOmitted = 0` | `output_throttle.py:102` |

**ANTES de testar E2E-03 (output streaming), os bugs DIV-001 e DIV-002 devem ser corrigidos.**

---

## Status dos Testes Python E2E

```
tests/remote/test_e2e_cross_platform.py: 43 passed ✅
- TestProtocolEnvelopeRoundTrip: 5 testes
- TestPCToAndroidFlow: 10 testes (inclui documentação de DIV-001/DIV-002)
- TestAndroidToPCFlow: 10 testes
- TestStateMachineFlow: 6 testes
- TestIPValidationFlow: 4 testes
- TestKnownDivergences: 4 testes (documentam bugs DIV-001 e DIV-002)
- TestEnumCompatibilityFlow: 4 testes
```
