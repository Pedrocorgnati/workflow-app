# Android Scalability — Task List
**Projeto:** WorkflowApp Android (Remote Client)
**Repo:** `ai-forge/workflow-app/android`
**Data:** 2026-03-16

---

## Contexto

App cliente WebSocket (Kotlin/Jetpack Compose) que controla o servidor PySide6 via
conexão remota. App focado — multi-module completo seria over-engineering. Melhorias
prioritárias: build otimizado, product flavors, Java 17, CI/CD.

---

## Tasks

### T1 — gradle.properties com otimizações de build
**Status:** concluído
- Criar `gradle.properties` na raiz do projeto android
- Habilitar: parallel builds, build caching, daemon, JVM args 4g
- Habilitar: kotlin incremental, configuration cache, nonTransitiveRClass
- BuildConfig explícito

### T2 — Product flavors dev/prod
**Status:** concluído
- Adicionar `flavorDimensions` com dimensão `environment`
- Flavor `dev`: applicationIdSuffix=".dev", versionNameSuffix="-dev", appName diferente
- Flavor `prod`: IDs limpos, sem sufixo
- BuildConfig field `IS_DEV_BUILD` para uso condicional no código
- Manter `buildTypes` existentes (debug/release)

### T3 — Java 17
**Status:** concluído
- Atualizar `sourceCompatibility`/`targetCompatibility` de VERSION_11 para VERSION_17
- Atualizar `kotlinOptions.jvmTarget` de "11" para "17"

### T4 — CI/CD GitHub Actions
**Status:** concluído
- Criar `.github/workflows/android.yml`
- Jobs: unit tests, lint, build debug APK
- Usar JDK 17, cache gradle
- Upload APK como artifact

---

## Checklist Final

- [x] T1: gradle.properties criado e validado
- [x] T2: product flavors dev/prod funcionando
- [x] T3: Java 17 configurado
- [x] T4: CI/CD workflow criado
