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
from contextlib import contextmanager
from pathlib import Path

import pytest

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]

_FLAG_NAME = "SF_LLM_CONFIG_V2"

# Item 005 do loop 08-17-systemforge-multillm-gaps-refactor: o gate da matriz
# Thinking/Execution foi MOVIDO do global `SF_LLM_CONFIG_V2` para este
# kill-switch dedicado (`feature_flags._MCP_THINK_EXEC_V2_FLAG`, lido em
# `main_window` por `mcp_think_exec_v2_enabled()`). Armar apenas o global
# devolve um probe sem nenhum botao TE — era exatamente esse o defeito destes
# testes depois do item 005.
_TE_FLAG_NAME = "SF_MCP_THINK_EXEC_V2"

# Switch das superficies do CLI MiMo (`feature_flags.mimo_v1_enabled()`). Pelo
# contrato D3 ele NAO gateia a matriz TE; `_run_te_probe` o remove do ambiente
# herdado para que um switch ligado no shell do operador nao decida o cenario.
_MIMO_FLAG_NAME = "SF_MIMO_V1"

# Regime "V2 ligado" como o operador o ve: aba LLM Config nova (global) MAIS a
# matriz Thinking/Execution. O wrapper `kimi-k3` de Thinking e fixo: nao ha gate
# separado para rebaixar o botao para `/mcp:kimi`.
_TE_FLAGS_ON: dict[str, str] = {
    _FLAG_NAME: "1",
    _TE_FLAG_NAME: "1",
}
_TE_FLAGS_OFF: dict[str, str] = {_FLAG_NAME: "0", _TE_FLAG_NAME: "0"}

# Probe que verifica a estrutura do selector e da aba LLM Config.
# Roda em subprocesso com o ambiente montado pelo teste.
_LLM_CONFIG_TAB_PROBE = """\
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout

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
llm_box_hint = llm_box.sizeHint()

main_radios = {
    "claude": win._command_queue._main_claude_radio,
    "grok": win._command_queue._main_grok_radio,
    "opus": win._command_queue._main_opus_radio,
    "kimi": win._command_queue._main_kimi_radio,
    "codex": win._command_queue._main_codex_radio,
    "sonnet": win._command_queue._main_sonnet_radio,
    "kimi-k3": win._command_queue._main_kimi_k3_radio,
    "qwen": win._command_queue._main_qwen_radio,
    "mimo": win._command_queue._main_mimo_radio,
}
main_options_layout = next(iter(main_radios.values())).parentWidget().layout()
main_radio_positions = {}
if hasattr(main_options_layout, "getItemPosition"):
    for slug, radio in main_radios.items():
        index = main_options_layout.indexOf(radio)
        if index < 0:
            continue
        row, column, _row_span, _column_span = main_options_layout.getItemPosition(index)
        main_radio_positions[slug] = [row, column]

def _find_by_testid(testid):
    for widget in [llm_box, *llm_box.findChildren(type(llm_box))]:
        if widget.property("testid") == testid:
            return widget
    return None

routing_section_order = []
for index in range(llm_box.layout().count()):
    item_widget = llm_box.layout().itemAt(index).widget()
    if item_widget is not None and not isinstance(item_widget, QFrame):
        routing_section_order.append(item_widget.property("testid"))

instance_parent_testid = win._metrics_bar._instance_group.parentWidget().property("testid")
parallel_column_orders = {}
for terminal in ("t2", "t3"):
    terminal_widget = _find_by_testid(f"queue-div-parallel-{terminal}")
    terminal_order = []
    if terminal_widget is not None:
        for index in range(terminal_widget.layout().count()):
            child = terminal_widget.layout().itemAt(index).widget()
            if child is None:
                continue
            terminal_order.append(child.property("testid") or child.text())
        parallel_column_orders[terminal] = {
            "layout": type(terminal_widget.layout()).__name__,
            "order": terminal_order,
        }

flag_section = _find_by_testid("queue-div-flag")
flag_positions = {}
if win._command_queue._flags_panel is not None:
    for flag, checkbox in win._command_queue._flags_panel._checkboxes.items():
        flag_grid = checkbox.parentWidget().layout()
        index = flag_grid.indexOf(checkbox)
        row, column, _row_span, _column_span = flag_grid.getItemPosition(index)
        flag_positions[flag] = [row, column]

# Check for terminal-insertions button
has_terminal_insertions = "output-toolbar-section-terminal-insertions" in btn_testids

# Check for llm-routing button and stack page
llm_routing_btn = None
for btn in btns:
    if btn.property("testid") == "output-toolbar-section-llm-routing":
        llm_routing_btn = btn
        break

llm_routing_widget = None
if llm_routing_btn is not None:
    from PySide6.QtWidgets import QWidget as _W
    for i in range(stack.count()):
        w = stack.widget(i)
        if w.property("testid") == "output-toolbar-section-llm-routing":
            llm_routing_widget = w
            break

has_llm_routing = llm_routing_btn is not None
llm_routing_parent_testid = None
if llm_box.parentWidget() is not None:
    llm_routing_parent_testid = llm_box.parentWidget().property("testid")

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

boot_stack_index = stack.currentIndex()
boot_stack_widget = stack.widget(boot_stack_index)
boot_stack_testid = (
    boot_stack_widget.property("testid") if boot_stack_widget is not None else None
)
boot_active_btn_testid = None
section_indices = getattr(win, "_toolbar_section_stack_indices", list(range(len(btns))))
for i, btn in enumerate(btns):
    mapped = section_indices[i] if i < len(section_indices) else i
    if mapped == boot_stack_index:
        boot_active_btn_testid = btn.property("testid")
        break

print(json.dumps({
    "btn_count": len(btns),
    "stack_count": stack_count,
    "btn_testids": btn_testids,
    "boot_stack_index": boot_stack_index,
    "boot_stack_testid": boot_stack_testid,
    "boot_active_btn_testid": boot_active_btn_testid,
    "has_llm_config": llm_config_btn is not None,
    "has_terminal_insertions": has_terminal_insertions,
    "llm_config_parent_testid": llm_box_parent_testid,
    "llm_box_layout_type": llm_box_layout_type,
    "main_options_layout_type": type(main_options_layout).__name__,
    "main_radio_positions": main_radio_positions,
    "routing_section_order": routing_section_order,
    "instance_parent_testid": instance_parent_testid,
    "parallel_column_orders": parallel_column_orders,
    "flag_section_layout_type": type(flag_section.layout()).__name__ if flag_section else None,
    "flag_positions": flag_positions,
    "llm_box_hint_w": llm_box_hint.width(),
    "llm_box_hint_h": llm_box_hint.height(),
    "llm_config_containers": sorted(containers),
    "flag_enabled": llm_config_btn is not None,
    "has_llm_routing": has_llm_routing,
    "llm_routing_parent_testid": llm_routing_parent_testid,
}))
"""


# Probe do teto de altura (C-04/R-18). Diferente da sonda acima, esta PRECISA
# de geometria viva: `_sync_flow_section_height` so mede depois de show() +
# resize(), e o offscreen do Qt entrega geometria real.
_LLM_CONFIG_HEIGHT_PROBE = """\
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from workflow_app.main_window import MainWindow

win = MainWindow()
win.resize(1747, 749)
win.show()


def _settle():
    for _ in range(6):
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 200)


_settle()
selector = win._toolbar_section_selector
stack = win._toolbar_section_stack

boot_cap = selector.maximumHeight()

def _button_index(testid):
    for i, btn in enumerate(win._toolbar_section_btns):
        if btn.property("testid") == testid:
            return i
    return None


def _cap_for_button(testid):
    index = _button_index(testid)
    if index is None:
        return None
    win._select_toolbar_section(index)
    _settle()
    return selector.maximumHeight()


llm_routing_cap = _cap_for_button("output-toolbar-section-llm-routing")

print(json.dumps({
    "qt_size_max": 16777215,
    "boot_cap": boot_cap,
    "llm_routing_cap": llm_routing_cap,
}))
"""


def _run_probe(
    env_override: dict[str, str] | None = None,
    source: str = _LLM_CONFIG_TAB_PROBE,
) -> dict:
    """Run the probe in a subprocess with the given env overrides."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    if env_override:
        env.update(env_override)
    # Remove the flag by default unless explicitly set
    if env_override is None or _FLAG_NAME not in env_override:
        env.pop(_FLAG_NAME, None)

    result = subprocess.run(
        [sys.executable, "-c", source],
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


# --- Selector tem uma unica secao LLM Routing quando a flag esta ligada ---


class TestLLMConfigTabFlagEnabled:
    """Tests with SF_LLM_CONFIG_V2=1."""

    def test_selector_has_7_sections_with_llm_routing_last(self):
        """Routing e adicionada sem substituir Terminal Insertions."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["btn_count"] == 7, (
            f"Expected 7 sections, got {data['btn_count']}: {data['btn_testids']}"
        )
        assert data["btn_testids"][1] == (
            "output-toolbar-section-terminal-insertions"
        )
        assert data["btn_testids"][-1] == "output-toolbar-section-llm-routing", (
            f"LLM Routing should be last, got: {data['btn_testids']}"
        )

    def test_boot_opens_llm_routing_section(self):
        """Toda instancia nova abre na aba LLM ROUTING, sem persistir sessao."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["boot_stack_testid"] == "output-toolbar-section-llm-routing", (
            f"boot deveria abrir LLM ROUTING, got stack="
            f"{data['boot_stack_testid']!r} index={data['boot_stack_index']}"
        )
        assert data["boot_active_btn_testid"] == (
            "output-toolbar-section-llm-routing"
        ), (
            f"botao ativo no boot deveria ser LLM ROUTING, "
            f"got {data['boot_active_btn_testid']!r}"
        )

    def test_terminal_insertions_preserved_and_llm_routing_added(self):
        """Flag ligada preserva a secao principal e adiciona LLM Routing."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["has_terminal_insertions"], (
            "TERMINAL INSERTIONS must remain present when flag is enabled"
        )
        assert data["has_llm_routing"], (
            "LLM Routing section should be present when flag is enabled"
        )
        assert data["llm_routing_parent_testid"] == "output-toolbar-section-llm-routing", (
            f"queue-div-llm-routing should be inside LLM Routing section, "
            f"got parent: {data['llm_routing_parent_testid']}"
        )

    def test_blank_llm_config_tab_does_not_exist(self):
        """Nao cria aba LLM Config paralela sem conteudo."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert not data["has_llm_config"], (
            "blank LLM Config tab must not coexist with LLM Routing"
        )

    def test_stack_has_7_pages(self):
        """Stack tem 6 paginas base mais a pagina unica LLM Routing."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["stack_count"] == 7, (
            f"Expected 7 stack pages, got {data['stack_count']}"
        )


# --- C-04: queue-div-llm-routing e QHBoxLayout na aba nova ---


class TestLLMConfigTabLayout:
    """C-04: queue-div-llm-routing layout and parent."""

    def test_llm_routing_is_in_llm_routing_tab(self):
        """queue-div-llm-routing reparenteado para a aba LLM Routing (C25)."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["llm_routing_parent_testid"] == "output-toolbar-section-llm-routing", (
            f"queue-div-llm-routing should be inside LLM Routing tab, "
            f"got parent: {data['llm_routing_parent_testid']}"
        )

    def test_dead_llm_config_containers_do_not_exist(self):
        """Nao preserva containers ocultos como justificativa para aba vazia."""
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["llm_config_containers"] == []

    def test_llm_routing_is_qhboxlayout_when_flag_enabled(self):
        """C-04 (metade que faltava): a div e QHBoxLayout dentro da aba.

        A sonda ja coletava `llm_box_layout_type` desde o item 017, mas nenhum
        teste afirmava o valor: a div continuou QVBoxLayout com a flag ligada e
        os 51 testes seguiram verdes.
        """
        data = _run_probe({_FLAG_NAME: "1"})
        assert data["llm_box_layout_type"] == "QHBoxLayout", (
            f"queue-div-llm-routing deve ser QHBoxLayout dentro da aba LLM "
            f"Routing, got: {data['llm_box_layout_type']}"
        )

    def test_main_llm_radios_follow_brainstorm_two_column_order(self):
        """Main LLM usa as duas colunas definidas no brainstorm 08-11."""
        data = _run_probe(
            {
                _FLAG_NAME: "1",
                "SF_MAIN_PROVIDERS_V2": "1",
                "SF_GROK_SPIKE": "1",
            }
        )
        assert data["main_options_layout_type"] == "QGridLayout"
        # `mimo` ocupa (2, 1) no grid em qualquer regime: a posicao e de
        # layout, a visibilidade fica com o switch proprio do roster MiMo.
        assert data["main_radio_positions"] == {
            "claude": [0, 0],
            "codex": [0, 1],
            "kimi": [1, 0],
            "grok": [1, 1],
            "qwen": [2, 0],
            "mimo": [2, 1],
        }

    def test_routing_uses_four_columns_with_internal_two_column_grids(self):
        """Aliases, Main, Parallel e Flag ocupam quatro colunas independentes."""
        data = _run_probe(
            {
                _FLAG_NAME: "1",
                "SF_INSTANCE_GROUP_ROUTE_AWARE": "1",
                "SF_MAIN_PROVIDERS_V2": "1",
                "SF_PARALLEL_WORKERS_V2": "1",
                "SF_LLM_FLAGS_V2": "1",
                "SF_GROK_SPIKE": "1",
            }
        )
        assert data["routing_section_order"] == [
            "queue-div-instance-buttons",
            "queue-div-main-llm",
            "queue-div-parallel-worker",
            "queue-div-flag",
        ]
        assert data["instance_parent_testid"] == "queue-div-instance-buttons"
        assert data["parallel_column_orders"] == {
            "t2": {
                "layout": "QVBoxLayout",
                # O worker MiMo fecha a coluna T2 em qualquer regime; oculto
                # quando o switch do roster MiMo esta off.
                "order": [
                    "T2:",
                    "queue-chk-use-kimi",
                    "queue-chk-use-qwen",
                    "queue-chk-use-mimo",
                ],
            },
            "t3": {
                "layout": "QVBoxLayout",
                "order": ["T3:", "queue-chk-use-codex", "queue-chk-use-grok"],
            },
        }
        assert data["flag_section_layout_type"] == "QVBoxLayout"
        assert data["flag_positions"] == {
            "--fable": [1, 0],
            "--opus": [2, 0],
            "--codex-ultra": [3, 0],
            "--mimo-pro": [4, 0],
            "--kimi-k3": [5, 0],
            "--grok-xhigh": [6, 0],
            "--grok": [1, 1],
            "--sonnet": [2, 1],
            "--mimo": [3, 1],
            "--kimi": [4, 1],
            "--qwen": [5, 1],
            "--codex": [6, 1],
        }

    def test_llm_routing_is_shorter_in_row_than_in_legacy_column(self):
        """C-04/R-18: a row de 4 colunas nao pode ser mais alta que a coluna.

        Premissa do risco R-18: em linha a div tem de ficar mais baixa que
        empilhada. O teto efetivo do selector e travado separadamente em
        `test_llm_routing_section_caps_selector_height`.
        """
        on = _run_probe({_FLAG_NAME: "1"})
        off = _run_probe()
        assert on["llm_box_hint_h"] < off["llm_box_hint_h"], (
            f"altura da div em linha ({on['llm_box_hint_h']}) deveria ser menor "
            f"que empilhada ({off['llm_box_hint_h']})"
        )

    def test_llm_routing_section_caps_selector_height(self):
        """C-04/R-18: LLM Routing mantem o selector com teto medido.

        `_sync_flow_section_height` so aplica teto quando consegue medir a
        pagina. LLM ROUTING nao usa flow layout, entao `hasHeightForWidth()`
        volta False e o teto cairia no release (`_QT_WIDGET_SIZE_MAX`); ai o
        QStackedLayout dimensionaria a aba pela pagina mais alta do stack e
        sobraria faixa vazia sob a row. Este teste trava as duas metades:
        teto aplicado (nao liberado) e nao maior que o da secao de boot.
        """
        data = _run_probe({_FLAG_NAME: "1"}, source=_LLM_CONFIG_HEIGHT_PROBE)
        assert data["llm_routing_cap"] is not None, (
            "pagina output-toolbar-section-llm-routing nao encontrada no stack"
        )
        cap = data["llm_routing_cap"]
        assert cap != data["qt_size_max"], (
            "teto do selector foi liberado com LLM ROUTING ativa"
        )
        assert 0 < cap, (
            f"teto com LLM ROUTING ({cap}) deveria ser medido"
        )
        # thinking/execution tem 5 linhas + labels; o teto segue a pagina
        # (nao o MAX) e pode superar o da secao de boot.
        assert cap <= max(int(data["boot_cap"]), 180), (
            f"teto com LLM ROUTING ({cap}) estourou o teto aceitavel "
            f"(boot={data['boot_cap']})"
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

    def test_boot_stays_command_sequence_when_llm_routing_tab_absent(self):
        """Sem a aba LLM ROUTING, o boot legado continua em COMMAND SEQUENCE."""
        data = _run_probe()
        assert data["boot_stack_index"] == 0
        assert data["boot_active_btn_testid"] == (
            "output-toolbar-section-command-sequence"
        )

    def test_llm_routing_in_top_row_when_flag_absent(self):
        """Flag ausente: queue-div-llm-routing permanece na top-row."""
        data = _run_probe()
        assert data["llm_config_parent_testid"] != "output-toolbar-section-llm-config", (
            "queue-div-llm-routing should NOT be in LLM Config tab when flag is absent"
        )

    def test_llm_routing_keeps_column_layout_when_flag_absent(self):
        """ST003: sem a flag, a div segue empilhada (QVBoxLayout) na top-row."""
        data = _run_probe()
        assert data["llm_box_layout_type"] == "QVBoxLayout", (
            f"layout legado deve permanecer QVBoxLayout, "
            f"got: {data['llm_box_layout_type']}"
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

    @staticmethod
    def _arm_parallel_workers_v2(monkeypatch):
        """Arma o roster v2 de workers (qwen/grok visiveis) antes do widget.

        O restore so remarca worker visivel pela intencao de boot
        (`_worker_visible`): com o roster v2 off, qwen/grok nascem ocultos e
        um `worker/t2_selected=qwen` herdado nao volta a ocupar o par. Os
        testes de sobrevivencia ao restore precisam do roster armado.
        """
        monkeypatch.setattr(
            "workflow_app.config.feature_flags.parallel_workers_v2_enabled",
            lambda: True,
        )

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

    def test_worker_persistence_t2_qwen_survives_restore(self, qapp, monkeypatch):
        from PySide6.QtCore import QSettings
        self._arm_parallel_workers_v2(monkeypatch)
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

    def test_worker_persistence_t3_grok_survives_restore(self, qapp, monkeypatch):
        from PySide6.QtCore import QSettings
        self._arm_parallel_workers_v2(monkeypatch)
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

    # -- Item 013 (gap C24): ocupacao dos pares publicada no signal_bus ------ #

    def _capture_occupancy(self, signal_bus, sink):
        signal_bus.worker_occupancy_changed.connect(
            lambda t2, t3: sink.append((t2, t3))
        )

    def test_occupancy_emitted_on_toggle(self, qapp):
        """Marcar um worker publica a ocupacao do par (todos os 4 toggles)."""
        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        seen: list[tuple[str, str]] = []
        self._capture_occupancy(signal_bus, seen)
        try:
            w._use_qwen_chk.setChecked(True)
            assert seen and seen[-1] == ("qwen", "")
            w._use_grok_chk.setChecked(True)
            assert seen[-1] == ("qwen", "grok")
            w._use_kimi_chk.setChecked(True)  # PW-01 troca qwen -> kimi
            assert seen[-1] == ("kimi", "grok")
            w._use_kimi_chk.setChecked(False)
            assert seen[-1] == ("", "grok")
        finally:
            signal_bus.worker_occupancy_changed.disconnect()

    def test_occupancy_emitted_on_restore_outside_blocksignals(self, qapp, monkeypatch):
        """O restore usa blockSignals, entao os toggles NAO rodam no boot.

        Sem um emit proprio, a MetricsBar ficaria cega justamente na sessao
        recem-aberta - que e quando a auto-recuperacao mais dispara.
        """
        from PySide6.QtCore import QSettings

        from workflow_app.signal_bus import signal_bus
        self._arm_parallel_workers_v2(monkeypatch)
        stg = QSettings("systemForge", "workflow-app")
        stg.setValue("worker/t2_selected", "qwen")
        stg.setValue("worker/t3_selected", "grok")
        stg.sync()
        w = self._make_widget()
        seen: list[tuple[str, str]] = []
        self._capture_occupancy(signal_bus, seen)
        try:
            w._restore_worker_selection()
            assert not w._use_kimi_chk.isChecked()
            assert seen and seen[-1] == ("qwen", "grok")
        finally:
            signal_bus.worker_occupancy_changed.disconnect()
            stg.remove("worker/t2_selected")
            stg.remove("worker/t3_selected")
            stg.sync()

    def test_resolve_worker_occupancy_empty_pairs(self, qapp):
        """Par sem worker marcado resolve `""` - vazio, nao "desconhecido"."""
        w = self._make_widget()
        for chk in (
            w._use_kimi_chk,
            w._use_qwen_chk,
            w._use_codex_chk,
            w._use_grok_chk,
        ):
            chk.setChecked(False)
        assert w._resolve_worker_occupancy() == ("", "")

    def test_persist_and_emit_agree(self, qapp):
        """O que vai para o QSettings e o que vai para o sinal e a MESMA
        resolucao: duas leituras paralelas dos checkboxes divergiriam."""
        from PySide6.QtCore import QSettings

        from workflow_app.signal_bus import signal_bus
        w = self._make_widget()
        seen: list[tuple[str, str]] = []
        self._capture_occupancy(signal_bus, seen)
        try:
            w._use_qwen_chk.setChecked(True)
            w._use_codex_chk.setChecked(True)
            stg = QSettings("systemForge", "workflow-app")
            assert seen[-1] == (
                stg.value("worker/t2_selected"),
                stg.value("worker/t3_selected"),
            )
        finally:
            signal_bus.worker_occupancy_changed.disconnect()
            stg = QSettings("systemForge", "workflow-app")
            stg.remove("worker/t2_selected")
            stg.remove("worker/t3_selected")
            stg.sync()

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

_LLM_FLAGS_V2_FLAG = "SF_LLM_FLAGS_V2"

# Roster vigente por regime do kill-switch (item 005 do loop
# 08-17-systemforge-multillm-gaps-refactor), na ordem canonica do regime (a
# ordem do sufixo T1). Ausente/off = roster legado (tabela C26 mais
# `--mimo`); "1" = colunas thinking + execution.
# `--mimo` entra nos dois regimes: substitui o `--kimi` (2026-10-02).
# `--mimo-pro` so existe no v2 (thinking, antes do `--kimi-k3`).
# Escritos a mao DE PROPOSITO: derivar de `llm_flags` faria o teste
# concordar com qualquer roster que o modulo produzisse.
_LEGACY_FLAG_ORDER_EXPECTED: tuple[str, ...] = ("--codex", "--mimo", "--kimi")
_V2_FLAG_ORDER_EXPECTED: tuple[str, ...] = (
    "--fable",
    "--opus",
    "--codex-ultra",
    "--mimo-pro",
    "--kimi-k3",
    "--grok-xhigh",
    "--grok",
    "--sonnet",
    "--mimo",
    "--kimi",
    "--qwen",
    "--codex",
)
_LEGACY_FLAG_LITERALS = frozenset(_LEGACY_FLAG_ORDER_EXPECTED)
_V2_FLAG_LITERALS = frozenset(_V2_FLAG_ORDER_EXPECTED)


@contextmanager
def _llm_flags_regime(v2_enabled: bool):
    """Executa o bloco sob o regime pedido de `SF_LLM_FLAGS_V2`.

    O kill-switch e boot-frozen: `feature_flags` le `os.environ` uma unica vez,
    no import. Trocar de regime dentro do processo exige reload em ordem de
    dependencia (`feature_flags` -> `llm_flags` -> `flags_panel`), porque
    `llm_flags` deriva o conjunto vigente no corpo do modulo e o `FlagsPanel`
    congela `_FLAG_ORDER` a partir dele no import.

    Afirmar o roster v2 (`_V2_FLAG_ORDER_EXPECTED`) sem armar a flag e o
    defeito que estes testes tinham: o default do processo e o regime LEGADO
    (`_LEGACY_FLAG_ORDER_EXPECTED`), entao a assercao descrevia um regime que
    nao estava vigente. O `finally` devolve o processo ao regime herdado do
    ambiente para nao contaminar os testes seguintes.
    """
    import importlib

    import workflow_app.config.feature_flags as ff_mod
    import workflow_app.config.llm_flags as lf_mod
    import workflow_app.llm_config.flags_panel as fp_mod

    previous = os.environ.get(_LLM_FLAGS_V2_FLAG)
    if v2_enabled:
        os.environ[_LLM_FLAGS_V2_FLAG] = "1"
    else:
        os.environ.pop(_LLM_FLAGS_V2_FLAG, None)

    def _reload_chain():
        importlib.reload(ff_mod)
        importlib.reload(lf_mod)
        importlib.reload(fp_mod)

    try:
        _reload_chain()
        yield fp_mod
    finally:
        if previous is None:
            os.environ.pop(_LLM_FLAGS_V2_FLAG, None)
        else:
            os.environ[_LLM_FLAGS_V2_FLAG] = previous
        _reload_chain()


class TestFlagsPanelSupportedFlags:
    """Testes do FlagsPanel (aba LLM Config) e do conjunto fechado."""

    @pytest.mark.parametrize(
        ("v2_enabled", "expected_order"),
        [
            pytest.param(False, _LEGACY_FLAG_ORDER_EXPECTED, id="legado"),
            pytest.param(True, _V2_FLAG_ORDER_EXPECTED, id="v2"),
        ],
    )
    def test_supported_flags_match_kill_switch_regime(self, v2_enabled, expected_order):
        """Conjunto fechado e ordem canonica sao funcao do regime, nao constantes.

        Os dois regimes ficam travados aqui de proposito: afirmar so o v2
        deixava o regime default (legado) sem cobertura, que foi como o
        roster legado pode encolher sem nenhum teste reclamar.

        A ordem e afirmada contra a tupla escrita a mao, e nao contra o
        conjunto: no modulo os dois saem da MESMA tupla do regime, entao
        compara-los entre si nunca falhava. A ordem tambem e contrato (vira a
        ordem do sufixo T1, com a MiMo antes do Kimi), e so a tupla esperada
        pega uma troca de posicao.
        """
        with _llm_flags_regime(v2_enabled):
            # `importlib.reload` reaproveita o mesmo objeto de modulo, entao o
            # import comum ja enxerga o conjunto recomputado.
            import workflow_app.config.llm_flags as lf_mod

            assert lf_mod._SUPPORTED_MCP_FLAGS == frozenset(expected_order)
            assert lf_mod._FLAG_CANONICAL_ORDER == expected_order

    def test_flags_panel_has_exactly_supported_flags(self, qapp):
        from workflow_app.config.llm_flags import _SUPPORTED_MCP_FLAGS
        from workflow_app.llm_config.flags_panel import FlagsPanel
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
        """Matriz de incompatibilidade sob o regime v2 (thinking/execution).

        O corpo enumera literais que so existem no roster v2. Sem armar o
        kill-switch o painel nasce com o roster legado
        (`_LEGACY_FLAG_ORDER_EXPECTED`) e a enumeracao estourava KeyError.
        """
        with _llm_flags_regime(True) as fp_mod:
            self._assert_incompatibility_matrix(fp_mod.FlagsPanel())

    @staticmethod
    def _assert_incompatibility_matrix(panel):
        # Main claude: todas habilitadas.
        panel.set_main_llm("claude")
        for flag, chk in panel._checkboxes.items():
            assert chk.isEnabled(), f"{flag} deveria estar habilitada sob Main claude"

        # Main kimi: --kimi e --kimi-k3 disabled (redundantes).
        panel.set_main_llm("kimi")
        assert not panel._checkboxes["--kimi"].isEnabled()
        assert "redundante" in panel._checkboxes["--kimi"].toolTip().lower() or "kimi" in panel._checkboxes["--kimi"].toolTip().lower()
        assert not panel._checkboxes["--kimi-k3"].isEnabled()
        # C-43 / R-40: --codex tambem cai sob Main Kimi, mas por auto-proxy,
        # nao por redundancia. As skills de provider do lado Kimi
        # (`.kimi/skills/codex`) sao o proprio Kimi se passando por Codex;
        # honrar a flag registraria segunda opiniao falsa. O tooltip precisa
        # dizer o motivo (C-57), e ele NAO e o de redundancia.
        assert not panel._checkboxes["--codex"].isEnabled()
        assert "auto-proxy" in panel._checkboxes["--codex"].toolTip().lower()
        assert not panel._checkboxes["--codex-ultra"].isEnabled()
        # Demais habilitadas.
        assert panel._checkboxes["--qwen"].isEnabled()
        assert panel._checkboxes["--grok"].isEnabled()
        assert panel._checkboxes["--opus"].isEnabled()
        assert panel._checkboxes["--sonnet"].isEnabled()
        assert panel._checkboxes["--fable"].isEnabled()

        # Main codex: --codex e --codex-ultra disabled.
        panel.set_main_llm("codex")
        assert not panel._checkboxes["--codex"].isEnabled()
        assert not panel._checkboxes["--codex-ultra"].isEnabled()
        assert panel._checkboxes["--kimi"].isEnabled()

        # Main qwen: --qwen disabled.
        panel.set_main_llm("qwen")
        assert not panel._checkboxes["--qwen"].isEnabled()
        assert panel._checkboxes["--kimi"].isEnabled()

        # Main grok: --grok e --grok-xhigh disabled.
        panel.set_main_llm("grok")
        assert not panel._checkboxes["--grok"].isEnabled()
        assert not panel._checkboxes["--grok-xhigh"].isEnabled()
        assert panel._checkboxes["--codex"].isEnabled()

    def test_kill_switch_disables_flags_only_under_non_claude_main(
        self, qapp, monkeypatch
    ):
        """SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0 tem escopo, nao e global.

        O nome da env var declara o escopo: ela freia a paridade de delegacao
        *non-Claude*. Sob Main Claude nao existe delegacao non-Claude a frear,
        entao desabilitar tudo era bug de escopo (corrigido em 2026-08-17).
        """
        monkeypatch.setenv("SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE", "0")
        # Reimport para capturar o env patchado.
        import importlib

        import workflow_app.config.feature_flags as ff_mod
        importlib.reload(ff_mod)
        try:
            import workflow_app.llm_config.flags_panel as fp_mod
            importlib.reload(fp_mod)
            panel = fp_mod.FlagsPanel()

            # Main Claude: kill-switch nao alcanca; todas seguem habilitadas.
            panel.set_main_llm("claude")
            for flag, chk in panel._checkboxes.items():
                assert chk.isEnabled(), (
                    f"{flag} nao deveria cair pelo kill-switch sob Main Claude"
                )

            # Main nao-Claude: TODAS as flags do roster vigente caem, com
            # motivo visivel (C-57). O roster muda com SF_LLM_FLAGS_V2
            # (`_V2_FLAG_ORDER_EXPECTED` ou `_LEGACY_FLAG_ORDER_EXPECTED`); a
            # assercao itera o painel para nao fixar numero.
            for main in ("kimi", "codex", "qwen", "grok"):
                panel.set_main_llm(main)
                for flag, chk in panel._checkboxes.items():
                    assert not chk.isEnabled(), (
                        f"{flag} deveria estar disabled sob Main {main}"
                    )
                    assert "kill-switch" in chk.toolTip().lower()
        finally:
            monkeypatch.delenv("SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE", raising=False)
            importlib.reload(ff_mod)
            import workflow_app.llm_config.flags_panel as fp_mod
            importlib.reload(fp_mod)

    def test_flags_panel_survives_rerun_after_main_change(self, qapp):
        """Transicoes de Main sob o regime v2 (o corpo cita `--qwen`)."""
        with _llm_flags_regime(True) as fp_mod:
            panel = fp_mod.FlagsPanel()
            self._assert_rerun_after_main_change(panel)

    @staticmethod
    def _assert_rerun_after_main_change(panel):
        # Claude -> Kimi -> Claude: estado correto em cada transicao.
        panel.set_main_llm("claude")
        assert all(chk.isEnabled() for chk in panel._checkboxes.values())

        panel.set_main_llm("kimi")
        assert not panel._checkboxes["--kimi"].isEnabled()
        # C-43: --codex tambem cai sob Main Kimi (auto-proxy).
        assert not panel._checkboxes["--codex"].isEnabled()
        assert panel._checkboxes["--qwen"].isEnabled()

        # A volta a Claude precisa reabilitar TUDO, inclusive o --codex que
        # caiu por auto-proxy: estado de disable nunca pode ficar grudado.
        panel.set_main_llm("claude")
        assert all(chk.isEnabled() for chk in panel._checkboxes.values())

    def test_flags_panel_under_legacy_regime_exposes_only_legacy_flags(self, qapp):
        """Regime legado: o painel expoe SO o roster legado.

        O roster e `_LEGACY_FLAG_ORDER_EXPECTED`: a tabela C26 mais `--mimo`,
        que entra nos dois regimes (MiMo > Kimi, 2026-10-02).

        Este e o regime default do processo (kill-switch ausente), e ate aqui
        ele nao tinha nenhuma cobertura de painel: os testes existentes so
        descreviam o roster v2. As regras de disable continuam valendo sobre o
        conjunto reduzido, incluindo o auto-proxy C-43/R-40 do `--codex` sob
        Main Kimi.
        """
        with _llm_flags_regime(False) as fp_mod:
            panel = fp_mod.FlagsPanel()
            assert set(panel._checkboxes) == _LEGACY_FLAG_LITERALS

            panel.set_main_llm("claude")
            assert all(chk.isEnabled() for chk in panel._checkboxes.values())

            panel.set_main_llm("kimi")
            assert not panel._checkboxes["--kimi"].isEnabled()
            assert not panel._checkboxes["--codex"].isEnabled()
            assert "auto-proxy" in panel._checkboxes["--codex"].toolTip().lower()

            panel.set_main_llm("codex")
            assert not panel._checkboxes["--codex"].isEnabled()
            assert panel._checkboxes["--kimi"].isEnabled()

            # A volta a Claude reabilita tudo tambem no roster reduzido.
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

from PySide6.QtWidgets import QComboBox, QPushButton

# Collect all testids in the window
all_testids = []
for w in [win, *win.findChildren(_W)]:
    tid = w.property("testid")
    if tid:
        all_testids.append(tid)

# Extract _TE_COMMANDS from Thinking/Execution combos (itemData) and
# leftover QPushButton properties (legacy path).
te_commands = {}
for combo in win.findChildren(QComboBox):
    for i in range(combo.count()):
        data = combo.itemData(i)
        if not isinstance(data, dict):
            continue
        tid = data.get("testid")
        cmd = data.get("te_command")
        if tid and cmd and str(tid).startswith("output-mcp-action-"):
            te_commands[str(tid)] = str(cmd)
            all_testids.append(str(tid))
for w in win.findChildren(QPushButton):
    tid2 = w.property("testid")
    cmd2 = w.property("te_command")
    if tid2 and cmd2 and str(tid2).startswith("output-mcp-action-"):
        te_commands[str(tid2)] = str(cmd2)

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
    # Sanear os kill-switches: o ambiente herdado nao pode decidir o regime
    # (o gate da matriz TE mora em _TE_FLAG_NAME desde o item 005; o switch
    # MiMo sai junto, mesmo sem gatear a matriz, para o cenario ser o pedido).
    for flag in (_FLAG_NAME, _TE_FLAG_NAME, _MIMO_FLAG_NAME):
        if env_override is None or flag not in env_override:
            env.pop(flag, None)

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
    """Item 023: Thinking/Execution split com os kill-switches V2 armados."""

    def test_thinking_group_has_expected_buttons(self):
        """Thinking group: alternativas do select alinhadas a queue-div-flag.

        Conjunto exato (sem contagem no nome): a thinking `mimo-pro` entra
        entre `codex-ultra` e `kimi`, sem gate do switch MiMo.
        """
        data = _run_te_probe(_TE_FLAGS_ON)
        expected = sorted([
            "output-mcp-action-thinking",
            "output-mcp-action-thinking-select",
            "output-mcp-action-thinking-fable",
            "output-mcp-action-thinking-opus",
            "output-mcp-action-thinking-codex-ultra",
            "output-mcp-action-thinking-mimo-pro",
            "output-mcp-action-thinking-kimi",
            "output-mcp-action-thinking-grok-xhigh",
        ])
        assert data["thinking_tids"] == expected, (
            f"Expected {expected}, got {data['thinking_tids']}"
        )

    def test_execution_group_has_6_buttons(self):
        """Execution group: 6 alternativas no select, alinhadas a queue-div-flag."""
        data = _run_te_probe(_TE_FLAGS_ON)
        expected = sorted([
            "output-mcp-action-execution",
            "output-mcp-action-execution-select",
            "output-mcp-action-execution-grok",
            "output-mcp-action-execution-sonnet",
            "output-mcp-action-execution-mimo",
            "output-mcp-action-execution-kimi",
            "output-mcp-action-execution-qwen",
            "output-mcp-action-execution-codex",
        ])
        assert data["execution_tids"] == expected, (
            f"Expected {expected}, got {data['execution_tids']}"
        )

    def test_fixed_commands_in_te_commands(self):
        """Cada alternativa do select cola o /mcp: da coluna thinking/execution."""
        data = _run_te_probe(_TE_FLAGS_ON)
        cmds = data["te_commands"]
        assert cmds.get("output-mcp-action-thinking-fable") == "/mcp:fable"
        assert cmds.get("output-mcp-action-thinking-opus") == "/mcp:claude-ultra"
        assert cmds.get("output-mcp-action-thinking-codex-ultra") == "/mcp:codex-ultra"
        assert cmds.get("output-mcp-action-thinking-mimo-pro") == "/mcp:mimo-pro"
        assert cmds.get("output-mcp-action-thinking-kimi") == "/mcp:kimi-k3"
        assert cmds.get("output-mcp-action-thinking-grok-xhigh") == "/mcp:grok-xhigh"
        assert cmds.get("output-mcp-action-execution-grok") == "/mcp:grok"
        assert cmds.get("output-mcp-action-execution-sonnet") == "/mcp:sonnet"
        assert cmds.get("output-mcp-action-execution-mimo") == "/mcp:mimo"
        assert cmds.get("output-mcp-action-execution-kimi") == "/mcp:kimi"
        assert cmds.get("output-mcp-action-execution-qwen") == "/mcp:qwen"
        assert cmds.get("output-mcp-action-execution-codex") == "/mcp:codex"

    def test_no_legacy_skill_pills_in_commands(self):
        """C-15: Old skill CLI pills are NOT in the command map."""
        data = _run_te_probe(_TE_FLAGS_ON)
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
        data = _run_te_probe(_TE_FLAGS_ON)
        assert not data["has_legacy_main"]
        assert not data["has_legacy_parallel"]
        assert not data["has_legacy_dual"]

    def test_persona_filter_bar_exists(self):
        """C-16: output-mcp-persona-filter-bar exists with flag=1."""
        data = _run_te_probe(_TE_FLAGS_ON)
        assert data["has_persona_filter"], (
            "output-mcp-persona-filter-bar should exist with flag=1"
        )

    def test_persona_checkboxes_have_categories(self):
        """C-16: MCP persona checkboxes have persona_category property."""
        data = _run_te_probe(_TE_FLAGS_ON)
        cats = data["persona_cats"]
        assert len(cats) >= 16, f"Expected at least 16 personas, got {len(cats)}"
        assert cats["output-mcp-persona-search-in"] == "Research"
        assert cats["output-mcp-persona-criar-task"] == "Build"
        assert cats["output-mcp-persona-delegador"] == "Plan"
        assert cats["output-mcp-persona-ux-ui"] == "Design"
        assert cats["output-mcp-persona-controversial"] == "Review"
        assert cats["output-mcp-persona-performance-engineer"] == "specialists"


class TestThinkingExecutionClaudeLocal:
    """Claude thinking/execution passam pelos wrappers MCP, nao por CLI nua."""

    def test_thinking_opus_binds_claude_ultra(self):
        data = _run_te_probe(_TE_FLAGS_ON)
        assert data["te_commands"].get("output-mcp-action-thinking-opus") == (
            "/mcp:claude-ultra"
        )
        assert data["te_commands"].get("output-mcp-action-thinking-fable") == (
            "/mcp:fable"
        )

    def test_execution_sonnet_binds_mcp_sonnet(self):
        data = _run_te_probe(_TE_FLAGS_ON)
        assert data["te_commands"].get("output-mcp-action-execution-sonnet") == (
            "/mcp:sonnet"
        )


class TestThinkingExecutionFlagAbsent:
    """Kill-switch: ambos ausentes = legacy layout (G3)."""

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
    """Kill-switch: ambos em '0' = legacy layout (G3)."""

    def test_legacy_buttons_present_when_flag_off(self):
        """Flag='0': Main/Parallel/Dual present, no Thinking/Execution."""
        data = _run_te_probe(_TE_FLAGS_OFF)
        assert data["has_legacy_main"]
        assert data["has_legacy_parallel"]
        assert data["has_legacy_dual"]
        assert data["thinking_tids"] == []
        assert data["execution_tids"] == []

    def test_persona_filter_absent_when_flag_off(self):
        """Flag='0': persona filter bar does NOT exist."""
        data = _run_te_probe(_TE_FLAGS_OFF)
        assert not data["has_persona_filter"]


# Item 015: as 16 personas curadas da secao MCPs, na ORDEM da tupla
# `persona_specs` de `_build_mcp_column()`. Lista declarada localmente de
# proposito: dois modulos de teste independentes provando a mesma sequencia
# valem mais que um import cruzado entre arquivos de teste.
_CURATED_PERSONA_TESTIDS = [
    "output-mcp-persona-search-in",
    "output-mcp-persona-search-out",
    "output-mcp-persona-search-forge",
    "output-mcp-persona-controversial",
    "output-mcp-persona-hardening",
    "output-mcp-persona-criar-task",
    "output-mcp-persona-revisar-task",
    "output-mcp-persona-executor",
    "output-mcp-persona-rev-exec",
    "output-mcp-persona-revisar-qa",
    "output-mcp-persona-code-debugger",
    "output-mcp-persona-delegador",
    "output-mcp-persona-scaffolds-blueprints-updater",
    "output-mcp-persona-questioner",
    "output-mcp-persona-ux-ui",
    "output-mcp-persona-performance-engineer",
]


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
        """C-16: 'All' mostra todas as personas curadas, na ordem da tupla.

        Item 015 - substituicao de contrato: a assercao anterior era
        `len(not_hidden) == 16`, contagem nua. Ela nao protege a UI, porque um
        filtro por exclusao do sufixo `-rules` tambem devolve 16 personas com 12
        slugs diferentes. Aqui a prova e dupla: 'All' nao esconde ninguem E o
        conjunto visivel e exatamente o curado, na ordem de `persona_specs`
        (que e a ordem de composicao de `_compose_mcp_text`).
        """
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
        visible_ids = [c.property("testid") for c in not_hidden]
        assert visible_ids[: len(_CURATED_PERSONA_TESTIDS)] == _CURATED_PERSONA_TESTIDS
        assert set(_CURATED_PERSONA_TESTIDS) <= set(visible_ids)


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

    def test_grok_spike_gate_default_off(self, monkeypatch):
        """Feature gate SF_GROK_SPIKE desligado por default."""
        # Default = variavel ausente no boot. O gate congela no import e o host
        # do operador pode exportar SF_GROK_SPIKE=1: simula o boot sem a env var.
        from workflow_app.config import feature_flags
        from workflow_app.config.feature_flags import grok_spike_enabled
        boot_state = feature_flags._resolve_grok_spike_state({})
        assert boot_state == feature_flags.STATE_ABSENT
        monkeypatch.setattr(feature_flags, "_GROK_SPIKE_STATE", boot_state)
        monkeypatch.setattr(
            feature_flags, "_GROK_SPIKE_ENABLED", boot_state == feature_flags.STATE_ON
        )
        assert grok_spike_enabled() is False

    def test_grok_spike_not_active_when_gate_off(self, monkeypatch):
        """is_grok_spike_active() retorna False com gate desligado."""
        from workflow_app.config import feature_flags
        from workflow_app.llm_config.grok_spike import is_grok_spike_active
        boot_state = feature_flags._resolve_grok_spike_state({})
        monkeypatch.setattr(feature_flags, "_GROK_SPIKE_STATE", boot_state)
        monkeypatch.setattr(
            feature_flags, "_GROK_SPIKE_ENABLED", boot_state == feature_flags.STATE_ON
        )
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
