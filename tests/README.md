# Testes — Workflow App

## Python (pytest)

### Executar todos os testes

```bash
cd ai-forge/workflow-app
.venv/bin/python -m pytest tests/ -v
```

### Testes por módulo

| Arquivo | Cobertura |
|---------|-----------|
| `test_protocol_contract.py` | Contrato do protocolo JSON — todos os 10 tipos de mensagem, rejeição de payloads inválidos |
| `test_enum_compatibility.py` | Enums do protocolo, UUID v4, forward compatibility, timestamps |
| `workflow_app/remote/test_protocol.py` | WsEnvelope básico, whitelists |
| `remote/test_message_serializer.py` | Serialização de mensagens |
| `remote/test_remote_server.py` | Servidor WebSocket |

---

## Android (JUnit / Kotlin)

### Executar via Android Studio

1. Abrir o projeto em Android Studio: `File → Open → selecionar `ai-forge/workflow-app/android/`
2. Aguardar Gradle sync
3. Abrir `Run → Edit Configurations → JUnit`
4. Ou clicar no ícone ▶ ao lado de qualquer classe de teste

### Executar via terminal (Gradle)

```bash
cd ai-forge/workflow-app/android
./gradlew test                       # todos os unit tests
./gradlew testDebugUnitTest          # unit tests (debug build)
./gradlew connectedAndroidTest       # testes instrumentados (dispositivo necessário)
```

### Testes de contrato (module-11)

| Arquivo | Cobertura |
|---------|-----------|
| `ProtocolContractTest.kt` | Parsing dos 10 tipos, forward compat, rejeição de JSON inválido |
| `EnumCompatibilityTest.kt` | WsMessageType, ControlAction, ResponseType, PipelineViewState, UUID v4 |
| `connection/MessageParserTest.kt` | parseMessage(), deduplicação, whitelist |

---

## Compilação e Instalação do APK

### Pré-requisitos

- Android Studio Hedgehog 2023.1.1 ou superior
- JDK 17+ — verificar: `java -version`
- Android SDK API 34+ instalado via SDK Manager
- ADB disponível no PATH

### APK Debug (desenvolvimento rápido)

```bash
cd ai-forge/workflow-app/android

# Build via Gradle
./gradlew assembleDebug

# APK gerado em:
# app/build/outputs/apk/debug/app-debug.apk

# Instalar no dispositivo/emulador conectado
adb install -r app/build/outputs/apk/debug/app-debug.apk

# Abrir o app
adb shell am start -n com.workflowapp.remote/.MainActivity
```

### APK Release (assinado)

1. Abrir em Android Studio: `Build → Generate Signed Bundle/APK → APK`
2. Criar keystore se necessário: escolher caminho, senha e alias
3. Selecionar variant `release`, clicar `Finish`
4. APK gerado em: `app/build/outputs/apk/release/app-release.apk`

```bash
# Verificar dispositivo conectado
adb devices

# Instalar APK release
adb install -r app/build/outputs/apk/release/app-release.apk
```

### Verificar conexão com o servidor PC

```bash
# Verificar logs em tempo real
adb logcat -s WorkflowApp:V RemoteLogger:V

# Verificar IP do dispositivo na rede
adb shell ip route
```

---

## Protocolo — Notas de compatibilidade cross-platform

| Aspecto | Python | Kotlin |
|---------|--------|--------|
| `MessageType` | 10 valores (enum) | `WsMessageType` — 15 valores (10 core + 5 internos) |
| `ControlAction` | 3 valores (play/pause/skip) | 4 valores (+ RESUME) |
| `CommandStatus` | 6 valores (enum) | Strings — sem enum dedicado |
| `PipelineStatus` | 8 valores (enum) | `PipelineViewState` — 8 valores |
| `ResponseType` | 4 valores | 4 valores ✓ |
| Timestamp | ISO 8601 com `+00:00` | ISO 8601 com `Z` — mesmo UTC |
| UUID | `uuid.uuid4()` | `UUID.randomUUID()` — ambos SecureRandom |
| Payload extra | `from_dict()` ignora | `ignoreUnknownKeys = true` |
