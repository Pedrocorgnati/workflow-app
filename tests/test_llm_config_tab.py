"""Loop 08-11-llm-config-multillm-expansion, item 017.

Aba LLM Config no output-toolbar-section-selector, com kill-switch
SF_LLM_CONFIG_V2 controlando a existencia da aba.

G2 do loop: a flag e lida no BOOT do processo. Cada estado da flag roda em
subprocesso proprio, com env montado explicitamente.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]

_FLAG_NAME = "SF_LLM_CONFIG_V2"

# Probe que verifica a estrutura do selector e da aba LLM Config.
# Roda em subprocesso com o ambiente montado pelo teste.
_LLM_CONFIG_TAB_PROBE = """\
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout

app = QApplication.instance() or QApplication(sys.argv)

from workflow_app.main_window import MainWindow

win = MainWindow()

selector = win._toolbar_section_selector
stack = win._toolbar_section_stack
btns = win._toolbar_section_btns

btn_testids = [btn.property("testid") for btn in btns]
stack_count = stack.count()

llm_config_btn = None
for btn in btns:
    if btn.property("testid") == "output-toolbar-section-llm-config":
        llm_config_btn = btn
        break

llm_config_widget = None
if llm_config_btn is not None:
    # Find by testid in stack pages (button index != stack index when flag enabled)
    from PySide6.QtWidgets import QWidget as _W
    for i in range(stack.count()):
        w = stack.widget(i)
        if w.property("testid") == "output-toolbar-section-llm-config":
            llm_config_widget = w
            break

llm_box = win._command_queue._llm_box
llm_box_parent_testid = None
if llm_box.parentWidget() is not None:
    llm_box_parent_testid = llm_box.parentWidget().property("testid")

llm_box_layout_type = type(llm_box.layout()).__name__

# Check for terminal-insertions button
has_terminal_insertions = "output-toolbar-section-terminal-insertions" in btn_testids

# Check for llm-config containers
containers = []
if llm_config_widget is not None:
    from PySide6.QtWidgets import QWidget as _W
    all_children = [llm_config_widget, *llm_config_widget.findChildren(_W)]
    for tid in ("llm-config-flags-container", "llm-config-main-llm-container", "llm-config-parallel-container"):
        for child in all_children:
            if child.property("testid") == tid:
                containers.append(tid)
                break

print(json.dumps({
    "btn_count": len(btns),
    "stack_count": stack_count,
    "btn_testids": btn_testids,
    "has_llm_config": llm_config_btn is not None,
    "has_terminal_insertions": has_terminal_insertions,
    "llm_config_parent_testid": llm_box_parent_testid,
    "llm_box_layout_type": llm_box_layout_type,
    "llm_config_containers": sorted(containers),
    "flag_enabled": llm_config_btn is not None,
}))
"""


def _run_probe(env_override: dict[str, str] | None = None) -> dict:
    """Run the probe in a subprocess with the given env overrides."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    if env_override:
        env.update(env_override)
    # Remove the flag by default unless explicitly set
    if env_override is None or _FLAG_NAME not in env_override:
        env.pop(_FLAG_NAME, None)

    result = subprocess.run(
        [sys.executable, "-c", _LLM_CONFIG_TAB_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Probe failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip().split("\n")[-1])


# --- C-03: selector tem 6 secoes, LLM Config na ultima posicao (flag ligada) ---


class TestLLMConfigTabFlagEnabled:
    """Tests with SF_LLM_CONFIG_V2=1."""

    def test_llm_config_tab_selector_has_6_sections_with_llm_config_last(self):
        """C-03: output-toolbar-section-selector tem 6 secoes, LLM Config na ultima."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["btn_count"] == 6, (
            f"Expected 6 sections, got {data['btn_count']}: {data['btn_testids']}"
        )
        assert data["btn_testids"][-1] == "output-toolbar-section-llm-config", (
            f"LLM Config should be last, got: {data['btn_testids']}"
        )

    def test_llm_config_tab_terminal_insertions_removed(self):
        """With flag enabled, TERMINAL INSERTIONS is removed from selector."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert not data["has_terminal_insertions"], (
            "TERMINAL INSERTIONS should be removed when flag is enabled"
        )

    def test_llm_config_tab_exists(self):
        """LLM Config button and stack page exist."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["has_llm_config"], "LLM Config tab should exist with flag=1"

    def test_llm_config_tab_stack_has_7_pages(self):
        """Stack has 7 pages (6 original + LLM Config) when flag enabled."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["stack_count"] == 7, (
            f"Expected 7 stack pages, got {data['stack_count']}"
        )


# --- C-04: queue-div-llm-routing e QHBoxLayout na aba nova ---


class TestLLMConfigTabLayout:
    """C-04: queue-div-llm-routing layout and parent."""

    def test_llm_routing_is_in_llm_config_tab(self):
        """queue-div-llm-routing reparenteado para a aba LLM Config."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["llm_config_parent_testid"] == "output-toolbar-section-llm-config", (
            f"queue-div-llm-routing should be inside LLM Config tab, "
            f"got parent: {data['llm_config_parent_testid']}"
        )

    def test_llm_config_containers_exist(self):
        """Empty containers for items 018-021 exist with stable testids."""
        data = _run_probe({_FLAG_NAME: "1"})
        expected = [
            "llm-config-flags-container",
            "llm-config-main-llm-container",
            "llm-config-parallel-container",
        ]
        assert data["llm_config_containers"] == expected, (
            f"Expected containers {expected}, got {data['llm_config_containers']}"
        )


# --- Flag ausente: aba LLM Config NAO existe, layout legado ---


class TestLLMConfigTabFlagAbsent:
    """With flag absent, LLM Config tab must NOT exist."""

    def test_llm_config_tab_absent_when_flag_missing(self):
        """Flag ausente: aba LLM Config nao existe."""
        data = _run_probe()
        assert not data["has_llm_config"], (
            "LLM Config tab should NOT exist when flag is absent"
        )

    def test_terminal_insertions_present_when_flag_absent(self):
        """Flag ausente: TERMINAL INSERTIONS permanece no selector."""
        data = _run_probe()
        assert data["has_terminal_insertions"], (
            "TERMINAL INSERTIONS should be present when flag is absent"
        )

    def test_selector_has_6_sections_legacy(self):
        """Flag ausente: selector tem 6 secoes legadas."""
        data = _run_probe()
        assert data["btn_count"] == 6
        assert data["stack_count"] == 6

    def test_llm_routing_in_top_row_when_flag_absent(self):
        """Flag ausente: queue-div-llm-routing permanece na top-row."""
        data = _run_probe()
        assert data["llm_config_parent_testid"] != "output-toolbar-section-llm-config", (
            "queue-div-llm-routing should NOT be in LLM Config tab when flag is absent"
        )


# --- Flag "0": mesmo comportamento da flag ausente ---


class TestLLMConfigTabFlagOff:
    """With SF_LLM_CONFIG_V2=0, same as absent (legacy layout)."""

    def test_llm_config_tab_absent_when_flag_off(self):
        """Flag='0': aba LLM Config nao existe."""
        data = _run_probe({_FLAG_NAME: "0"})
        assert not data["has_llm_config"], (
            "LLM Config tab should NOT exist when flag='0'"
        )

    def test_terminal_insertions_present_when_flag_off(self):
        """Flag='0': TERMINAL INSERTIONS permanece."""
        data = _run_probe({_FLAG_NAME: "0"})
        assert data["has_terminal_insertions"]

    def test_selector_has_6_sections_legacy(self):
        """Flag='0': selector tem 6 secoes legadas."""
        data = _run_probe({_FLAG_NAME: "0"})
        assert data["btn_count"] == 6
        assert data["stack_count"] == 6


# --- Item 020: Parallel Workers Exclusivity (PW-01) ---


class TestParallelWorkersExclusivity:
    """Item 020: checkboxes qwen/grok + PW-01 exclusivity + persistence."""

    def _make_widget(self):
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        return CommandQueueWidget()

    def test_qwen_checkbox_exists_with_correct_testid(self, qapp):
        w = self._make_widget()
        assert w._use_qwen_chk.property("testid") == "queue-chk-use-qwen"

    def test_grok_checkbox_exists_with_correct_testid(self, qapp):
        w = self._make_widget()
        assert w._use_grok_chk.property("testid") == "queue-chk-use-grok"

    def test_pw01_t2_checking_qwen_unchecks_kimi(self, qapp, qtbot):
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        toasts = []
        signal_bus.toast_requested.connect(lambda msg, level: toasts.append(msg))
        try:
            w._use_kimi_chk.setChecked(True)
            assert w._use_kimi_chk.isChecked()
            w._use_qwen_chk.setChecked(True)
            assert not w._use_kimi_chk.isChecked(), "kimi should be unchecked by PW-01"
            assert w._use_qwen_chk.isChecked()
            assert any("Qwen substituiu Kimi" in t for t in toasts)
        finally:
            signal_bus.toast_requested.disconnect()

    def test_pw01_t2_checking_kimi_unchecks_qwen(self, qapp, qtbot):
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        toasts = []
        signal_bus.toast_requested.connect(lambda msg, level: toasts.append(msg))
        try:
            w._use_qwen_chk.setChecked(True)
            assert w._use_qwen_chk.isChecked()
            w._use_kimi_chk.setChecked(True)
            assert not w._use_qwen_chk.isChecked(), "qwen should be unchecked by PW-01"
            assert w._use_kimi_chk.isChecked()
            assert any("Kimi substituiu Qwen" in t for t in toasts)
        finally:
            signal_bus.toast_requested.disconnect()

    def test_pw01_t3_checking_grok_unchecks_codex(self, qapp, qtbot):
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        toasts = []
        signal_bus.toast_requested.connect(lambda msg, level: toasts.append(msg))
        try:
            w._use_codex_chk.setChecked(True)
            assert w._use_codex_chk.isChecked()
            w._use_grok_chk.setChecked(True)
            assert not w._use_codex_chk.isChecked(), "codex should be unchecked by PW-01"
            assert w._use_grok_chk.isChecked()
            assert any("Grok substituiu Codex" in t for t in toasts)
        finally:
            signal_bus.toast_requested.disconnect()

    def test_pw01_t3_checking_codex_unchecks_grok(self, qapp, qtbot):
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        toasts = []
        signal_bus.toast_requested.connect(lambda msg, level: toasts.append(msg))
        try:
            w._use_grok_chk.setChecked(True)
            assert w._use_grok_chk.isChecked()
            w._use_codex_chk.setChecked(True)
            assert not w._use_grok_chk.isChecked(), "grok should be unchecked by PW-01"
            assert w._use_codex_chk.isChecked()
            assert any("Codex substituiu Grok" in t for t in toasts)
        finally:
            signal_bus.toast_requested.disconnect()

    def test_pw01_unchecking_allows_sibling(self, qapp):
        w = self._make_widget()
        w._use_qwen_chk.setChecked(True)
        assert w._use_qwen_chk.isChecked()
        w._use_qwen_chk.setChecked(False)
        w._use_kimi_chk.setChecked(True)
        assert w._use_kimi_chk.isChecked(), "kimi should be checkable after qwen unchecked"

    def test_worker_persistence_t2_qwen_survives_restore(self, qapp):
        from PySide6.QtCore import QSettings
        w = self._make_widget()
        w._use_qwen_chk.setChecked(True)
        w._persist_worker_selection()
        stg = QSettings("systemForge", "workflow-app")
        assert stg.value("worker/t2_selected") == "qwen"
        w2 = self._make_widget()
        assert w2._use_qwen_chk.isChecked()
        assert not w2._use_kimi_chk.isChecked()
        stg.remove("worker/t2_selected")
        stg.remove("worker/t3_selected")
        stg.sync()

    def test_worker_persistence_t3_grok_survives_restore(self, qapp):
        from PySide6.QtCore import QSettings
        w = self._make_widget()
        w._use_grok_chk.setChecked(True)
        w._persist_worker_selection()
        stg = QSettings("systemForge", "workflow-app")
        assert stg.value("worker/t3_selected") == "grok"
        w2 = self._make_widget()
        assert w2._use_grok_chk.isChecked()
        assert not w2._use_codex_chk.isChecked()
        stg.remove("worker/t2_selected")
        stg.remove("worker/t3_selected")
        stg.sync()

    def test_worker_persistence_empty_default(self, qapp):
        from PySide6.QtCore import QSettings
        stg = QSettings("systemForge", "workflow-app")
        stg.remove("worker/t2_selected")
        stg.remove("worker/t3_selected")
        stg.sync()
        w = self._make_widget()
        assert not w._use_kimi_chk.isChecked()
        assert not w._use_qwen_chk.isChecked()
        assert not w._use_codex_chk.isChecked()
        assert not w._use_grok_chk.isChecked()

    def test_main_worker_same_provider_toast(self, qapp, qtbot):
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        toasts = []
        signal_bus.toast_requested.connect(lambda msg, level: toasts.append(msg))
        try:
            w._main_qwen_radio.setChecked(True)
            w._use_qwen_chk.setChecked(True)
            assert any("qwen" in t and "Main" in t for t in toasts)
        finally:
            signal_bus.toast_requested.disconnect()


# ---------------------------------------------------------------------------
# Item 021: FlagsPanel e conjunto fechado de flags suportadas
# ---------------------------------------------------------------------------

class TestFlagsPanelSupportedFlags:
    """Testes do FlagsPanel (aba LLM Config) e do conjunto fechado."""

    def test_supported_flags_count_is_seven(self):
        from workflow_app.config.llm_flags import _SUPPORTED_MCP_FLAGS
        assert len(_SUPPORTED_MCP_FLAGS) == 7

    def test_supported_flags_literals(self):
        from workflow_app.config.llm_flags import _SUPPORTED_MCP_FLAGS
        expected = {"--opus", "--sonnet", "--codex", "--kimi", "--kimi-k3", "--qwen", "--grok"}
        assert _SUPPORTED_MCP_FLAGS == expected

    def test_flags_panel_has_exactly_supported_flags(self, qapp):
        from workflow_app.llm_config.flags_panel import FlagsPanel
        from workflow_app.config.llm_flags import _SUPPORTED_MCP_FLAGS
        panel = FlagsPanel()
        # Coletar testids dos checkboxes do painel.
        ui_flags = set()
        for flag, chk in panel._checkboxes.items():
            testid = chk.property("testid")
            assert testid is not None and testid.startswith("queue-chk-flag-")
            ui_flags.add(flag)
        # Bidirecional: toda flag da UI esta no conjunto fechado e vice-versa.
        assert ui_flags == _SUPPORTED_MCP_FLAGS

    def test_incompatible_flag_is_disabled_with_tooltip(self, qapp):
        from workflow_app.llm_config.flags_panel import FlagsPanel
        panel = FlagsPanel()
        # Main claude: todas habilitadas.
        panel.set_main_llm("claude")
        for flag, chk in panel._checkboxes.items():
            assert chk.isEnabled(), f"{flag} deveria estar habilitada sob Main claude"

        # Main kimi: --kimi e --kimi-k3 disabled (redundantes).
        panel.set_main_llm("kimi")
        assert not panel._checkboxes["--kimi"].isEnabled()
        assert "redundante" in panel._checkboxes["--kimi"].toolTip().lower() or "kimi" in panel._checkboxes["--kimi"].toolTip().lower()
        assert not panel._checkboxes["--kimi-k3"].isEnabled()
        # Demais habilitadas.
        assert panel._checkboxes["--codex"].isEnabled()
        assert panel._checkboxes["--qwen"].isEnabled()
        assert panel._checkboxes["--grok"].isEnabled()
        assert panel._checkboxes["--opus"].isEnabled()
        assert panel._checkboxes["--sonnet"].isEnabled()

        # Main codex: --codex disabled.
        panel.set_main_llm("codex")
        assert not panel._checkboxes["--codex"].isEnabled()
        assert panel._checkboxes["--kimi"].isEnabled()

        # Main qwen: --qwen disabled.
        panel.set_main_llm("qwen")
        assert not panel._checkboxes["--qwen"].isEnabled()
        assert panel._checkboxes["--kimi"].isEnabled()

        # Main grok: --grok disabled.
        panel.set_main_llm("grok")
        assert not panel._checkboxes["--grok"].isEnabled()
        assert panel._checkboxes["--codex"].isEnabled()

    def test_kill_switch_disables_all_flags(self, qapp, monkeypatch):
        import os
        monkeypatch.setenv("SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE", "0")
        # Reimport para capturar o env patchado.
        import importlib
        import workflow_app.config.feature_flags as ff_mod
        importlib.reload(ff_mod)
        try:
            from workflow_app.llm_config.flags_panel import FlagsPanel
            panel = FlagsPanel()
            panel.set_main_llm("claude")
            for flag, chk in panel._checkboxes.items():
                assert not chk.isEnabled(), f"{flag} deveria estar disabled pelo kill-switch"
                assert "kill-switch" in chk.toolTip().lower()
        finally:
            monkeypatch.delenv("SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE", raising=False)
            importlib.reload(ff_mod)

    def test_flags_panel_survives_rerun_after_main_change(self, qapp):
        from workflow_app.llm_config.flags_panel import FlagsPanel
        panel = FlagsPanel()
        # Claude -> Kimi -> Claude: estado correto em cada transicao.
        panel.set_main_llm("claude")
        assert all(chk.isEnabled() for chk in panel._checkboxes.values())

        panel.set_main_llm("kimi")
        assert not panel._checkboxes["--kimi"].isEnabled()
        assert panel._checkboxes["--codex"].isEnabled()

        panel.set_main_llm("claude")
        assert all(chk.isEnabled() for chk in panel._checkboxes.values())

    def test_checked_flags_returns_selected(self, qapp):
        from workflow_app.llm_config.flags_panel import FlagsPanel
        panel = FlagsPanel()
        panel.set_main_llm("claude")
        assert panel.checked_flags() == []
        panel._checkboxes["--kimi"].setChecked(True)
        assert "--kimi" in panel.checked_flags()
        panel._checkboxes["--codex"].setChecked(True)
        result = panel.checked_flags()
        assert "--kimi" in result
        assert "--codex" in result


# ---------------------------------------------------------------------------
# Item 023: Thinking/Execution split + persona filter (C-14, C-15, C-16, C-59)
# ---------------------------------------------------------------------------

_TE_PROBE = """\
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget as _W

app = QApplication.instance() or QApplication(sys.argv)

from workflow_app.main_window import MainWindow

win = MainWindow()

# Collect all testids in the window
all_testids = []
for w in [win, *win.findChildren(_W)]:
    tid = w.property("testid")
    if tid:
        all_testids.append(tid)

# Thinking group testids
thinking_tids = [
    t for t in all_testids if t.startswith("output-mcp-action-thinking")
]
# Execution group testids
execution_tids = [
    t for t in all_testids if t.startswith("output-mcp-action-execution")
]
# Persona filter bar
has_persona_filter = "output-mcp-persona-filter-bar" in all_testids

# Legacy buttons
has_legacy_main = "output-mcp-action-main" in all_testids
has_legacy_parallel = "output-mcp-action-parallel" in all_testids
has_legacy_dual = "output-mcp-action-dual" in all_testids

# Extract _TE_COMMANDS from closure of a Thinking/Execution button
te_commands = {}
for w in win.findChildren(_W):
    tid = w.property("testid")
    cmd = w.property("te_command")
    if tid and cmd and tid.startswith("output-mcp-action-"):
        te_commands[tid] = cmd
    # Also check QCheckBox (persona filter bar is QTabBar, buttons are QPushButton)
    from PySide6.QtWidgets import QPushButton
    if isinstance(w, QPushButton):
        tid2 = w.property("testid")
        cmd2 = w.property("te_command")
        if tid2 and cmd2 and tid2.startswith("output-mcp-action-"):
            te_commands[tid2] = cmd2

# Persona checkbox categories
from PySide6.QtWidgets import QCheckBox
persona_cats = {}
for w in win.findChildren(QCheckBox):
    tid = w.property("testid")
    cat = w.property("persona_category")
    if tid and str(tid).startswith("output-mcp-persona-") and cat:
        persona_cats[str(tid)] = str(cat)

print(json.dumps({
    "thinking_tids": sorted(thinking_tids),
    "execution_tids": sorted(execution_tids),
    "has_persona_filter": has_persona_filter,
    "has_legacy_main": has_legacy_main,
    "has_legacy_parallel": has_legacy_parallel,
    "has_legacy_dual": has_legacy_dual,
    "te_commands": te_commands,
    "persona_cats": persona_cats,
}))
"""


def _run_te_probe(env_override: dict[str, str] | None = None) -> dict:
    """Run the TE probe in a subprocess with the given env overrides."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    if env_override:
        env.update(env_override)
    if env_override is None or _FLAG_NAME not in env_override:
        env.pop(_FLAG_NAME, None)

    result = subprocess.run(
        [sys.executable, "-c", _TE_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"TE probe failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip().split("\n")[-1])


class TestThinkingExecutionFlagEnabled:
    """Item 023: Thinking/Execution split with SF_LLM_CONFIG_V2=1."""

    def test_thinking_group_has_3_buttons(self):
        """C-14: Thinking group has exactly 3 provider buttons."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        expected = sorted([
            "output-mcp-action-thinking",
            "output-mcp-action-thinking-claude",
            "output-mcp-action-thinking-codex",
            "output-mcp-action-thinking-kimi",
        ])
        assert data["thinking_tids"] == expected, (
            f"Expected {expected}, got {data['thinking_tids']}"
        )

    def test_execution_group_has_5_buttons(self):
        """C-14: Execution group has exactly 5 provider buttons."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        expected = sorted([
            "output-mcp-action-execution",
            "output-mcp-action-execution-claude",
            "output-mcp-action-execution-codex",
            "output-mcp-action-execution-kimi",
            "output-mcp-action-execution-grok",
            "output-mcp-action-execution-qwen",
        ])
        assert data["execution_tids"] == expected, (
            f"Expected {expected}, got {data['execution_tids']}"
        )

    def test_fixed_commands_in_te_commands(self):
        """C-14: Each button has a fixed command independent of Main LLM."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        cmds = data["te_commands"]
        assert cmds.get("output-mcp-action-thinking-claude") == (
            "claude --model opus --effort high"
        )
        assert cmds.get("output-mcp-action-thinking-codex") == "/mcp:codex"
        assert cmds.get("output-mcp-action-thinking-kimi") == "/mcp:kimi-k3"
        assert cmds.get("output-mcp-action-execution-claude") == (
            "claude --model sonnet --effort standard"
        )
        assert cmds.get("output-mcp-action-execution-codex") == "/mcp:codex"
        assert cmds.get("output-mcp-action-execution-kimi") == "/mcp:kimi"
        assert cmds.get("output-mcp-action-execution-grok") == "/mcp:grok"
        assert cmds.get("output-mcp-action-execution-qwen") == "/mcp:qwen"

    def test_no_legacy_skill_pills_in_commands(self):
        """C-15: Old skill CLI pills are NOT in the command map."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        all_cmds = list(data["te_commands"].values())
        for old in (
            "/skill:claude", "/skill:codex", "/skill:dual",
            "Use skill-claude", "Use skill-codex", "Use skill-dual",
        ):
            assert old not in all_cmds, (
                f"Legacy skill pill '{old}' should not be in TE commands"
            )

    def test_no_legacy_buttons_when_flag_enabled(self):
        """Kill-switch: legacy Main/Parallel/Dual absent when flag=1."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        assert not data["has_legacy_main"]
        assert not data["has_legacy_parallel"]
        assert not data["has_legacy_dual"]

    def test_persona_filter_bar_exists(self):
        """C-16: output-mcp-persona-filter-bar exists with flag=1."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        assert data["has_persona_filter"], (
            "output-mcp-persona-filter-bar should exist with flag=1"
        )

    def test_persona_checkboxes_have_categories(self):
        """C-16: MCP persona checkboxes have persona_category property."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        cats = data["persona_cats"]
        assert len(cats) == 16, f"Expected 16 personas, got {len(cats)}"
        assert cats["output-mcp-persona-search-in"] == "Research"
        assert cats["output-mcp-persona-criar-task"] == "Build"
        assert cats["output-mcp-persona-delegador"] == "Plan"
        assert cats["output-mcp-persona-ux-ui"] == "Design"
        assert cats["output-mcp-persona-controversial"] == "Review"
        assert cats["output-mcp-persona-performance-engineer"] == "specialists"


class TestThinkingExecutionClaudeLocal:
    """C-59: Claude buttons paste explicit local invocation (no shell alias)."""

    def test_thinking_claude_command_has_model_and_effort(self):
        """C-59: Thinking Claude = 'claude --model opus --effort high'."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        cmd = data["te_commands"].get("output-mcp-action-thinking-claude", "")
        assert "claude" in cmd
        assert "--model opus" in cmd
        assert "--effort high" in cmd

    def test_execution_claude_command_has_model_and_effort(self):
        """C-59: Execution Claude = 'claude --model sonnet --effort standard'."""
        data = _run_te_probe({_FLAG_NAME: "1"})
        cmd = data["te_commands"].get("output-mcp-action-execution-claude", "")
        assert "claude" in cmd
        assert "--model sonnet" in cmd
        assert "--effort standard" in cmd

    def test_claude_commands_with_empty_shell_env(self):
        """C-59: Claude commands work with empty shell environment."""
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env[_FLAG_NAME] = "1"
        env.pop("HOME", None)
        env.pop("ZDOTDIR", None)
        env.pop("XDG_CONFIG_HOME", None)

        result = subprocess.run(
            [sys.executable, "-c", _TE_PROBE],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_WORKFLOW_APP_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Probe failed with empty shell env:\n{result.stderr}"
        )
        data = json.loads(result.stdout.strip().split("\n")[-1])
        th_cmd = data["te_commands"].get("output-mcp-action-thinking-claude", "")
        ex_cmd = data["te_commands"].get("output-mcp-action-execution-claude", "")
        assert "claude --model opus --effort high" in th_cmd
        assert "claude --model sonnet --effort standard" in ex_cmd


class TestThinkingExecutionFlagAbsent:
    """Kill-switch: flag absent = legacy layout (G3)."""

    def test_legacy_buttons_present_when_flag_absent(self):
        """Flag absent: Main/Parallel/Dual present, no Thinking/Execution."""
        data = _run_te_probe()
        assert data["has_legacy_main"]
        assert data["has_legacy_parallel"]
        assert data["has_legacy_dual"]
        assert data["thinking_tids"] == []
        assert data["execution_tids"] == []

    def test_persona_filter_absent_when_flag_missing(self):
        """Flag absent: persona filter bar does NOT exist."""
        data = _run_te_probe()
        assert not data["has_persona_filter"]


class TestThinkingExecutionFlagOff:
    """Kill-switch: flag='0' = legacy layout (G3)."""

    def test_legacy_buttons_present_when_flag_off(self):
        """Flag='0': Main/Parallel/Dual present, no Thinking/Execution."""
        data = _run_te_probe({_FLAG_NAME: "0"})
        assert data["has_legacy_main"]
        assert data["has_legacy_parallel"]
        assert data["has_legacy_dual"]
        assert data["thinking_tids"] == []
        assert data["execution_tids"] == []

    def test_persona_filter_absent_when_flag_off(self):
        """Flag='0': persona filter bar does NOT exist."""
        data = _run_te_probe({_FLAG_NAME: "0"})
        assert not data["has_persona_filter"]


class TestPersonaFilterBar:
    """C-16: Persona filter bar in MCP section."""

    def test_persona_filter_does_not_crash_with_empty_list(self, qapp):
        """C-16: Filtering to a category with few personas shows empty, no crash."""
        from workflow_app.main_window import MainWindow
        win = MainWindow()
        bar = getattr(win, "_mcp_persona_filter_bar", None)
        if bar is None:
            pytest.skip("MCP persona filter bar not created (flag absent)")
        # Set to last category (specialists) - has only 1 persona
        bar.setCurrentIndex(bar.count() - 1)
        win._apply_mcp_persona_filter()
        # Count widgets that the filter kept visible (hidden=False).
        not_hidden = [
            c for c in win._mcp_persona_checkboxes
            if not c.isHidden()
        ]
        # specialists has performance-engineer = 1
        assert len(not_hidden) >= 1

    def test_persona_filter_all_shows_everyone(self, qapp):
        """C-16: 'All' tab shows all 16 personas (none hidden)."""
        from workflow_app.main_window import MainWindow
        win = MainWindow()
        bar = getattr(win, "_mcp_persona_filter_bar", None)
        if bar is None:
            pytest.skip("MCP persona filter bar not created (flag absent)")
        bar.setCurrentIndex(0)  # All
        win._apply_mcp_persona_filter()
        not_hidden = [
            c for c in win._mcp_persona_checkboxes
            if not c.isHidden()
        ]
        assert len(not_hidden) == 16


# ---------------------------------------------------------------------------
# Item 025: Grok spike NAO vaza em superficie publica (C-58, G6)
# ---------------------------------------------------------------------------


class TestGrokPublicExposure:
    """Item 026: Grok expoe em UI publica SOMENTE quando feature gate ligado.

    A promocao publica (D-30) adiciona _main_grok_radio no CommandQueueWidget,
    mas a visibilidade e condicionada ao kill-switch SF_GROK_SPIKE. Com gate
    desligado (default), o radio existe mas esta oculto. Com gate ligado,
    o radio fica visivel e selecionavel.

    Testes de exposicao condicionada substituem os testes de ausencia do
    item 025 (C-58). O teste grok_spike_gate_default_off e preservado.
    """

    def test_grok_spike_gate_default_off(self):
        """Feature gate SF_GROK_SPIKE desligado por default."""
        from workflow_app.config.feature_flags import grok_spike_enabled
        assert grok_spike_enabled() is False

    def test_grok_spike_not_active_when_gate_off(self):
        """is_grok_spike_active() retorna False com gate desligado."""
        from workflow_app.llm_config.grok_spike import is_grok_spike_active
        assert is_grok_spike_active() is False

    def test_grok_radio_hidden_when_gate_off(self, qapp):
        """Com gate desligado, _main_grok_radio existe mas esta oculto."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        w = CommandQueueWidget()
        assert hasattr(w, "_main_grok_radio"), (
            "_main_grok_radio deve existir apos item 026 (promocao publica)"
        )
        assert not w._main_grok_radio.isVisible(), (
            "_main_grok_radio visivel com gate desligado - "
            "violacao do kill-switch SF_GROK_SPIKE"
        )
        assert w._main_grok_radio.property("testid") == "queue-radio-main-grok"

    def test_grok_not_exposed_when_gate_off(self, qapp):
        """Com gate desligado, Grok nao e selecionado como Main LLM ativo."""
        from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
        w = CommandQueueWidget()
        # Radio grok existe mas esta oculto e nao checked
        assert not w._main_grok_radio.isChecked()
        # Main LLM resolvido nao e grok quando gate esta desligado
        main_llm = w.current_main_llm()
        assert main_llm != "grok", (
            f"current_main_llm retornou 'grok' com gate desligado - "
            f"valor atual: {main_llm}"
        )
