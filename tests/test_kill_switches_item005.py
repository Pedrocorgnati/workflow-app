"""Item 005 (pacote H pt1) — kill-switches dedicados de C26.

Cada switch entregue aqui e boot-frozen e fail-closed. Testar isso exige
processo NOVO por estado: mutar `os.environ` dentro do processo depois do
import nao prova nada, porque a captura ja aconteceu. Todos os testes de
estado rodam via `subprocess.run` com o ambiente montado antes do boot,
seguindo o padrao do item 002 (`test_command_queue_widget.py::_run_probe`).

Cobertura por switch: par presente/ausente, os dois valores reconhecidos
(`"1"`/`"0"`), o valor nao reconhecido, o congelamento no boot e o ponto unico
de leitura do literal em `src/`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]

# Switches entregues pelo item 005, todos boot-frozen e fail-closed.
_ITEM_005_SWITCHES: tuple[tuple[str, str], ...] = (
    ("SF_MAIN_PROVIDERS_V2", "main_providers_v2"),
    ("SF_PARALLEL_WORKERS_V2", "parallel_workers_v2"),
    ("SF_LLM_FLAGS_V2", "llm_flags_v2"),
    ("SF_MCP_THINK_EXEC_V2", "mcp_think_exec_v2"),
)

_ALL_ITEM_005_FLAG_NAMES = tuple(name for name, _ in _ITEM_005_SWITCHES)


def _run_probe(probe: str, env_overrides: dict[str, str | None]) -> dict:
    """Roda `probe` em processo novo com o ambiente pedido.

    Valor `None` REMOVE a variavel do filho (estado ausente). Todas as env vars
    do item 005 sao removidas por default, para que um switch ligado no shell do
    operador nao contamine o cenario sob teste.
    """
    env = os.environ.copy()
    for flag in _ALL_ITEM_005_FLAG_NAMES:
        env.pop(flag, None)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"probe falhou (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


def _state_probe(prefix: str) -> str:
    return f'''import json
from workflow_app.config.feature_flags import (
    {prefix}_enabled, {prefix}_flag_name, {prefix}_state,
)
print(json.dumps({{
    "flag_name": {prefix}_flag_name(),
    "state": {prefix}_state(),
    "enabled": {prefix}_enabled(),
}}, sort_keys=True))
'''


def _freeze_probe(prefix: str, literal: str) -> str:
    """Muta a env var DEPOIS do import e reconsulta: a resposta nao pode mudar."""
    return f'''import json
import os
from workflow_app.config.feature_flags import {prefix}_enabled, {prefix}_state


def observe():
    return {{"state": {prefix}_state(), "enabled": {prefix}_enabled()}}


before = observe()
os.environ[{literal!r}] = "1"
after_set = observe()
os.environ.pop({literal!r}, None)
after_unset = observe()
print(json.dumps({{
    "before": before, "after_set": after_set, "after_unset": after_unset,
}}, sort_keys=True))
'''


# ======================================================================
# Estado por switch: par presente/ausente + fail-closed
# ======================================================================


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
def test_switch_absent_falls_back_to_legacy(flag: str, prefix: str):
    """Ausente = legado. Nenhum switch do item 005 e opt-out."""
    got = _run_probe(_state_probe(prefix), {flag: None})
    assert got == {"flag_name": flag, "state": "absent", "enabled": False}, got


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
def test_switch_present_with_one_enables(flag: str, prefix: str):
    """Somente `"1"` liga o caminho novo."""
    got = _run_probe(_state_probe(prefix), {flag: "1"})
    assert got == {"flag_name": flag, "state": "on", "enabled": True}, got


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
def test_switch_zero_is_explicit_off(flag: str, prefix: str):
    """`"0"` e desligamento explicito, distinguivel de ausente pelo `state`."""
    got = _run_probe(_state_probe(prefix), {flag: "0"})
    assert got == {"flag_name": flag, "state": "off", "enabled": False}, got


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
@pytest.mark.parametrize("raw", [" 1 ", "1\n", "TRUE", "true", "01", "yes", ""])
def test_switch_unrecognized_values_stay_closed(flag: str, prefix: str, raw: str):
    """Comparacao literal: sem `strip`, sem `casefold`, sem coercao.

    Toda normalizacao alarga o conjunto de valores que LIGAM o caminho novo,
    que e o oposto de fail-closed.
    """
    got = _run_probe(_state_probe(prefix), {flag: raw})
    assert got == {"flag_name": flag, "state": "unrecognized", "enabled": False}, got


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
@pytest.mark.parametrize("boot_value", [None, "0", "1"])
def test_switch_is_frozen_at_boot(flag: str, prefix: str, boot_value: str | None):
    """Trocar a env var no processo ja iniciado nao muda a resposta."""
    got = _run_probe(_freeze_probe(prefix, flag), {flag: boot_value})
    assert got["after_set"] == got["before"], got
    assert got["after_unset"] == got["before"], got


@pytest.mark.parametrize(("flag", "prefix"), _ITEM_005_SWITCHES)
def test_switch_has_single_env_read_point_in_src(flag: str, prefix: str):
    """Ponto unico de LEITURA do literal em `src/` (criterio A1 do item 002).

    Comentario que cita o literal para explicar um branch nao le nada e nao
    pode divergir do helper — por isso linhas iniciadas por `#` sao ignoradas,
    exatamente como no guard do `SF_LLM_CONFIG_V2`.
    """
    hits = []
    for path in sorted((_WORKFLOW_APP_ROOT / "src").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if flag not in line:
                continue
            if line.strip().startswith("#"):
                continue
            hits.append(
                (path.relative_to(_WORKFLOW_APP_ROOT).as_posix(), lineno, line.strip())
            )
    assert len(hits) == 1, f"ponto unico de leitura violado para {flag}: {hits}"
    assert hits[0][0] == "src/workflow_app/config/feature_flags.py", hits


def test_switches_are_not_reexported_in_config_package():
    """Precedente `grok_spike_*` (A005-11): switch dedicado nao vai para o `__init__`."""
    probe = '''import json
import workflow_app.config as c
print(json.dumps({"leaked": sorted(
    n for n in dir(c)
    if n.startswith((
        "main_providers_v2", "parallel_workers_v2", "mcp_think_exec_v2",
    ))
)}))
'''
    got = _run_probe(probe, {})
    assert got["leaked"] == [], got


_TE_COMMANDS_PROBE = '''import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton
from workflow_app.main_window import MainWindow

app = QApplication.instance() or QApplication([])
window = MainWindow()
commands = {
    str(button.property("testid")): str(button.property("te_command"))
    for button in window.findChildren(QPushButton)
    if button.property("te_command")
}
for combo in window.findChildren(QComboBox):
    for i in range(combo.count()):
        data = combo.itemData(i)
        if isinstance(data, dict) and data.get("te_command") and data.get("testid"):
            commands[str(data["testid"])] = str(data["te_command"])
print(json.dumps(commands, sort_keys=True))
window.close()
'''


@pytest.mark.parametrize("raw", [None, "0", "TRUE", "1"])
def test_thinking_kimi_always_uses_k3_when_think_exec_enabled(raw: str | None):
    """O botao Thinking `kimi-k3` publica sempre o wrapper K3."""
    got = _run_probe(
        _TE_COMMANDS_PROBE,
        {"SF_MCP_THINK_EXEC_V2": "1", "SF_MCP_WRAPPERS_V2": raw},
    )
    assert got["output-mcp-action-thinking-kimi"] == "/mcp:kimi-k3"
    assert got["output-mcp-action-execution-kimi"] == "/mcp:kimi"


def test_removed_mcp_wrappers_flag_does_not_materialize_think_exec_row_by_itself():
    """A env removida nao materializa a matriz Thinking/Execution sozinha."""
    got = _run_probe(
        _TE_COMMANDS_PROBE,
        {"SF_MCP_THINK_EXEC_V2": None, "SF_MCP_WRAPPERS_V2": "1"},
    )
    assert "output-mcp-action-thinking-kimi" not in got
    assert "output-mcp-action-execution-kimi" not in got


# ======================================================================
# Comportamento gateado: prova de que nenhum switch e inerte
# ======================================================================


_FLAGS_SET_PROBE = '''import json
from workflow_app.config import llm_flags
print(json.dumps({
    "supported": sorted(llm_flags._SUPPORTED_MCP_FLAGS),
    "order": list(llm_flags._FLAG_CANONICAL_ORDER),
    "by_terminal": {k: sorted(v) for k, v in llm_flags._FLAGS_BY_TERMINAL.items()},
    "literal_to_main": llm_flags._FLAG_LITERAL_TO_MAIN,
    "redundant": llm_flags._REDUNDANT_FLAG_MAINS,
}, sort_keys=True))
'''


def test_llm_flags_v2_absent_closes_set_to_two_literals():
    """C26: sem o switch, o conjunto fechado e `--codex` + `--kimi`."""
    got = _run_probe(_FLAGS_SET_PROBE, {"SF_LLM_FLAGS_V2": None})
    assert got["supported"] == ["--codex", "--kimi"], got
    assert got["order"] == ["--codex", "--kimi"], got
    assert got["by_terminal"] == {
        "T1": ["--codex", "--kimi"],
        "T2": ["--kimi"],
        "T3": ["--codex"],
    }, got
    assert got["literal_to_main"] == {"--codex": "codex", "--kimi": "kimi"}, got
    assert got["redundant"] == {"--codex": "codex", "--kimi": "kimi"}, got


def test_llm_flags_v2_on_opens_the_seven_canonical_literals():
    """Com o switch ligado, os literais thinking/execution na ordem canonica."""
    got = _run_probe(_FLAGS_SET_PROBE, {"SF_LLM_FLAGS_V2": "1"})
    assert got["order"] == [
        "--fable", "--opus", "--codex-ultra", "--kimi-k3", "--grok-xhigh",
        "--grok", "--sonnet", "--kimi", "--qwen", "--codex",
    ], got
    assert got["by_terminal"] == {
        "T1": [
            "--codex", "--codex-ultra", "--fable", "--grok", "--grok-xhigh",
            "--kimi", "--kimi-k3", "--opus", "--qwen", "--sonnet",
        ],
        "T2": ["--kimi", "--kimi-k3", "--qwen"],
        "T3": ["--codex", "--codex-ultra", "--grok", "--grok-xhigh"],
    }, got
    assert len(got["redundant"]) == 7, got


def test_llm_flags_module_stays_qt_free():
    """O modulo e puro: importa-lo nao pode arrastar PySide6."""
    probe = '''import json
import sys
import workflow_app.config.llm_flags  # noqa: F401
print(json.dumps({"qt": sorted(m for m in sys.modules if m.startswith("PySide"))}))
'''
    assert _run_probe(probe, {"SF_LLM_FLAGS_V2": "1"})["qt"] == []


_WIDGET_PROBE = '''import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

app = QApplication([])
w = CommandQueueWidget()
w.show()
print(json.dumps({
    "main_hidden": {
        slug: w._main_radio_map[slug].isHidden()
        for slug in ("claude", "codex", "kimi", "qwen", "grok",
                     "opus", "sonnet", "kimi-k3")
    },
    "worker_hidden": {
        "kimi": w._use_kimi_chk.isHidden(),
        "qwen": w._use_qwen_chk.isHidden(),
        "codex": w._use_codex_chk.isHidden(),
        "grok": w._use_grok_chk.isHidden(),
    },
    "worker_checked": {
        "qwen": w._use_qwen_chk.isChecked(),
        "grok": w._use_grok_chk.isChecked(),
    },
}, sort_keys=True))
'''


def test_main_providers_gate_moved_off_the_global_switch():
    """Prova de gate MOVIDO, nao duplicado.

    Com `SF_LLM_CONFIG_V2=1` mas `SF_MAIN_PROVIDERS_V2` ausente, os 4 slugs
    gateados tem que ficar OCULTOS. Se ainda respondessem ao switch global, o
    gate teria sido duplicado e este teste ficaria vermelho.
    """
    got = _run_probe(
        _WIDGET_PROBE, {"SF_LLM_CONFIG_V2": "1", "SF_MAIN_PROVIDERS_V2": None}
    )
    for slug in ("qwen", "opus", "sonnet", "kimi-k3"):
        assert got["main_hidden"][slug] is True, (slug, got["main_hidden"])
    for slug in ("claude", "codex", "kimi"):
        assert got["main_hidden"][slug] is False, (slug, got["main_hidden"])


def test_main_providers_gate_opens_the_four_slugs():
    got = _run_probe(_WIDGET_PROBE, {"SF_MAIN_PROVIDERS_V2": "1"})
    for slug in ("claude", "codex", "kimi", "qwen"):
        assert got["main_hidden"][slug] is False, (slug, got["main_hidden"])
    for slug in ("opus", "sonnet", "kimi-k3"):
        assert got["main_hidden"][slug] is True, (slug, got["main_hidden"])


def test_grok_radio_stays_under_its_own_switch():
    """C7: `grok` nao entra em conjuncao de dois switches.

    `SF_MAIN_PROVIDERS_V2=1` sozinho nao revela `grok`; `SF_GROK_SPIKE=1`
    sozinho revela.
    """
    only_main = _run_probe(
        _WIDGET_PROBE, {"SF_MAIN_PROVIDERS_V2": "1", "SF_GROK_SPIKE": None}
    )
    assert only_main["main_hidden"]["grok"] is True, only_main["main_hidden"]

    only_spike = _run_probe(
        _WIDGET_PROBE, {"SF_MAIN_PROVIDERS_V2": None, "SF_GROK_SPIKE": "1"}
    )
    assert only_spike["main_hidden"]["grok"] is False, only_spike["main_hidden"]


def test_parallel_workers_absent_keeps_two_worker_roster():
    """Legado: `kimi` no T2 e `codex` no T3; `qwen`/`grok` ocultos E desmarcados."""
    got = _run_probe(
        _WIDGET_PROBE, {"SF_PARALLEL_WORKERS_V2": None, "SF_GROK_SPIKE": "1"}
    )
    assert got["worker_hidden"] == {
        "kimi": False, "qwen": True, "codex": False, "grok": True,
    }, got["worker_hidden"]
    # Consumidores a jusante leem `isChecked()` sem consultar visibilidade.
    assert got["worker_checked"] == {"qwen": False, "grok": False}, got


def test_parallel_workers_on_opens_the_four_worker_roster():
    got = _run_probe(_WIDGET_PROBE, {"SF_PARALLEL_WORKERS_V2": "1"})
    assert got["worker_hidden"] == {
        "kimi": False, "qwen": False, "codex": False, "grok": False,
    }, got["worker_hidden"]


_TE_PROBE = '''import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import workflow_app.main_window as mw

print(json.dumps({"think_exec": mw.mcp_think_exec_v2_enabled(),
                  "global_v2": mw.llm_config_v2_enabled()}))
'''


def test_think_exec_gate_moved_off_the_global_switch():
    """`SF_LLM_CONFIG_V2=1` nao liga mais o par Thinking/Execution sozinho."""
    got = _run_probe(
        _TE_PROBE, {"SF_LLM_CONFIG_V2": "1", "SF_MCP_THINK_EXEC_V2": None}
    )
    assert got == {"think_exec": False, "global_v2": True}, got

    got_on = _run_probe(
        _TE_PROBE, {"SF_LLM_CONFIG_V2": None, "SF_MCP_THINK_EXEC_V2": "1"}
    )
    assert got_on == {"think_exec": True, "global_v2": False}, got_on
