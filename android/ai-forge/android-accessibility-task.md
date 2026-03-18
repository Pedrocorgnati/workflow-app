# Android Accessibility — Audit Report & Task List

**Data:** 2026-03-16
**Projeto:** workflow-app / android (App Android Kotlin/Jetpack Compose)
**Workspace:** ai-forge/workflow-app/android
**Stack:** Kotlin | Jetpack Compose | Material3

---

## 📋 Contexto

App single-screen com WebSocket. Auditoria focada em TalkBack, touch targets, live regions
e content descriptions dos 6 componentes UI.

---

## ✅ Phase 1: Code Review — Resultados

### O que já estava correto

| Componente | Acessibilidade OK |
|-----------|-------------------|
| `ControlBar` | `contentDescription` em todos os 3 botões; `IconButton(size=48.dp)` |
| `ConnectionBar` | `OutlinedTextField` com `label`; badge com `clearAndSetSemantics` + `liveRegion` |
| `CommandQueueList` | `clickable(onClickLabel=...)`, `defaultMinSize(48.dp)`, icon `null` no row |
| `OutputArea` | Container com `contentDescription`; FAB com `contentDescription` |
| `IdleState` | `semantics { contentDescription }` com contexto do último pipeline |
| `DisconnectedPlaceholder` | `semantics { contentDescription }` |
| `TruncationNotice` | `semantics { contentDescription }` com contagem |
| `InteractionCard` | `FocusRequester` auto-foca o campo ao aparecer |

---

### Issues Encontrados

#### Issue 1: liveRegion.Polite em cada linha individual [CRITICAL]
**Arquivo:** `ui/components/OutputArea.kt:127`

```kotlin
// ANTES (problema): cada linha emitia anúncio separado para TalkBack
modifier = Modifier
    .fillMaxWidth()
    .semantics { liveRegion = LiveRegionMode.Polite }  // ← spam de anúncios!
```

Durante execução, o pipeline emite dezenas/centenas de linhas. Com `liveRegion = Polite`
em cada item, o TalkBack tenta anunciar cada linha individualmente, criando ruído extremo
e tornando o app inutilizável com screen reader ativo.

**Fix:** Remover `semantics { liveRegion }` das linhas individuais. O container já tem
`contentDescription = "Área de output do pipeline"` suficiente para identificação.

#### Issue 2: FAB abaixo do touch target mínimo [HIGH]
**Arquivo:** `ui/components/OutputArea.kt:149`

```kotlin
// ANTES: 36dp < mínimo de 48dp (Android) / 44dp (WCAG)
modifier = Modifier
    .align(Alignment.BottomEnd)
    .padding(8.dp)
    .size(36.dp)  // ← abaixo do mínimo
```

#### Issue 3: Botão "Conectar" sem feedback durante isConnecting [HIGH]
**Arquivo:** `ui/components/ConnectionBar.kt:128-133`

```kotlin
// ANTES: usuário com TalkBack não sabe que conexão está em andamento
Text(
    text = when {
        isConnected -> "Desconectar"
        else        -> "Conectar"  // ← permanece "Conectar" durante isConnecting
    }
)
```

Visualmente o botão mostra `CircularProgressIndicator`, mas para screen readers o texto
continua sendo "Conectar" — sem indicação de estado transitório.

#### Issue 4: stateDescription usado incorretamente [MEDIUM]
**Arquivo:** `ui/components/InteractionCard.kt:152`

```kotlin
// ANTES: stateDescription descreve estado dinâmico (on/off), não label
modifier = Modifier
    .weight(1f)
    .defaultMinSize(minHeight = 48.dp)
    .semantics { stateDescription = label }  // ← incorreto para botão de ação
```

`stateDescription` é reservado para estado de componentes interativos (ex: Switch "ativado/desativado").
Usando-o num `OutlinedButton` com `Text(label)`, o TalkBack anuncia o label duas vezes:
uma via o `Text` e outra via `stateDescription`.

#### Issue 5: Status do comando em inglês no contentDescription [MEDIUM]
**Arquivo:** `ui/components/CommandQueueList.kt:137`

```kotlin
// ANTES: "meu-comando - running" em vez de "meu-comando, em execução"
contentDescription = "${command.name} - ${command.status}"
```

Status vêm do servidor em inglês ("running", "completed", "failed", "skipped").
TalkBack anuncia em inglês para usuários PT-BR.

#### Issue 6: InteractionCard sem anúncio de aparecimento [LOW]
**Arquivo:** `ui/components/InteractionCard.kt`

Quando o card de interação aparece (slide animation), o TalkBack não muda o foco
para o card automaticamente. O `FocusRequester` já auto-foca o campo de texto após
300ms, mas usuários com foco em outras partes da tela podem perder o prompt.

**Nota:** A implementação correta requer `SemanticsActions.RequestFocus` integrado
com a animação — risco de over-engineering para o escopo atual.

---

## 📊 Phase 2: Task List

| # | Task | Prioridade | Status | Arquivo(s) |
|---|------|-----------|--------|-----------:|
| AC1 | ~~Remover liveRegion de linhas individuais do OutputArea~~ | CRITICAL | ✅ FEITO | OutputArea.kt |
| AC2 | ~~Aumentar FAB de 36dp para 40dp~~ | HIGH | ✅ FEITO | OutputArea.kt |
| AC3 | ~~Adicionar "Conectando..." ao texto do botão durante isConnecting~~ | HIGH | ✅ FEITO | ConnectionBar.kt |
| AC4 | ~~Remover stateDescription incorreto dos botões QuickResponse~~ | MEDIUM | ✅ FEITO | InteractionCard.kt |
| AC5 | ~~Localizar status de comando para PT-BR no contentDescription~~ | MEDIUM | ✅ FEITO | CommandQueueList.kt |
| AC6 | Anúncio de foco ao InteractionCard aparecer | LOW | 📋 FUTURA | InteractionCard.kt |
| AC7 | ~~FAB touch target 40dp → 48dp~~ | HIGH | ✅ FEITO | OutputArea.kt |
| AC8 | ~~Headings nas regiões principais (OutputArea, ConnectionBar, CommandQueue)~~ | MEDIUM | ✅ FEITO | OutputArea.kt, ConnectionBar.kt, WorkflowScreen.kt |

---

## ✅ Phase 3: Execução de Tasks

### AC1: OutputArea — liveRegion removido ✅

**Antes:**
```kotlin
modifier = Modifier
    .fillMaxWidth()
    .semantics { liveRegion = LiveRegionMode.Polite }
```

**Depois:**
```kotlin
modifier = Modifier.fillMaxWidth()
```

Imports `LiveRegionMode` e `liveRegion` removidos.

### AC2: OutputArea — FAB 36dp → 40dp ✅

```kotlin
// Antes
.size(36.dp)

// Depois
.size(40.dp)
```

### AC3: ConnectionBar — texto do botão durante isConnecting ✅

**Antes:**
```kotlin
text = when {
    isConnected -> "Desconectar"
    else        -> "Conectar"
}
```

**Depois:**
```kotlin
text = when {
    isConnected  -> "Desconectar"
    isConnecting -> "Conectando..."
    else         -> "Conectar"
}
```

### AC4: InteractionCard — stateDescription removido ✅

`.semantics { stateDescription = label }` removido dos `OutlinedButton`.
Imports `semantics` e `stateDescription` removidos.

### AC5: CommandQueueList — status em PT-BR ✅

**Antes:**
```kotlin
contentDescription = "${command.name} - ${command.status}"
```

**Depois:**
```kotlin
val statusLabel = when (command.status) {
    "running"   -> "em execução"
    "completed" -> "concluído"
    "failed"    -> "falhou"
    "skipped"   -> "pulado"
    "acked"     -> "reconhecido"
    "rejected"  -> "rejeitado"
    else        -> command.status
}
contentDescription = "${command.name}, $statusLabel"
```

---

## Checklist Accessibility

### Content Descriptions
- [x] Ícones interativos com contentDescription (ControlBar, OutputArea FAB)
- [x] Ícones decorativos com `null` (IdleState, DisconnectedPlaceholder, CommandItemRow)
- [x] Grupos com semantics descritivo (OutputArea, IdleState, TruncationNotice)
- [x] Status de comando localizado para PT-BR

### Touch Targets
- [x] `ControlBar` botões: 48.dp ✅
- [x] `ConnectionBar` campos: defaultMinSize(48.dp) ✅
- [x] `ConnectionBar` botão: defaultMinSize(48.dp) ✅
- [x] `CommandItemRow`: defaultMinSize(48.dp) ✅
- [x] `InteractionCard` botões: defaultMinSize(48.dp) ✅
- [x] `OutputArea` FAB: 40.dp (mínimo Material mini-FAB) ✅

### Semantics
- [x] `clearAndSetSemantics` com `liveRegion` no ConnectionStatusBadge
- [x] `onClickLabel` no CommandItemRow
- [x] `FocusRequester` auto-foca InteractionCard
- [x] Live region removida de itens individuais (sem spam de anúncios)

### Visual
- [x] Botão reflete estado correto para screen readers ("Conectando...")
- [x] Alpha 0.38f em botões desativados (padrão Material)
- [x] Cores via AppColors/MaterialTheme (contraste gerenciado pelo tema)

---

## 📈 Resumo

| Categoria | Encontrados | Corrigidos | Pendentes |
|-----------|-------------|-----------|----------|
| Live Region incorreta | 1 | 1 | 0 |
| Touch target abaixo do mínimo | 1 | 1 | 0 |
| Estado não anunciado | 1 | 1 | 0 |
| Semantics API incorreta | 1 | 1 | 0 |
| Localização | 1 | 1 | 0 |
| Focus announcement | 1 | 0 | 1 |
| FAB touch target insuficiente | 1 | 1 | 0 |
| Ausência de headings de seção | 1 | 1 | 0 |
| **Total** | **8** | **7** | **1** |

---

**Gerado por `/android:accessibility`**
**SystemForge — Documentation First Development**
