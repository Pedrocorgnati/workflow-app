"""Loop 08-11-llm-config-multillm-expansion, item 018.

Radios de Main com estado persistido, preflight de credencial ORCH antes
do enqueue e teste de paridade dos quatro mapas de configuracao.

Criterios do apendice: C-06, C-20, C-34.
Restricao: Grok NAO entra neste item (item 026).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from workflow_app.command_queue.command_item_widget import (
    _PROVIDER_BTN_STYLE,
    _PROVIDER_DEST,
    _PROVIDER_LABEL,
)
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.provider_router import (
    Provider,
    _PROVIDER_FAMILIES,
)


# --------------------------------------------------------------------------- #
# main_radio — radios de selecao de Main com persistencia                      #
# --------------------------------------------------------------------------- #

class TestMainRadioExistence:
    """Radios de Main para Claude, Kimi, Codex e Qwen existem com testids."""

    def test_main_llm_container_has_four_radios(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        radios = [
            w._main_claude_radio,
            w._main_codex_radio,
            w._main_kimi_radio,
            w._main_qwen_radio,
        ]
        assert len(radios) == 4

    def test_main_radio_testids(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert w._main_claude_radio.property("testid") == "queue-radio-main-claude"
        assert w._main_codex_radio.property("testid") == "queue-radio-main-codex"
        assert w._main_kimi_radio.property("testid") == "queue-chk-force-kimi"
        assert w._main_qwen_radio.property("testid") == "queue-radio-main-qwen"

    def test_main_radio_group_exclusive(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert w._main_llm_group.exclusive()

    def test_claude_checked_by_default(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert w._main_claude_radio.isChecked()

    def test_current_main_llm_reflects_radio(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert w.current_main_llm() == "claude"
        w._main_codex_radio.setChecked(True)
        assert w.current_main_llm() == "codex"
        w._main_kimi_radio.setChecked(True)
        assert w.current_main_llm() == "kimi"
        w._main_qwen_radio.setChecked(True)
        assert w.current_main_llm() == "qwen"


class TestMainRadioPersistence:
    """Estado do radio Main LLM persistido via QSettings."""

    def test_persist_on_radio_change(self, qtbot):
        from PySide6.QtCore import QSettings
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        QSettings("systemForge", "workflow-app").remove("main_llm/selected")

        w._main_codex_radio.setChecked(True)
        w._persist_main_llm_selection()
        saved = QSettings("systemForge", "workflow-app").value(
            "main_llm/selected"
        )
        assert saved == "codex"

    def test_persist_kimi(self, qtbot):
        from PySide6.QtCore import QSettings
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_kimi_radio.setChecked(True)
        w._persist_main_llm_selection()
        saved = QSettings("systemForge", "workflow-app").value(
            "main_llm/selected"
        )
        assert saved == "kimi"

    def test_persist_qwen(self, qtbot):
        from PySide6.QtCore import QSettings
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_qwen_radio.setChecked(True)
        w._persist_main_llm_selection()
        saved = QSettings("systemForge", "workflow-app").value(
            "main_llm/selected"
        )
        assert saved == "qwen"


# --------------------------------------------------------------------------- #
# orch_preflight — preflight de credencial ORCH antes do enqueue               #
# --------------------------------------------------------------------------- #

class TestOrchPreflight:
    """Preflight de credencial do Main LLM antes do enqueue."""

    def test_preflight_passes_with_claude_key(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_claude_radio.setChecked(True)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            assert w._orch_preflight_main_credential() is None

    def test_preflight_blocks_without_claude_key(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_claude_radio.setChecked(True)
        with patch.dict(os.environ, {}, clear=False):
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                result = w._orch_preflight_main_credential()
                assert result is not None
                assert "claude" in result
                assert "ANTHROPIC_API_KEY" in result

    def test_preflight_passes_with_kimi_key(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_kimi_radio.setChecked(True)
        with patch.dict(os.environ, {"KIMI_API_KEY": "test-key"}):
            assert w._orch_preflight_main_credential() is None

    def test_preflight_passes_with_moonshot_fallback(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_kimi_radio.setChecked(True)
        with patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key"}, clear=False):
            env = os.environ.copy()
            env.pop("KIMI_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                result = w._orch_preflight_main_credential()
                assert result is None

    def test_preflight_blocks_without_codex_key(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_codex_radio.setChecked(True)
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = w._orch_preflight_main_credential()
            assert result is not None
            assert "codex" in result

    def test_preflight_blocks_without_qwen_key(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_qwen_radio.setChecked(True)
        env = os.environ.copy()
        env.pop("DASHSCOPE_API_KEY", None)
        env.pop("QWEN_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = w._orch_preflight_main_credential()
            assert result is not None
            assert "qwen" in result


# --------------------------------------------------------------------------- #
# map_parity — paridade entre os quatro mapas de configuracao                  #
# --------------------------------------------------------------------------- #

class TestMapParity:
    """Paridade entre os quatro mapas: Provider enum, _PROVIDER_FAMILIES,
    _PROVIDER_BTN_STYLE, _PROVIDER_LABEL e _PROVIDER_DEST.

    Os quatro mapas devem cobrir exatamente o mesmo conjunto de providers.
    """

    def _enum_members(self) -> set[str]:
        return {p.value for p in Provider}

    def _families_keys(self) -> set[str]:
        return set(_PROVIDER_FAMILIES.keys())

    def _btn_style_keys(self) -> set[str]:
        return {p.value for p in _PROVIDER_BTN_STYLE}

    def _label_keys(self) -> set[str]:
        return {p.value for p in _PROVIDER_LABEL}

    def _dest_keys(self) -> set[str]:
        return {p.value for p in _PROVIDER_DEST}

    def test_enum_and_families_parity(self):
        assert self._enum_members() == self._families_keys(), (
            f"Provider enum members {self._enum_members()} != "
            f"_PROVIDER_FAMILIES keys {self._families_keys()}"
        )

    def test_enum_and_btn_style_parity(self):
        assert self._enum_members() == self._btn_style_keys(), (
            f"Provider enum members {self._enum_members()} != "
            f"_PROVIDER_BTN_STYLE keys {self._btn_style_keys()}"
        )

    def test_enum_and_label_parity(self):
        assert self._enum_members() == self._label_keys(), (
            f"Provider enum members {self._enum_members()} != "
            f"_PROVIDER_LABEL keys {self._label_keys()}"
        )

    def test_enum_and_dest_parity(self):
        assert self._enum_members() == self._dest_keys(), (
            f"Provider enum members {self._enum_members()} != "
            f"_PROVIDER_DEST keys {self._dest_keys()}"
        )

    def test_all_four_maps_consistent(self):
        """Todos os quatro mapas cobrem exatamente o mesmo conjunto."""
        enum_set = self._enum_members()
        assert enum_set == self._families_keys() == self._btn_style_keys() == self._label_keys() == self._dest_keys()

    def test_four_providers_present(self):
        """Os quatro providers (claude, kimi, codex, qwen) estao presentes."""
        expected = {"claude", "kimi", "codex", "qwen"}
        assert self._enum_members() == expected

    def test_no_grok_in_maps(self):
        """Grok NAO entra neste item (restricao D-41, C-58)."""
        assert "grok" not in self._enum_members()
        assert "grok" not in self._families_keys()
        assert "grok" not in self._btn_style_keys()
