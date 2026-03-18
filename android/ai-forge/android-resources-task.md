# Android Resources — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | Material3

---

## Contexto

App single-screen com WebSocket. Auditoria focada em strings, spacing, tema e assets.

---

## Phase 1: Code Review — Resultados

### O que já estava correto

| Item | Status |
|------|--------|
| `WorkflowAppTheme` com `darkColorScheme` M3 | ✅ |
| `AppColors` centralizados em object | ✅ |
| `CustomColors` via `staticCompositionLocalOf` | ✅ |
| `WorkflowShapes` com tokens M3 | ✅ |
| `WorkflowTypography` separado em `Type.kt` | ✅ |
| App dark-only (sem light theme) — intencional | ✅ |
| Sem `drawable-night/` necessário (dark-only) | ✅ |

---

## Issues Encontrados

### RS01: Strings hardcoded em componentes UI (HIGH)

`strings.xml` continha apenas `app_name`. Todas as strings visíveis ao usuário estavam hardcoded em Kotlin:

**Afetados:**
- `ConnectionBar.kt`: labels, placeholders, textos de botão, status labels
- `InteractionCard.kt`: label do TextField, botão Enviar, botões de resposta rápida
- `IdleState.kt`: mensagem de idle e last pipeline
- `OutputArea.kt`: texto do placeholder de waiting

### RS02: Ausência de sistema de Spacing (MEDIUM)

Sem `Spacing` CompositionLocal nem `dimens.xml`. Valores de espaçamento eram magic numbers dispersos.

### RS-FUTURA: Strings em FeedbackSnackbar e ViewModel (LOW)

`FeedbackMessage.toSnackbarSpec()` e `PipelineViewModel` contêm strings em PT-BR hardcoded.
Não podem usar `stringResource()` — chamados de `LaunchedEffect` (non-composable).
**Fix futuro:** Padrão `UiText` (sealed class `UiText.StringResource` / `UiText.DynamicString`).

---

## Phase 2: Task List

| # | Task | Prioridade | Status |
|---|------|-----------|--------|
| RS1 | ~~Extrair strings de UI para strings.xml~~ | HIGH | ✅ FEITO |
| RS2 | ~~Criar Spacing CompositionLocal em theme/~~ | MEDIUM | ✅ FEITO |
| RS3 | Migrar FeedbackSnackbar + ViewModel para UiText | LOW | 📋 FUTURA |

---

## Phase 3: Execução

### RS1: strings.xml — 11 strings adicionadas ✅

```xml
<!-- ConnectionBar -->
connection_ip_label, connection_ip_placeholder
connection_port_label, connection_port_placeholder
connection_btn_connect, connection_btn_connecting, connection_btn_disconnect
connection_status_connected, connection_status_reconnecting,
connection_status_connecting, connection_status_disconnected

<!-- InteractionCard -->
interaction_response_label, interaction_send
interaction_quick_ok, interaction_quick_yes, interaction_quick_no, interaction_quick_cancel

<!-- IdleState -->
idle_no_pipeline, idle_last_pipeline (%1$s)

<!-- OutputArea -->
output_waiting
```

**Arquivos atualizados:**
- `ConnectionBar.kt` — `stringResource()` em labels, placeholders, button text, status labels
- `InteractionCard.kt` — `stringResource()` em label, botão, quick response labels
- `IdleState.kt` — `stringResource()` em texto e semantics
- `OutputArea.kt` — `stringResource()` em placeholder text

### RS2: Spacing CompositionLocal ✅

Criado `ui/theme/Spacing.kt` com tokens:
```kotlin
Spacing(
    xs = 4.dp, sm = 8.dp, md = 16.dp, lg = 24.dp,
    xl = 32.dp, xxl = 48.dp,
    screenH = 8.dp, screenV = 8.dp,
    touchTarget = 48.dp, cardPadding = 16.dp,
)
```

`LocalSpacing` registrado em `WorkflowAppTheme` via `CompositionLocalProvider`.
Acesso: `MaterialTheme.spacing.md`

---

## Checklist Resources

### Strings
- [x] UI Text strings extraídas para strings.xml
- [x] Placeholders com %1$s para formatação (idle_last_pipeline)
- [ ] FeedbackSnackbar / ViewModel (futura — requer UiText)
- [x] Sem plurals necessários (app não exibe contagens)

### Dimensions
- [x] Sistema de Spacing via CompositionLocal (Compose-native)
- [ ] Sem WindowSizeClass — app phone-only por design

### Theme
- [x] Material Design 3 (darkColorScheme)
- [x] AppColors centralizados
- [x] CustomColors via CompositionLocal
- [x] WorkflowShapes com tokens
- [ ] Dynamic colors (Android 12+) — não implementado (dark-only theme fixo, intencional)

### Assets
- [x] ic_launcher com adaptive icon (mipmap-anydpi-v26)
- [x] Sem imagens bitmap — apenas vector drawables e Compose
- [x] Sem drawable-night necessário (app dark-only)

---

**Gerado por `/android:resources`**
**SystemForge — Documentation First Development**
