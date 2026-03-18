# Android Security Task List

Gerado por `/android:security` em 2026-03-16.

---

## T1 — Migrar `android.util.Log` para Timber em 4 arquivos

**Arquivos:**
- `connection/WebSocketClient.kt`
- `data/ConnectionPreferences.kt`
- `model/PipelineViewState.kt`
- `viewmodel/PipelineViewModel.kt`

**Ação:** Substituir `import android.util.Log` + `Log.d/i/w/e(TAG, ...)` por `Timber.d/i/w/e(...)`.
No `ConnectionPreferences.kt` e `WebSocketClient.kt`, usar `Timber` diretamente (não há logger de camada específica).
No `PipelineViewState.kt` e `PipelineViewModel.kt`, usar `Timber`.

**Por quê:** `Timber.DebugTree` só é plantado em debug (vide `WorkflowApplication`), então logs ficam silenciosos em release automaticamente. `android.util.Log` direto vaza em release.

---

## T2 — Criar `network_security_config.xml` e referenciar no Manifest

**Arquivo novo:** `app/src/main/res/xml/network_security_config.xml`

**Conteúdo:**
- `base-config cleartextTrafficPermitted="false"` (produção: apenas HTTPS/WSS)
- `debug-overrides` com user certificates (proxy/debug)
- `domain-config cleartextTrafficPermitted="true"` para `localhost` e `10.0.2.2` (LAN/emulador)
- LAN range permitido para ws:// (conexão local ao servidor PC)

**Manifest:** adicionar `android:networkSecurityConfig="@xml/network_security_config"`.

---

## T3 — Desabilitar backup de dados sensíveis no Manifest

**Ação no Manifest:**
- `android:allowBackup="false"` (ou criar regras explícitas)
- `android:dataExtractionRules="@xml/data_extraction_rules"` (Android 12+)
- `android:fullBackupContent="@xml/backup_rules"` (Android 11-)

**Arquivo novo:** `res/xml/data_extraction_rules.xml` — excluir `connection_prefs_encrypted.xml` e `remote_settings`.
**Arquivo novo:** `res/xml/backup_rules.xml` — mesmas exclusões.

---

## T4 — Completar ProGuard rules

**Adicionar em `proguard-rules.pro`:**
- `-keepattributes SourceFile,LineNumberTable` (stack traces legíveis no Crashlytics)
- `-renamesourcefileattribute SourceFile`
- `-keepattributes *Annotation*`
- `-assumenosideeffects class android.util.Log { ... }` (remove chamadas residuais de Log)
- Keep para data classes do modelo (`com.workflowapp.remote.model.**`)
- Keep para Timber

---

## T5 — Eliminar SharedPreferences plain duplicado em PipelineViewModel

**Problema:** `PipelineViewModel` cria `prefs = app.getSharedPreferences("remote_settings", MODE_PRIVATE)`
(plain, não encriptado) e passa para `ConnectionManager.saveSettings/loadSettings`.
Ao mesmo tempo, `ConnectionPreferences` (encriptado) salva os mesmos dados pós-conexão.

**Ação:** Fazer `ConnectionManager` usar `ConnectionPreferences` (já injetado no ViewModel)
ou remover `ConnectionManager.saveSettings/loadSettings` e deixar apenas `ConnectionPreferences` como fonte de verdade.
