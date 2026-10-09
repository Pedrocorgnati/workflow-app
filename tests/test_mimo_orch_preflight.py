"""Loop 10-03-systemforge-mimo-llm-paralela, item 011.

Preflight ORCH e preflight de capability sob o Main MiMo.

A entrada `mimo` de `_ORCH_PROVIDER_SOURCES` checa so o que o launcher
`mimod` usa de fato: o binario `mimod`, o `~/.local/share/mimocode/auth.json`
e as envs `XIAOMI_API_KEY`/`MIMO_API_KEY` (alias do mesmo segredo). O
project.json NAO e fonte da `mimo`: o `mimod.sh` aborta sem essas tres fontes
e nunca le `credentials.mcp_servers.mimo`, entao aprovar por ele seria
aprovacao calada (P4). Tudo e conferido so por existencia, nunca por valor
(P8 trava que nenhum valor de env chega a mensagem).

Os dois desfechos de credencial ausente ficam travados:

- enqueue (`load_pipeline`, D4): avisa com toast `warning` e carrega a fila
  mesmo assim (fail-open explicito, P9);
- dispatch (`_on_step_btn_clicked`): backstop fail-closed, registra
  `_record_provider_blocked` e nao publica (P10).

Isolamento do host: a maquina tem `mimod` e `auth.json` reais. Nenhum teste
depende deles nem os le; config, CLI, project.json e envs sao patchados.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec

SENTINELA = "sf-test-valor-sentinela-011"
_MIMO_ENVS = ("XIAOMI_API_KEY", "MIMO_API_KEY")
_BUS = "workflow_app.command_queue.command_queue_widget.signal_bus"


# --------------------------------------------------------------------------- #
# helpers (copiados de tests/test_loop_0811_item018.py, D-1)                   #
# --------------------------------------------------------------------------- #

def _isolated_sources(**overrides):
    """`_ORCH_PROVIDER_SOURCES` com configs locais apontando para o vazio."""
    base = dict(CommandQueueWidget._ORCH_PROVIDER_SOURCES)
    for slug, (binaries, cred_key, _cfg, envs) in list(base.items()):
        base[slug] = (binaries, cred_key, ("~/.nonexistent-sf-test-cfg",), envs)
    base.update(overrides)
    return base


def _auth_override(tmp_path):
    """Entrada de producao da `mimo` trocando so a config (D-3)."""
    src = CommandQueueWidget._ORCH_PROVIDER_SOURCES["mimo"]
    return _isolated_sources(
        mimo=(src[0], src[1], (str(tmp_path / "auth.json"),), src[3])
    )


def _env_without_mimo(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _MIMO_ENVS}
    env.update(extra)
    return env


def _mimo_widget(qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    # O radio mimo fica atras do kill switch do roster; o teste liga direto.
    w._main_radio_visible["mimo"] = True
    w._main_mimo_radio.setChecked(True)
    return w


def _credential_stack(*, sources, cli: bool, project_json: bool, env: dict):
    return [
        patch.object(CommandQueueWidget, "_ORCH_PROVIDER_SOURCES", sources),
        patch.object(
            CommandQueueWidget, "_orch_cli_resolvable", staticmethod(lambda _b: cli)
        ),
        patch.object(
            CommandQueueWidget,
            "_orch_credential_in_project_json",
            staticmethod(lambda _k: project_json),
        ),
        patch.dict(os.environ, env, clear=True),
    ]


@contextmanager
def _apply(stack):
    with ExitStack() as es:
        for ctx in stack:
            es.enter_context(ctx)
        yield


def _snapshot(tmp_path, matrix: dict) -> object:
    from workflow_app.provider_capability_loader import ProviderCapabilityLoader

    path = tmp_path / "provider-capability-matrix.json"
    path.write_text(
        json.dumps({"schema_version": "1.0.0", "matrix": matrix}),
        encoding="utf-8",
    )
    return ProviderCapabilityLoader(path)


@contextmanager
def _with_loader(loader):
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


def _mimo_warnings(seen: list[tuple]) -> list[tuple]:
    return [t for t in seen if t[1:] == ("warning",) and "'mimo'" in t[0]]


# --------------------------------------------------------------------------- #
# preflight ORCH do Main MiMo                                                  #
# --------------------------------------------------------------------------- #

class TestMimoOrchPreflight:
    def test_p1_entry_checks_only_what_mimod_uses(self):
        assert CommandQueueWidget._ORCH_PROVIDER_SOURCES["mimo"] == (
            ("mimod",),
            None,
            ("~/.local/share/mimocode/auth.json",),
            ("XIAOMI_API_KEY", "MIMO_API_KEY"),
        )

    def test_p2_blocks_without_cli(self, qtbot):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_isolated_sources(), cli=False, project_json=True,
            env=_env_without_mimo(),
        )
        with _apply(stack):
            msg = w._orch_preflight_main_credential("mimo")
        assert msg is not None
        assert "mimo" in msg and "CLI" in msg and "mimod" in msg

    def test_p3_missing_credential_names_every_source(self, qtbot, tmp_path):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_auth_override(tmp_path), cli=True, project_json=False,
            env=_env_without_mimo(),
        )
        with _apply(stack):
            msg = w._orch_preflight_main_credential("mimo")
        assert msg is not None
        assert "Credencial ORCH do Main LLM 'mimo' ausente" in msg
        for token in ("auth.json", "XIAOMI_API_KEY", "MIMO_API_KEY"):
            assert token in msg
        assert "credentials.mcp_servers" not in msg

    def test_p4_project_json_alone_does_not_approve(self, qtbot):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_isolated_sources(), cli=True, project_json=True,
            env=_env_without_mimo(),
        )
        with _apply(stack):
            msg = w._orch_preflight_main_credential("mimo")
        assert msg is not None
        assert "Credencial ORCH do Main LLM 'mimo' ausente" in msg

    def test_p5_present_via_auth_json(self, qtbot, tmp_path):
        (tmp_path / "auth.json").write_text("", encoding="utf-8")
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_auth_override(tmp_path), cli=True, project_json=False,
            env=_env_without_mimo(),
        )
        with _apply(stack):
            assert w._orch_preflight_main_credential("mimo") is None

    def test_p6_present_via_xiaomi_api_key(self, qtbot):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_isolated_sources(), cli=True, project_json=False,
            env=_env_without_mimo(XIAOMI_API_KEY=SENTINELA),
        )
        with _apply(stack):
            assert w._orch_preflight_main_credential("mimo") is None

    def test_p7_present_via_mimo_api_key_alias(self, qtbot):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_isolated_sources(), cli=True, project_json=False,
            env=_env_without_mimo(MIMO_API_KEY=SENTINELA),
        )
        with _apply(stack):
            assert w._orch_preflight_main_credential("mimo") is None

    def test_p8_message_never_carries_a_value(self, qtbot):
        w = _mimo_widget(qtbot)
        stack = _credential_stack(
            sources=_isolated_sources(), cli=True, project_json=False,
            env=_env_without_mimo(XIAOMI_API_KEY="   ", OPENAI_API_KEY=SENTINELA),
        )
        with _apply(stack):
            msg = w._orch_preflight_main_credential("mimo")
        assert msg is not None
        assert SENTINELA not in msg

    def test_p9_enqueue_warns_and_still_loads(self, qtbot, tmp_path):
        w = _mimo_widget(qtbot)
        seen: list[tuple] = []
        stack = _credential_stack(
            sources=_auth_override(tmp_path), cli=True, project_json=False,
            env=_env_without_mimo(),
        )
        stack.append(
            patch.object(
                CommandQueueWidget,
                "_capability_preflight_specs",
                lambda self, specs: None,
            )
        )
        with _apply(stack), patch(_BUS) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline([CommandSpec(name="/prd-create", position=1)])
        assert len(_mimo_warnings(seen)) == 1
        assert len(w._items) == 1

    def test_p10_dispatch_blocks_without_publishing(self, qtbot, tmp_path):
        w = _mimo_widget(qtbot)
        with patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: None,
        ), patch.object(
            CommandQueueWidget,
            "_capability_preflight_specs",
            lambda self, specs: None,
        ):
            w.load_pipeline([CommandSpec(name="/prd-create", position=1)])

        blocked: list[object] = []
        published: list[str] = []
        seen: list[tuple] = []

        def _fake_blocked(self, item, *, provider=None):
            blocked.append(provider)

        def _fake_publish(self, channel, *, route, text):
            published.append(text)

        stack = _credential_stack(
            sources=_auth_override(tmp_path), cli=True, project_json=False,
            env=_env_without_mimo(),
        )
        stack += [
            patch.object(CommandQueueWidget, "_record_provider_blocked", _fake_blocked),
            patch.object(CommandQueueWidget, "_publish_to_terminal", _fake_publish),
        ]
        with _apply(stack), patch(_BUS) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w._on_step_btn_clicked()
        assert blocked == ["mimo"]
        assert len(_mimo_warnings(seen)) == 1
        assert published == []


# --------------------------------------------------------------------------- #
# preflight de capability sob Main MiMo                                         #
# --------------------------------------------------------------------------- #

class TestMimoCapabilityPreflight:
    def test_p11_uncovered_main_is_explicit_fail_open(self, qtbot, tmp_path):
        loader = _snapshot(
            tmp_path, {"/prd-create": {"claude": {"main": {"file_write": "disponivel"}}}}
        )
        w = _mimo_widget(qtbot)
        seen: list[tuple] = []
        with _with_loader(loader), patch.object(
            CommandQueueWidget,
            "_orch_preflight_main_credential",
            lambda self, main_llm=None: None,
        ), patch(_BUS) as bus:
            bus.toast_requested.emit.side_effect = lambda *a: seen.append(a)
            w.load_pipeline([CommandSpec(name="/prd-create", position=1)])
        cap = [t for t in seen if t[0].startswith("Capability preflight")]
        assert len(cap) == 1
        assert "Main 'mimo' sem cobertura no snapshot" in cap[0][0]
        assert "(fail-open)" in cap[0][0]
