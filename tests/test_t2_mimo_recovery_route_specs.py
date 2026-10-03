"""Casos minimos do ST002 do Item 009 do loop 10-03-systemforge-mimo-llm-paralela.

O item fecha os dois caminhos do T2 que hoje ignoram a MiMo: o recovery do canal
`workspace` (`_on_request_recovery_command`) e o `route_specs` da insercao
LLM-aware (`_publish_insertion_llm_aware_report`), somados ao ramo
`llm == "mimo"` de `CommandQueueWidget.render_for_llm`. Este arquivo e escrito
ANTES da mudanca de codigo (baseline red do ST003) e fica verde no ST005.

Casos cobertos:
  1. recovery MiMo com host presente publica exatamente uma vez o payload
     `/slash-executor --delegation-runtime=mimo --recovery-mode ...` (um espaco
     final) com delay 1000, sem `/skill:slash-executor`, sem
     `--delegation-runtime=kimi` e sem `terminal_force_failed`;
  2. recovery MiMo com host ausente nao publica nada e termina em
     `("workspace", "BLOCKED")` com pelo menos um toast `warning`
     (host guard fail-closed + `_reject_recovery_command`);
  3. nao regressao do recovery Kimi e Qwen (parametrizado por ocupante), com o
     payload de hoje e nenhuma presenca de `--delegation-runtime=`;
  4. `route_specs` do T2 segue o ocupante vivo (kimi, qwen, mimo) na insercao
     (parametrizado), com o payload colado no T2 via
     `paste_text_in_workspace_terminal`;
  5. par T2 vazio usa `channel_llm.t2_fallback_default` decidido por
     `feature_flags.mimo_v1_enabled()` (parametrizado no flag);
  6. ramo `mimo` de `render_for_llm` em chamadas diretas: embrulho do slash
     conhecido, reescrita de `/skill:`, abort de comando inexistente e de "!`",
     `--recovery-mode` no slug de recovery, passthrough idempotente do
     `/slash-executor --delegation-runtime=mimo`, metodo puro (sem toast) e
     paridade byte a byte entre `mode="insert"` e `mode="dispatch"`.

Fixtures copiadas (sem importar) de tests/test_command_queue_recovery.py
(`widget`, `ctx_file`, `_Recorder`/`rec`) e de tests/test_insertion_llm_routing.py
(`_new_window`, `_set_route`, `_capture`). Worker MiMo vivo segue o padrao de
tests/test_mimo_t2_host_guard.py. Nenhum teste le ou grava `worker/t2_selected`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.config import feature_flags
from workflow_app.signal_bus import signal_bus

# ─────────────────────── fixtures copiadas (sem importar) ─────────────────── #


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture()
def ctx_file(tmp_path: Path) -> str:
    """Snapshot diagnostico valido (existe em disco + termina em .md)."""
    p = tmp_path / "interactive-BLOCKED-snapshot.md"
    p.write_text("# recovery snapshot\n", encoding="utf-8")
    return str(p)


class _Recorder:
    """Coleta emissoes dos signals de dispatch/feedback e desconecta no fim."""

    def __init__(self) -> None:
        self.interactive: list[str] = []
        self.xterm: list[str] = []
        self.kimi_blue: list[tuple[str, int]] = []
        self.toast: list[tuple[str, str]] = []
        self.force_failed: list[tuple[str, str]] = []
        self._wires = [
            (signal_bus.run_command_in_terminal, self._on_t1),
            (signal_bus.run_command_in_workspace_xterm, self._on_t3),
            (signal_bus.kimi_blue_arrow_dispatched, self._on_blue),
            (signal_bus.toast_requested, self._on_toast),
            (signal_bus.terminal_force_failed, self._on_failed),
        ]
        for sig, slot in self._wires:
            sig.connect(slot)

    def _on_t1(self, cmd: str) -> None:
        self.interactive.append(cmd)

    def _on_t3(self, cmd: str) -> None:
        self.xterm.append(cmd)

    def _on_blue(self, prompt: str, delay: int) -> None:
        self.kimi_blue.append((prompt, delay))

    def _on_toast(self, msg: str, kind: str) -> None:
        self.toast.append((msg, kind))

    def _on_failed(self, channel: str, reason: str) -> None:
        self.force_failed.append((channel, reason))

    def disconnect(self) -> None:
        for sig, slot in self._wires:
            sig.disconnect(slot)


@pytest.fixture()
def rec() -> _Recorder:
    r = _Recorder()
    try:
        yield r
    finally:
        r.disconnect()


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _set_route(win, *, t1, t2, t3):
    radios = (win._chk_route_t1, win._chk_route_t2, win._chk_route_t3)
    states = (t1, t2, t3)
    if sum(states) == 1:
        radios[states.index(True)].setChecked(True)
        return
    win._terminal_route_group.setExclusive(False)
    for radio, checked in zip(radios, states, strict=True):
        radio.setChecked(checked)
    win._terminal_route_group.setExclusive(True)


def _capture(signal):
    """Captura emissoes de um signal; devolve (lista, disconnect).

    Igual a `_capture` de tests/test_insertion_llm_routing.py, so que o slot
    fica guardado para ser desconectado no `finally` (regra do contrato).
    """
    out: list = []
    slot = lambda *a: out.append(a)  # noqa: E731
    signal.connect(slot)
    return out, lambda: signal.disconnect(slot)


def _stop_modal_timer(win) -> None:
    timer = getattr(win, "_modal_check_timer", None)
    if timer is not None:
        timer.stop()


# ──────────────────────── helpers do ramo MiMo ────────────────────────────── #

_REVIEW = "/corgly:class-review"
_SKILL_PREFIX = "/skill:corgly:class-review"
_MISSING = "/nao-existe:xyz"
_SHELL_EXPANSION = "/corgly:class-review !`ls`"
_RECOVERY_SLASH = "/tools:listener-recovery --channel workspace"
_PASSTHROUGH = "/slash-executor --delegation-runtime=mimo /qa:prep "
_PASSTHROUGH_SHELL = "/slash-executor --delegation-runtime=mimo /qa:prep !`ls`"

# Todas as entradas diretas do caso 6 (variedades de texto usadas em (g)).
_MIMO_RENDER_INPUTS = (
    _REVIEW,
    _SKILL_PREFIX,
    _MISSING,
    _SHELL_EXPANSION,
    _RECOVERY_SLASH,
    _PASSTHROUGH,
    _PASSTHROUGH_SHELL,
)


def _render_mimo(text: str, *, mode: str = "insert"):
    return CommandQueueWidget.render_for_llm(
        text, "mimo", listener_channel="workspace", mode=mode
    )


def _enable_live_mimo_worker(w) -> None:
    """Worker MiMo vivo: visivel por intencao de boot E checkbox marcado."""
    w._worker_visible["mimo"] = True
    w._use_mimo_chk.setChecked(True)


# ──────────────────── caso 1 e 2: recovery MiMo (host guard) ──────────────── #


class TestRecoveryMimoBlueArrow:
    def test_t2_mimo_recovery_dispatches_native_executor_payload(
        self, widget, rec, ctx_file, monkeypatch
    ):
        """Caso 1: host presente -> payload MiMo nativo, exatamente uma vez."""
        _enable_live_mimo_worker(widget)
        monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)

        widget._on_request_recovery_command("workspace", "EXIT_NONZERO", ctx_file)

        assert len(rec.kimi_blue) == 1
        payload, delay = rec.kimi_blue[0]
        assert payload == (
            f"/slash-executor --delegation-runtime=mimo --recovery-mode "
            f"/tools:listener-recovery --channel workspace --reason EXIT_NONZERO "
            f"--context-file {ctx_file} "
        )
        assert delay == 1000
        assert "/skill:slash-executor" not in payload
        assert "--delegation-runtime=kimi" not in payload
        assert rec.force_failed == []
        assert rec.interactive == []
        assert rec.xterm == []

    def test_t2_mimo_recovery_host_absent_is_blocked(
        self, widget, rec, ctx_file, monkeypatch
    ):
        """Caso 2: host ausente -> nada publicado, canal BLOCKED + warning."""
        _enable_live_mimo_worker(widget)
        monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: False)

        widget._on_request_recovery_command("workspace", "EXIT_NONZERO", ctx_file)

        assert rec.kimi_blue == []
        assert rec.interactive == []
        assert rec.xterm == []
        assert rec.force_failed == [("workspace", "BLOCKED")]
        assert any(kind == "warning" for _msg, kind in rec.toast)


# ────────────────── caso 3: nao regressao Kimi/Qwen no recovery ───────────── #


class TestRecoveryKimiQwenUnchanged:
    @pytest.mark.parametrize("occ", ["kimi", "qwen"])
    def test_t2_kimi_qwen_recovery_payload_is_unchanged(
        self, widget, rec, ctx_file, monkeypatch, occ
    ):
        """Caso 3: ocupacao fixada; payload de hoje, sem --delegation-runtime=."""
        monkeypatch.setattr(widget, "_resolve_worker_occupancy", lambda: (occ, ""))

        widget._on_request_recovery_command("workspace", "EXIT_NONZERO", ctx_file)

        assert len(rec.kimi_blue) == 1
        payload, delay = rec.kimi_blue[0]
        assert delay == 1000
        if occ == "kimi":
            assert payload == (
                f"/skill:slash-executor --recovery-mode "
                f"/tools:listener-recovery --channel workspace "
                f"--reason EXIT_NONZERO --context-file {ctx_file}"
            )
        else:
            assert payload.startswith("/slash-executor")
            assert "--recovery-mode /tools:listener-recovery" in payload
        assert "--delegation-runtime=" not in payload
        assert rec.force_failed == []
        assert rec.interactive == []
        assert rec.xterm == []


# ─────────────── casos 4 e 5: route_specs com ocupante vivo ───────────────── #


class TestRouteSpecsLiveOccupancy:
    @pytest.mark.parametrize("occ", ["kimi", "qwen", "mimo"])
    def test_t2_payload_follows_live_occupancy(self, qapp, qtbot, monkeypatch, occ):
        """Caso 4: o payload colado no T2 segue o ocupante vivo do par T2."""
        win = _new_window(qtbot)
        _set_route(win, t1=False, t2=True, t3=False)
        monkeypatch.setattr(
            win._command_queue, "_resolve_worker_occupancy", lambda: (occ, "")
        )
        pastes, drop_pastes = _capture(signal_bus.paste_text_in_workspace_terminal)
        try:
            report = win._publish_insertion_llm_aware_report(_REVIEW)
        finally:
            drop_pastes()
            _stop_modal_timer(win)

        assert report.accepted == ("T2",)
        assert len(pastes) == 1
        payload = pastes[0][0]
        if occ == "kimi":
            assert payload.startswith("/skill:slash-executor /corgly:class-review")
        elif occ == "qwen":
            assert payload.startswith("/slash-executor /corgly:class-review")
        else:
            assert payload == "/slash-executor --delegation-runtime=mimo /corgly:class-review "
        assert "--delegation-runtime=kimi" not in payload

    @pytest.mark.parametrize("flag", [True, False])
    def test_t2_empty_pair_uses_t2_fallback_default(
        self, qapp, qtbot, monkeypatch, flag
    ):
        """Caso 5: par vazio -> fallback decidido por mimo_v1_enabled()."""
        win = _new_window(qtbot)
        _set_route(win, t1=False, t2=True, t3=False)
        monkeypatch.setattr(
            win._command_queue, "_resolve_worker_occupancy", lambda: ("", "")
        )
        monkeypatch.setattr(feature_flags, "mimo_v1_enabled", lambda: flag)
        pastes, drop_pastes = _capture(signal_bus.paste_text_in_workspace_terminal)
        try:
            report = win._publish_insertion_llm_aware_report(_REVIEW)
        finally:
            drop_pastes()
            _stop_modal_timer(win)

        assert report.accepted == ("T2",)
        assert len(pastes) == 1
        payload = pastes[0][0]
        if flag:
            assert payload == "/slash-executor --delegation-runtime=mimo /corgly:class-review "
        else:
            assert payload.startswith("/skill:slash-executor /corgly:class-review")
        assert "--delegation-runtime=kimi" not in payload


# ─────────────────── caso 6: render_for_llm, ramo mimo ────────────────────── #


class TestRenderForLlmMimoBranch:
    def test_known_slash_wraps_with_mimo_executor(self):
        """(a) slash conhecido sai embrulhado com um espaco final."""
        r = _render_mimo(_REVIEW)
        assert r.abort_reason is None
        assert r.text == "/slash-executor --delegation-runtime=mimo /corgly:class-review "

    def test_skill_prefix_is_rewritten_by_builder(self):
        """(b) `/skill:` sai do dialeto `/skill:` e vira executor MiMo."""
        r = _render_mimo(_SKILL_PREFIX)
        assert r.abort_reason is None
        assert r.text is not None
        assert r.text.startswith("/slash-executor --delegation-runtime=mimo")

    def test_unknown_command_aborts_citing_slug(self):
        """(c) comando inexistente aborta citando o slug, sem texto."""
        r = _render_mimo(_MISSING)
        assert r.text is None
        assert r.abort_reason is not None
        assert "nao-existe:xyz" in r.abort_reason

    def test_shell_expansion_in_slash_aborts_with_mimo_prefix(self):
        """(d) "!`" no texto slash vira abort vindo do builder (`MiMo: ...`)."""
        r = _render_mimo(_SHELL_EXPANSION)
        assert r.text is None
        assert r.abort_reason is not None
        assert r.abort_reason.startswith("MiMo:")

    def test_recovery_slug_gets_recovery_mode_flag(self):
        """(e) o slug de recovery carrega `--recovery-mode` no payload."""
        r = _render_mimo(_RECOVERY_SLASH)
        assert r.abort_reason is None
        assert r.text is not None
        assert "--recovery-mode /tools:listener-recovery" in r.text

    def test_native_executor_passthrough_is_idempotent(self):
        """(f) entrada que ja e o executor MiMo volta byte a byte igual."""
        r = _render_mimo(_PASSTHROUGH)
        assert r.abort_reason is None
        assert r.text == _PASSTHROUGH

    def test_no_toast_in_any_variant(self):
        """(g) o metodo e puro: nenhuma variante emite toast_requested."""
        toasts, drop_toasts = _capture(signal_bus.toast_requested)
        try:
            for text in _MIMO_RENDER_INPUTS:
                _render_mimo(text)
            _render_mimo(_REVIEW, mode="dispatch")
        finally:
            drop_toasts()
        assert toasts == []

    @pytest.mark.parametrize("text", [_REVIEW, _SKILL_PREFIX, _RECOVERY_SLASH, _PASSTHROUGH])
    def test_no_kimi_markers_in_rendered_text(self, text):
        """(h) variante com texto nao nulo nunca carrega marcadores Kimi."""
        r = _render_mimo(text)
        assert r.text is not None
        assert "/skill:slash-executor" not in r.text
        assert "--delegation-runtime=kimi" not in r.text

    def test_passthrough_with_shell_expansion_aborts_without_toast(self):
        """(i) passthrough com "!`" aborta (nao vazio) e nao toasta."""
        toasts, drop_toasts = _capture(signal_bus.toast_requested)
        try:
            r = _render_mimo(_PASSTHROUGH_SHELL)
        finally:
            drop_toasts()
        assert r.text is None
        assert r.abort_reason
        assert toasts == []

    def test_dispatch_mode_matches_insert_mode_byte_for_byte(self):
        """(j) `mode="dispatch"` devolve o mesmo payload da variante (a)."""
        insert = _render_mimo(_REVIEW, mode="insert")
        dispatch = _render_mimo(_REVIEW, mode="dispatch")
        assert insert.text == "/slash-executor --delegation-runtime=mimo /corgly:class-review "
        assert dispatch.abort_reason is None
        assert dispatch.text == insert.text
