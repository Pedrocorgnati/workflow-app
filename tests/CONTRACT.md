# Tests Contract — workflow-app

Este documento descreve as fixtures compartilhadas da suite pytest-qt e
suas garantias canonicas. Hardening T9 do loop
`05-21-implantation-tasklist-aba-brainstorm` (item 008).

## Fixtures em `tests/conftest.py`

### `qapp` (session-scoped)

`QApplication` singleton compartilhado entre todos os testes Qt da sessao.
Reusa instancia existente quando ja criado (idempotente).

### `_cleanup_qt_widgets` (autouse, function-scoped)

Hardening T9 §13 (criterio 4): apos cada teste, deleta TODOS os widgets
remanescentes em duas passadas:

1. Fecha + destroi sincronamente (`shiboken6.delete`) todos os
   `app.topLevelWidgets()` — previne QComboBox popup leak.
2. Para cada widget em `app.allWidgets()` (filhos reparented que
   sobreviveram a passada 1), valida via `shiboken6.isValid` e chama
   `deleteLater()`.

Cross-cutting: afeta toda a suite (105+ arquivos). Validar em PR isolado
ao mudar comportamento.

### `qsettings_isolated` (autouse, function-scoped)

Hardening T9 §4 (criterio 5): aponta `QSettings.setPath` (User+System
scope IniFormat) para `tmp_path` por teste. Seta
`QT_QPA_PLATFORM=offscreen` (defensive contra ambientes sem display).
Garante zero contaminacao do `~/.config/` do usuario.

### `mcp_prompt_button_factory(qtbot)`

Hardening T9 §9 (criterio 12): factory de `MCPPromptButton` parametrizada.
Cria um `QWidget` parent montado + exposto via `qtbot.waitExposed`,
instancia o botao dentro do parent e retorna o tuplo `(parent, btn)`.

Assinatura:

```python
factory(
    button_type: str = "Claude",
    action: str = "Executar",
    target_path: str | None = "terminal-interactive-output",
    agent_name: str | None = "claude-coder",
    agent_path: str | None = "ai-forge/MCP/agents/claude-coder.md",
    radio_state_getter: Callable | None = None,
    label: str = "test-btn",
    prompt: str = "STUB",
    testid_slug: str | None = "test-slug",
) -> tuple[QWidget, MCPPromptButton]
```

Notas:
- `button_type="Codex"` forca `target_path="terminal-codex-output"`
  (regra do widget).
- Parent montado garante que `self.window()` retorne nao-None nos slots
  do widget (necessario para `_codex_target_alive` + `recheck_codex_
  availability` rodarem cedo).

### `mock_terminal_widget(qtbot)`

Hardening T9 §3 (criterio 7): cria `QPlainTextEdit` OFF-SCREEN visivel
com `testid="terminal-codex-output"`. Geometry em (-10000, -10000) com
`show()` real - `isVisibleTo(root)` retorna True, mas usuario nao ve
nada na tela.

Retorna `(root_frame, terminal_widget)`. `WA_DontShowOnScreen` NAO eh
usado porque invalida `isVisibleTo` e quebra o gate T7.

### `frozen_clock(monkeypatch)`

Hardening T9 §5 (criterio 6): mocka `time.monotonic_ns` no modulo
`workflow_app.widgets.mcp_prompt_button`. Permite avancar o relogio
manualmente sem sleep real:

```python
def test_debounce(frozen_clock):
    # ... primeiro clique ...
    frozen_clock(900)  # avanca 900ms
    # ... segundo clique passa a janela de debounce 800ms ...
```

Testes de debounce rodam em <50ms cada (validavel via
`pytest --durations=20`).

### `codex_alive_factory(monkeypatch)`

Hardening T9 §10 (criterio 12): monkeypatch granular de
`MCPPromptButton._codex_target_alive` retornando constante True/False.

```python
def test_codex_blocked(codex_alive_factory, mcp_prompt_button_factory):
    codex_alive_factory(False)  # T3 ausente
    _, btn = mcp_prompt_button_factory(button_type="Codex", action="send",
                                       target_path="terminal-codex-output")
    assert btn.isEnabled() is False
```

IMPORTANTE: chamar `codex_alive_factory(...)` ANTES de
`mcp_prompt_button_factory(...)` porque `__init__` ja avalia o cache.

## Helper `tests/_helpers.py`

### `assert_no_silent_fallback(mock_t1, mock_t2, toast_spy, expected_toast_text)`

Hardening T9 §6 (criterio 11): DRY do cenario 11 do mcp-flow §10.3 +
variantes T7. Garante que Codex bloqueado NAO caiu em fallback
silencioso para Claude/Kimi:

- `mock_t1.publish` NAO chamado (terminal Claude T1 nao recebeu).
- `mock_t2.publish` NAO chamado (terminal Kimi T2 nao recebeu).
- `toast_spy` recebeu pelo menos 1 emissao com `level="warning"` e
  texto literal exato.

## Pre-commit hook (criterio 13)

Hardening T9 §2: a suite proibe `xfail(strict=True)` (zona morta:
quando dependencia entrega, teste passa XPASS e quebra CI silenciosamente,
operador desativa strict ao inves de remover marcador).

Mecanismo canonico de skip enquanto modulo ausente:
`pytest.importorskip("workflow_app.widgets.X")`.

Hook bash em `scripts/check-no-xfail-strict.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
matches=$(grep -rn "xfail(strict=True)" tests/ || true)
if [ -n "$matches" ]; then
    echo "ERRO: xfail(strict=True) e PROIBIDO na suite (hardening T9 §2)."
    echo "Use pytest.importorskip() para skip enquanto dependencia ausente."
    echo "$matches"
    exit 1
fi
exit 0
```

Para integrar via pre-commit framework, adicionar entry em
`.pre-commit-config.yaml` da raiz do submodulo:

```yaml
- repo: local
  hooks:
    - id: check-no-xfail-strict
      name: Proibe xfail(strict=True) em tests/
      entry: scripts/check-no-xfail-strict.sh
      language: script
      pass_filenames: false
```

Quando `.pre-commit-config.yaml` ausente, rodar o script manualmente
antes do `git commit` (CI tambem o roda apos pytest).

## Coverage threshold (criterio 10)

`pyproject.toml [tool.pytest.ini_options]`:

```toml
addopts = "--cov=workflow_app.widgets.mcp_prompt_button --cov=workflow_app.widgets.mcp_prompt_actions --cov-branch --cov-report=term-missing --cov-fail-under=80"
```

Line + branch coverage combinado. Threshold 80% (deep doc compatible).
