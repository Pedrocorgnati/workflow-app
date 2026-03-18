# Android Configuration — Task List

Gerado em: 2026-03-16
Repo: `ai-forge/workflow-app/android`

---

### T001 - Atualizar versões desatualizadas no Version Catalog

**Tipo:** SEQUENTIAL
**Arquivos:**
- modificar: `gradle/libs.versions.toml`
- modificar: `app/build.gradle.kts`

**Descricao:**
- `composeBom` → `2024.09.03` (latest LTS com AGP 8.5)
- `compileSdk` e `targetSdk` → `35`
- Corrigir `androidx-lifecycle-viewmodel-compose` para usar versão própria (`lifecycleViewmodelCompose`)

**Criterios de Aceite:**
- [ ] composeBom atualizado para 2024.09.03
- [ ] compileSdk/targetSdk = 35
- [ ] lifecycleViewmodelCompose tem version.ref próprio
- [ ] Build assembleDebug sem erros

---

### T002 - Substituir security-crypto alpha por versão estável

**Tipo:** SEQUENTIAL
**Arquivos:**
- modificar: `gradle/libs.versions.toml`

**Descricao:**
`securityCrypto = "1.1.0-alpha06"` é uma versão alpha usada em produção.
Substituir por `1.0.0` (estável) ou `1.1.0-alpha06` anotar como tech debt se a API alpha for necessária.
Verificar se a API usada no código existe na versão estável.

**Criterios de Aceite:**
- [ ] securityCrypto não usa versão alpha em produção
- [ ] EncryptedSharedPreferences ainda funciona no build

---

### T003 - Adicionar packaging excludes no app/build.gradle.kts

**Tipo:** PARALLEL-GROUP-1
**Arquivos:**
- modificar: `app/build.gradle.kts`

**Descricao:**
Adicionar bloco `packaging` para evitar conflitos de metadados com OkHttp/Kotlin:

```kotlin
packaging {
    resources {
        excludes += "/META-INF/{AL2.0,LGPL2.1}"
        excludes += "/META-INF/DEPENDENCIES"
    }
}
```

**Criterios de Aceite:**
- [ ] packaging block presente em android {}
- [ ] Build release sem DuplicateFilesException

---

### T004 - Adicionar signingConfig para release via keystore.properties

**Tipo:** PARALLEL-GROUP-1
**Arquivos:**
- modificar: `app/build.gradle.kts`
- criar: `keystore.properties.template`

**Descricao:**
Release build sem signingConfig fará o build falhar ao gerar APK assinado.
Implementar leitura de `keystore.properties` (não commitado) para assinar release.
Criar `keystore.properties.template` como referência para desenvolvedores.

**Criterios de Aceite:**
- [ ] signingConfig lê de keystore.properties quando arquivo existe
- [ ] keystore.properties em .gitignore
- [ ] keystore.properties.template commitado como referência
- [ ] Build release não falha por falta de signing

---

### T005 - Adicionar ProGuard rules para androidx.security.crypto

**Tipo:** PARALLEL-GROUP-1
**Arquivos:**
- modificar: `app/proguard-rules.pro`

**Descricao:**
EncryptedSharedPreferences pode ser ofuscado incorretamente pelo R8 sem regras explícitas.
Adicionar keep rules para `androidx.security.crypto`.

**Criterios de Aceite:**
- [ ] Rules para security-crypto presentes
- [ ] Build release com minify não quebra EncryptedSharedPreferences

---

### T006 - Adicionar tools:targetApi no AndroidManifest.xml

**Tipo:** PARALLEL-GROUP-1
**Arquivos:**
- modificar: `app/src/main/AndroidManifest.xml`

**Descricao:**
Adicionar `tools:targetApi="31"` e `xmlns:tools` no tag `<application>` para suprimir lint warning
sobre atributos introduzidos em API 31+ (ex: `android:exported`).

**Criterios de Aceite:**
- [ ] tools namespace declarado no manifest
- [ ] tools:targetApi="31" presente em <application>
- [ ] ./gradlew lint sem warning sobre targetApi
