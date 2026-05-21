# MCPPromptButton — Guia de integracao

Loop: `05-20-mcp-flow-implantation` · P1 scaffold · **NAO executar agora** — o widget esta isolado em `widgets/mcp_prompt_button.py` para evitar quebrar o workflow-app em execucao. A integracao acontece quando o item 010 (aba brainstorm) for re-executado.

## Status atual

- Widget standalone: `workflow_app.widgets.mcp_prompt_button.MCPPromptButton`
- Modal embutido: `MCPPromptConfigModal`
- Exportado em `workflow_app.widgets.__init__`
- Testes: `tests/test_mcp_prompt_button.py` (4 testes pytest-qt)
- `main_window.py` **nao foi alterado** (regra do loop)

## Slots conceituais alvo

- Aba brainstorm (3x3 grid atual com `brainstorm-md-picker` em `main_window.py:1720+`)
- `toolbar-prompts-config-gear` (gear de configuracao de prompts em `main_window.py:1413+`)

## Terminal targets canonicos

| target_path | testid em `output_panel.py` |
|---|---|
| `terminal-interactive-output` | terminal padrao Claude |
| `terminal-workspace-output` | terminal de workspace (modo `_workspace_mode`) |
| `terminal-codex-output` | terminal exclusivo Codex (item 010 deste loop) |

Regra dura: `button_type="Codex"` exige `target_path="terminal-codex-output"` (validado no `__init__`).

## 3 passos para wire (quando item 010 for re-executado)

### Passo 1 — Importar no `main_window.py`

```python
from workflow_app.widgets import MCPPromptButton
```

Posicao sugerida: junto aos demais imports de widgets locais (perto de `from workflow_app.widgets.notification_banner import ...`).

### Passo 2 — Instanciar na construcao da aba brainstorm

Localizar o bloco que constroi os 9 botoes da grade 3x3 (apos `md_btn.clicked.connect(_pick_md)` em `main_window.py:1746`). Substituir cada `QPushButton` da grade por uma instancia `MCPPromptButton` com os 7 args canonicos:

```python
btn = MCPPromptButton(
    label="Claude · Analyse",
    button_type="Claude",
    prompt=Path(self._brainstorm_md_path) if self._brainstorm_md_path else "",
    agent_name=None,
    agent_path=None,
    action="send",
    target_path="terminal-interactive-output",
    parent=self,
)
btn.prompt_requested.connect(self._on_mcp_prompt_requested)
grid_layout.addWidget(btn, row, col)
```

### Passo 3 — Implementar handler `_on_mcp_prompt_requested`

Novo metodo em `MainWindow`. Roteia o payload para o terminal alvo via `self._output_panel` (ja existente). Stub:

```python
def _on_mcp_prompt_requested(self, payload: dict) -> None:
    target = payload["target_path"]
    text = payload["prompt_text"]
    action = payload["action"]
    # rotear via output_panel conforme target (interactive | workspace | codex)
    # respeitar action (send=cola e envia, queue=enfileira no command_queue, config=abre modal)
    ...
```

## Anti-patterns (NAO fazer)

- Editar `main_window.py` enquanto este scaffold P1 esta em revisao
- Importar `MCPPromptButton` em `output_panel.py` (widget e apresentacional, nao conhece terminais)
- Bypassar validacao Codex chamando `setattr(btn, "_target_path", ...)` apos construcao
- Persistir o widget em QSettings (config persiste no project.json, nao no botao)

## Checklist de re-execucao do item 010

- [ ] Confirmar que `terminal-codex-output` existe em `output_panel.py` (criar se ausente)
- [ ] Wire dos 3 passos acima
- [ ] Adicionar testes de integracao em `tests/integration/test_main_window_mcp_brainstorm.py`
- [ ] Atualizar `data-testid` registry em `.claude/commands/data-test-id.md`
- [ ] Bump de WORKFLOW-APP-RULES.md secao 2 (registrar `mcp-prompt-button-*` nos testids canonicos)
