"""Loop 08-11-llm-config-multillm-expansion, item 018.

Radios de Main com estado persistido, preflight de credencial ORCH antes
do enqueue e teste de paridade dos quatro mapas de configuracao.

Criterios do apendice: C-06, C-20, C-34.
Restricao: Grok NAO entra neste item (item 026).
"""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
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
    """Preflight ORCH do Main LLM (PF-01, source.md §10.13).

    Credencial de provider e **ORCH**: quem le e o agente/CLI, nao a aplicacao
    entregue. Por isso ela vive em `.claude/projects/{slug}.json >
    credentials.mcp_servers.<provider>.*` e **nunca** no `.env`. O preflight
    reprova em duas metades: provider sem CLI resolvivel (source.md:1415) e
    provider sem nenhuma fonte de credencial (project.json, config local do CLI
    ou env var, nesta ordem de autoridade).

    Estes testes substituem a bateria original que exigia variavel de ambiente
    (`ANTHROPIC_API_KEY` etc). Aquela semantica invertia PF-01: tratava o `.env`
    como fonte canonica e reprovava provider autenticado por `~/.codex/auth.json`
    — falso-negativo, nao fail-closed. A cobertura foi substituida, nao removida:
    cada caso de bloqueio antigo tem equivalente abaixo.
    """

    @staticmethod
    def _isolated_sources(**overrides):
        """`_ORCH_PROVIDER_SOURCES` com configs locais apontando para o vazio.

        Sem isso, `~/.codex/config.toml` (presente nesta maquina) aprovaria o
        codex antes do teste chegar ao ramo que ele quer exercitar.
        """
        base = dict(CommandQueueWidget._ORCH_PROVIDER_SOURCES)
        for slug, (binaries, cred_key, _cfg, envs) in list(base.items()):
            base[slug] = (binaries, cred_key, ("~/.nonexistent-sf-test-cfg",), envs)
        base.update(overrides)
        return base

    def _widget_with(self, qtbot, *, radio: str, cli: bool, project_json: bool):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        getattr(w, f"_main_{radio}_radio").setChecked(True)
        stack = [
            patch.object(
                CommandQueueWidget, "_ORCH_PROVIDER_SOURCES", self._isolated_sources()
            ),
            patch.object(
                CommandQueueWidget, "_orch_cli_resolvable", staticmethod(lambda _b: cli)
            ),
            patch.object(
                CommandQueueWidget,
                "_orch_credential_in_project_json",
                staticmethod(lambda _k: project_json),
            ),
        ]
        return w, stack

    @contextmanager
    def _apply(self, stack):
        with ExitStack() as es:
            for ctx in stack:
                es.enter_context(ctx)
            yield

    def test_preflight_passes_with_orch_credential_in_project_json(self, qtbot):
        """PF-01: project.json e a fonte canonica — basta ele, sem env var."""
        w, stack = self._widget_with(qtbot, radio="claude", cli=True, project_json=True)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with self._apply(stack), patch.dict(os.environ, env, clear=True):
            assert w._orch_preflight_main_credential() is None

    def test_preflight_blocks_without_cli(self, qtbot):
        """Metade 1 do fail-closed: provider sem CLI resolvivel (source.md:1415)."""
        w, stack = self._widget_with(qtbot, radio="claude", cli=False, project_json=True)
        with self._apply(stack):
            result = w._orch_preflight_main_credential()
            assert result is not None
            assert "claude" in result
            assert "CLI" in result

    def test_preflight_blocks_without_any_credential_source(self, qtbot):
        """Metade 2: CLI existe, mas nao ha credencial em nenhuma das 3 fontes."""
        w, stack = self._widget_with(qtbot, radio="codex", cli=True, project_json=False)
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with self._apply(stack), patch.dict(os.environ, env, clear=True):
            result = w._orch_preflight_main_credential()
            assert result is not None
            assert "codex" in result
            assert "credentials.mcp_servers.codex" in result

    def test_preflight_blocks_qwen_without_any_credential_source(self, qtbot):
        w, stack = self._widget_with(qtbot, radio="qwen", cli=True, project_json=False)
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DASHSCOPE_API_KEY", "QWEN_API_KEY")
        }
        with self._apply(stack), patch.dict(os.environ, env, clear=True):
            result = w._orch_preflight_main_credential()
            assert result is not None
            assert "qwen" in result

    def test_preflight_env_var_is_last_resort_not_canonical(self, qtbot):
        """Env var ainda aprova, mas so depois de project.json e config local."""
        w, stack = self._widget_with(qtbot, radio="kimi", cli=True, project_json=False)
        with self._apply(stack), patch.dict(os.environ, {"KIMI_API_KEY": "test-key"}):
            assert w._orch_preflight_main_credential() is None

    def test_preflight_passes_with_moonshot_fallback(self, qtbot):
        w, stack = self._widget_with(qtbot, radio="kimi", cli=True, project_json=False)
        env = {k: v for k, v in os.environ.items() if k != "KIMI_API_KEY"}
        env["MOONSHOT_API_KEY"] = "test-key"
        with self._apply(stack), patch.dict(os.environ, env, clear=True):
            assert w._orch_preflight_main_credential() is None

    def test_preflight_runs_at_enqueue_not_only_at_dispatch(self, qtbot):
        """Item 018: "barra **no enqueue** com motivo, nunca no meio do dispatch".

        O enqueue e o momento em que o operador ainda pode trocar o Main sem ter
        uma fila a meio caminho. O guard de dispatch continua existindo como
        backstop fail-closed — a credencial pode sumir entre enqueue e dispatch,
        e falhar em silencio ali seria pior — mas nao pode ser o **primeiro**
        lugar onde o problema aparece.
        """
        from workflow_app.domain import CommandSpec

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        seen: list[tuple[str, str]] = []
        with patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: "BLOQUEIO-DE-TESTE",
        ), patch(
            "workflow_app.command_queue.command_queue_widget.signal_bus"
        ) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline([CommandSpec(name="/prd-create", position=1)])
        assert ("BLOQUEIO-DE-TESTE", "warning") in seen

    def test_preflight_passes_with_local_cli_config(self, qtbot):
        """Config local do CLI conta: e assim que o Codex deste host autentica."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._main_codex_radio.setChecked(True)
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.object(
            CommandQueueWidget, "_orch_cli_resolvable", staticmethod(lambda _b: True)
        ), patch.object(
            CommandQueueWidget,
            "_orch_credential_in_project_json",
            staticmethod(lambda _k: False),
        ), patch.object(
            os.path, "exists", lambda p: p.endswith("/.codex/auth.json")
        ), patch.dict(os.environ, env, clear=True):
            assert w._orch_preflight_main_credential() is None


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
        """Os cinco providers (claude, kimi, codex, qwen, grok) estao presentes.

        Item 020 adicionou grok ao Provider enum e mapas (DUP-01).
        """
        expected = {"claude", "kimi", "codex", "qwen", "grok"}
        assert self._enum_members() == expected

    def test_grok_in_maps(self):
        """Grok entra nos mapas a partir do item 020 (DUP-01)."""
        assert "grok" in self._enum_members()
        assert "grok" in self._families_keys()
        assert "grok" in self._btn_style_keys()
