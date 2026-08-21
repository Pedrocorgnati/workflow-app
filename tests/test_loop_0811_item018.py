"""Loop 08-11-llm-config-multillm-expansion, item 018.

Radios de Main com estado persistido, preflight de credencial ORCH antes
do enqueue e teste de paridade dos quatro mapas de configuracao.

Criterios do apendice: C-06, C-20, C-34.
Restricao: Grok NAO entra neste item (item 026).
"""

from __future__ import annotations

import json
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
    """Radios de Main existem com testids.

    Item 004 (C6/C13) do loop 08-17-systemforge-multillm-gaps-refactor: o eixo
    Main deixou de ser so provider. A lista canonica fechada em `source.md:1196`
    tem 7 slugs com semantica family+variant (opus, sonnet, codex, kimi,
    kimi-k3, qwen, grok), mais o radio `claude` (family nua) que permanece o
    default do regime legado — 8 radios instanciados.

    O teste antigo `test_main_llm_container_has_four_radios` afirmava "quatro"
    listando quatro atributos: a contagem era da propria lista literal, nao do
    widget, e por isso continuava verde com 5, 6 ou 8 radios no grupo. A
    contagem agora sai do `_main_llm_group` e o regime de gate esta declarado
    explicitamente em cada assercao.
    """

    def test_main_llm_group_has_all_canonical_radios(self, qtbot):
        """Contagem real, lida do QButtonGroup, nao de uma lista literal.

        A INSTANCIACAO dos 8 radios independe de flag — quem depende de
        `llm_config_v2_enabled()`/`grok_spike_enabled()` e a VISIBILIDADE
        (coberta por `test_variant_radios_visibility_follows_gate`).
        """
        from workflow_app.command_queue.command_queue_widget import (
            _MAIN_LLM_VARIANTS,
        )

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert len(w._main_llm_group.buttons()) == 8
        # os 7 canonicos + `claude`, cada um alcancavel pelo slug
        assert set(w._main_radio_map) == set(_MAIN_LLM_VARIANTS) | {"claude"}
        for slug, radio in w._main_radio_map.items():
            assert radio in w._main_llm_group.buttons(), slug

    def test_main_radio_testids(self, qtbot):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        assert w._main_claude_radio.property("testid") == "queue-radio-main-claude"
        assert w._main_codex_radio.property("testid") == "queue-radio-main-codex"
        # D-004-C: o testid do kimi permanece o alias historico
        # `queue-chk-force-kimi`. Renomear e mudanca de contrato de testid e
        # esta fora do escopo do item 004.
        assert w._main_kimi_radio.property("testid") == "queue-chk-force-kimi"
        assert w._main_qwen_radio.property("testid") == "queue-radio-main-qwen"
        assert w._main_grok_radio.property("testid") == "queue-radio-main-grok"
        # Item 004 (C6): os 3 testids que eram declarados e nunca criados.
        assert w._main_opus_radio.property("testid") == "queue-radio-main-opus"
        assert w._main_sonnet_radio.property("testid") == "queue-radio-main-sonnet"
        assert w._main_kimi_k3_radio.property("testid") == "queue-radio-main-kimi-k3"

    def test_variant_radios_visibility_follows_gate(self, qtbot):
        """Variantes de raciocinio ficam ocultas no Main LLM (CLI do terminal).
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        for radio in (
            w._main_opus_radio,
            w._main_sonnet_radio,
            w._main_kimi_k3_radio,
        ):
            assert radio.isHidden() is True, radio.property("testid")
        # Regime legado: nenhum radio NOVO visivel — o eixo Main volta a ser
        # exatamente o roster de provider de antes do item 004.
        assert w._main_claude_radio.isHidden() is False
        assert w._main_codex_radio.isHidden() is False
        assert w._main_kimi_radio.isHidden() is False

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
        """Item 018 + item 011: preflight no enqueue, e no TOPO dele.

        O enqueue e o momento em que o operador ainda pode trocar o Main sem ter
        uma fila a meio caminho. O guard de dispatch continua existindo como
        backstop fail-closed — a credencial pode sumir entre enqueue e dispatch,
        e falhar em silencio ali seria pior — mas nao pode ser o **primeiro**
        lugar onde o problema aparece.

        Item 011 (C12) adiciona a assercao de ORDEM: os dois preflights
        (provider e capability) rodam ANTES de `self._items.clear()` destruir a
        fila e ANTES de `adapt_specs_to_main` traduzir as specs. Avisar depois da
        traducao descreveria uma fila que o operador nunca montou (sob Main
        nao-Claude a traducao remove `/model`/`/effort`); avisar depois do clear
        descreveria uma fila que ja nao existe. Instrumentacao por gravacao de
        eventos, sem sleep e sem numero de linha.
        """
        from workflow_app.domain import CommandSpec

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        order: list[str] = []

        class _RecordingItems(list):
            def clear(self):  # noqa: D102 - instrumentacao de teste
                order.append("clear")
                super().clear()

        w._items = _RecordingItems(w._items)

        def _fake_translate(specs, main_llm):
            order.append("translate")
            return specs

        seen: list[tuple[str, str]] = []
        with patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: (
                order.append("preflight-provider"), "BLOQUEIO-DE-TESTE"
            )[1],
        ), patch.object(
            CommandQueueWidget,
            "_capability_preflight_specs",
            lambda self, specs: (
                order.append("preflight-capability"), "CAPABILITY-DE-TESTE"
            )[1],
        ), patch(
            "workflow_app.command_queue.command_queue_widget.adapt_specs_to_main",
            _fake_translate,
        ), patch(
            "workflow_app.command_queue.command_queue_widget.signal_bus"
        ) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline([CommandSpec(name="/prd-create", position=1)])

        assert ("BLOQUEIO-DE-TESTE", "warning") in seen
        assert ("CAPABILITY-DE-TESTE", "warning") in seen
        assert "preflight-provider" in order and "preflight-capability" in order
        assert order.index("preflight-provider") < order.index("clear")
        assert order.index("preflight-capability") < order.index("clear")
        assert order.index("clear") < order.index("translate")

    def test_load_pipeline_signature_stays_none(self, qtbot):
        """Item 011: preflight que so avisa NAO pode virar retorno tratavel.

        Se `load_pipeline` passasse a devolver veredito, os 4 callsites
        (`main_window.py` em `_on_pipeline_ready` e `_refresh_queue_ui`,
        a montagem Daily Loop e `restore_queue_snapshot`) teriam que decidir o
        que fazer com ele — e nenhum decide. D4 mantem o preflight informativo.
        """
        from workflow_app.domain import CommandSpec

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        with patch(
            "workflow_app.command_queue.command_queue_widget.signal_bus"
        ):
            assert w.load_pipeline([CommandSpec(name="/prd-create", position=1)]) is None
        # `from __future__ import annotations`: a anotacao chega como string.
        assert CommandQueueWidget.load_pipeline.__annotations__.get("return") in (
            None,
            "None",
        )

    def test_empty_queue_emits_no_preflight_toast(self, qtbot):
        """Fila vazia nao avisa — comportamento preservado pela mudanca de ordem."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        seen: list[tuple[str, str]] = []
        with patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: "NAO-DEVIA-SAIR",
        ), patch.object(
            CommandQueueWidget,
            "_capability_preflight_specs",
            lambda self, specs: "NAO-DEVIA-SAIR-TAMPOUCO",
        ), patch(
            "workflow_app.command_queue.command_queue_widget.signal_bus"
        ) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline([])
        assert not [t for t in seen if "NAO-DEVIA-SAIR" in t[0]]


# --------------------------------------------------------------------------- #
# capability_preflight — item 011 (C11, C12): avisa por comando, nao barra     #
# --------------------------------------------------------------------------- #

class TestCapabilityPreflight:
    """Preflight de capability por comando sob o Main corrente.

    Contrato D4: AVISA, nao barra. Um toast agregado por `load_pipeline`,
    silencio total para comando fora do snapshot.
    """

    @staticmethod
    def _snapshot(tmp_path, matrix: dict) -> object:
        from workflow_app.provider_capability_loader import ProviderCapabilityLoader

        path = tmp_path / "provider-capability-matrix.json"
        path.write_text(
            json.dumps({"schema_version": "1.0.0", "matrix": matrix}),
            encoding="utf-8",
        )
        return ProviderCapabilityLoader(path)

    @contextmanager
    def _with_loader(self, loader):
        from workflow_app.provider_capability_loader import reset_singleton

        reset_singleton()
        try:
            with patch(
                "workflow_app.command_queue.command_queue_widget.get_capability_loader",
                lambda *a, **k: loader,
            ):
                yield
        finally:
            reset_singleton()

    def _run(self, qtbot, loader, names: list[str]) -> list[tuple[str, str]]:
        from workflow_app.domain import CommandSpec

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        seen: list[tuple[str, str]] = []
        specs = [CommandSpec(name=n, position=i) for i, n in enumerate(names, start=1)]
        with self._with_loader(loader), patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: None,
        ), patch(
            "workflow_app.command_queue.command_queue_widget.signal_bus"
        ) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline(specs)
        return [t for t in seen if t[0].startswith("Capability preflight")]

    def test_unmapped_command_is_silent(self, qtbot, tmp_path):
        """Comando fora dos 21 do snapshot NAO gera aviso.

        `get_capability` responderia 'indisponivel' para ele (fail-closed); e
        por isso que o preflight consulta `get_mapped_capabilities`, que
        devolve `None` para nao mapeado.
        """
        loader = self._snapshot(
            tmp_path,
            {"/prd-create": {"claude": {"main": {"file_write": "disponivel"}}}},
        )
        assert self._run(qtbot, loader, ["/comando-que-nao-existe-xyz"]) == []

    def test_mapped_and_available_is_silent(self, qtbot, tmp_path):
        """Tudo disponivel: silencio."""
        loader = self._snapshot(
            tmp_path,
            {"/prd-create": {"claude": {"main": {"file_write": "disponivel"}}}},
        )
        assert self._run(qtbot, loader, ["/prd-create"]) == []

    def test_directives_and_clear_are_skipped(self, qtbot, tmp_path):
        """`/model`, `/effort` e `/clear` nao vao a capability nenhuma."""
        loader = self._snapshot(
            tmp_path,
            {"/model": {"claude": {"main": {"file_write": "indisponivel"}}},
             "/clear": {"claude": {"main": {"file_write": "indisponivel"}}}},
        )
        assert self._run(qtbot, loader, ["/model opus", "/effort high", "/clear"]) == []

    def test_five_missing_commands_produce_one_aggregated_toast(self, qtbot, tmp_path):
        """5 comandos sem capability = UM toast, 3 exemplos, sufixo `(+2)`.

        Zero Silencio nao e Zero Ruido: um aviso por comando repetido cinco
        vezes esconde o sinal em vez de entrega-lo.
        """
        matrix = {
            f"/cmd-{i}": {"claude": {"main": {"file_write": "indisponivel"}}}
            for i in range(1, 6)
        }
        loader = self._snapshot(tmp_path, matrix)
        toasts = self._run(qtbot, loader, [f"/cmd-{i}" for i in range(1, 6)])
        assert len(toasts) == 1
        msg, severity = toasts[0]
        assert severity == "warning"
        assert "5 item(ns)" in msg
        assert "/cmd-1:file_write, /cmd-2:file_write, /cmd-3:file_write" in msg
        assert msg.endswith("(+2)")
        assert "/cmd-4" not in msg and "/cmd-5" not in msg
        assert "nao barra" in msg

    def test_no_overflow_suffix_when_three_or_fewer(self, qtbot, tmp_path):
        """Ate 3 exemplos, nenhum `(+K)`."""
        matrix = {
            f"/cmd-{i}": {"claude": {"main": {"file_write": "indisponivel"}}}
            for i in range(1, 3)
        }
        loader = self._snapshot(tmp_path, matrix)
        toasts = self._run(qtbot, loader, ["/cmd-1", "/cmd-2"])
        assert len(toasts) == 1
        assert "(+" not in toasts[0][0]
        assert "2 item(ns)" in toasts[0][0]

    def test_missing_snapshot_says_so_once(self, qtbot, tmp_path):
        """Snapshot ausente: uma mensagem honesta, sem iterar comando nenhum."""
        from workflow_app.provider_capability_loader import ProviderCapabilityLoader

        loader = ProviderCapabilityLoader(tmp_path / "nao-existe.json")
        toasts = self._run(qtbot, loader, ["/prd-create", "/execute-task"])
        assert len(toasts) == 1
        assert toasts[0][0] == (
            "Capability preflight indisponivel: snapshot_ausente (aviso, nao barra)."
        )
        assert toasts[0][1] == "warning"

    def test_local_action_specs_are_skipped(self, qtbot, tmp_path):
        """`local-action` nao vai a provider nenhum, logo nao tem capability."""
        from workflow_app.domain import CommandSpec

        loader = self._snapshot(
            tmp_path,
            {"/cmd-1": {"claude": {"main": {"file_write": "indisponivel"}}}},
        )
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = CommandSpec(
            name="/cmd-1", position=1, kind="local-action", local_action_id="x"
        )
        with self._with_loader(loader):
            assert w._capability_preflight_specs([spec]) is None

    def test_preflight_does_not_touch_queue_items(self, qtbot, tmp_path):
        """Metodo puro em relacao a fila: nao le nem escreve `self._items`."""
        from workflow_app.domain import CommandSpec

        loader = self._snapshot(
            tmp_path,
            {"/cmd-1": {"claude": {"main": {"file_write": "indisponivel"}}}},
        )
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        sentinel = object()
        w._items = sentinel  # type: ignore[assignment]
        with self._with_loader(loader):
            msg = w._capability_preflight_specs([CommandSpec(name="/cmd-1", position=1)])
        assert msg is not None
        assert w._items is sentinel

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
