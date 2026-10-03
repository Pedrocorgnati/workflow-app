"""Host guard fail-closed da MiMo (T2) e rota propria da seta azul (item 007).

Trava em testes:
  - `_ensure_t2_mimo_host` e FAIL-CLOSED: so libera quando a ocupacao viva do
    T2 e `mimo` E o PTY do T2 hospeda um processo `mimo`. Qualquer outro estado
    bloqueia com toast de warning (contraste explicito com o fail-open do guard
    Grok, que libera quando o PTY nao e inspecionavel);
  - o clique (`_on_exec_clicked`) e o step (`_on_step_btn_clicked`) de um item
    `Provider.MIMO` usam a rota propria (`_on_mimo_clicked` ->
    `_dispatch_mimo_blue_arrow`), nunca caem no T1, e so marcam o item como
    enviado depois do envio confirmado;
  - recusa de "!`" no payload slash da MiMo;
  - nao regressao de KIMI e QWEN pelo caminho antigo (`_on_kimi_clicked` com
    marcacao incondicional).
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.provider_router import Provider
from workflow_app.domain import CommandSpec, ModelName
from workflow_app.signal_bus import signal_bus

# Payload esperado da rota MiMo: builder nativo `/slash-executor` (item 006),
# com UM espaco final e sem espaco inicial (contrato do CLI mimocode).
EXPECTED_PAYLOAD = "/slash-executor --delegation-runtime=mimo /qa:prep "
EXPECTED_DELAY_MS = 1_000


class _Signals:
    """Captura os sinais de dispatch/toast, sempre com disconnect no finally."""

    def __init__(self) -> None:
        self.blue: list[tuple[str, int]] = []
        self.t1: list[str] = []
        self.toasts: list[tuple[str, str]] = []

    def _on_blue(self, payload: str, delay: int) -> None:
        self.blue.append((payload, delay))

    def _on_t1(self, cmd: str) -> None:
        self.t1.append(cmd)

    def _on_toast(self, msg: str, kind: str) -> None:
        self.toasts.append((msg, kind))

    def __enter__(self) -> "_Signals":
        signal_bus.kimi_blue_arrow_dispatched.connect(self._on_blue)
        signal_bus.run_command_in_terminal.connect(self._on_t1)
        signal_bus.toast_requested.connect(self._on_toast)
        return self

    def __exit__(self, *_exc) -> bool:
        signal_bus.kimi_blue_arrow_dispatched.disconnect(self._on_blue)
        signal_bus.run_command_in_terminal.disconnect(self._on_t1)
        signal_bus.toast_requested.disconnect(self._on_toast)
        return False

    def warnings(self) -> list[str]:
        return [msg for msg, kind in self.toasts if kind == "warning"]


def _build_widget(qapp, qtbot, monkeypatch, *, name: str = "/qa:prep") -> CommandQueueWidget:
    """Fixture de fila com o Worker MiMo vivo (mesma base de
    tests/test_mimo_main_dispatch.py, sem importar dela)."""
    _ = qapp
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    # Worker MiMo vivo: visivel por intencao de boot E checkbox marcado
    # (`_is_mimo_worker_live`), para `_resolve_worker_occupancy()[0] == "mimo"`.
    w._worker_visible["mimo"] = True
    w._use_mimo_chk.setChecked(True)
    # O preflight de credencial depende do host; nao e o alvo aqui.
    monkeypatch.setattr(w, "_orch_preflight_main_credential", lambda *_a, **_k: None)
    # O resolver e injetado na criacao do item: patch ANTES do load_pipeline.
    monkeypatch.setattr(w, "_resolve_item_provider", lambda _s: Provider.MIMO)
    w.load_pipeline([CommandSpec(name, ModelName.SONNET, position=1)])
    return w


@pytest.fixture()
def widget(qapp, qtbot, monkeypatch) -> CommandQueueWidget:
    return _build_widget(qapp, qtbot, monkeypatch)


def _mimo_item(qtbot) -> CommandItemWidget:
    """Item isolado roteado a MiMo (padrao de `_qwen_item` em
    tests/test_command_item_widget.py)."""
    spec = CommandSpec("/qa:prep", ModelName.SONNET, position=0)
    item = CommandItemWidget(spec, provider_resolver=lambda _s: Provider.MIMO)
    qtbot.addWidget(item)
    item.refresh_provider()
    return item


# ─────────────────────── guard: estados que bloqueiam ──────────────────── #


def test_headless_sem_panel_t2_nem_pty(widget):
    """Sem MainWindow nao ha painel T2 nem PTY: a sonda devolve None."""
    assert widget._find_t2_output_panel() is None
    assert widget._t2_pty_hosts_cli("mimo") is None


def test_pty_nao_inspecionavel_bloqueia(widget, monkeypatch):
    """FAIL-CLOSED: sonda None bloqueia; o guard Grok no mesmo estado libera."""
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: None)
    with _Signals() as sig:
        assert widget._ensure_t2_mimo_host() is False
    assert len(sig.warnings()) == 1
    assert sig.blue == []
    assert sig.t1 == []

    # Contraste explicito (NAO copiar o fail-open do Grok): com o PTY do T3
    # nao inspecionavel (None) o guard Grok trata como liberado e devolve True.
    monkeypatch.setattr(widget, "_t3_pty_hosts_cli", lambda _cli: None)
    widget._codex_t3_available = True
    monkeypatch.setattr(widget, "_resolve_worker_occupancy", lambda: ("", "grok"))
    assert widget._ensure_t3_grok_host() is True


def test_processo_mimo_ausente_bloqueia(widget, monkeypatch):
    """PTY inspecionavel mas sem o processo mimo: bloqueia com toast."""
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: False)
    with _Signals() as sig:
        assert widget._ensure_t2_mimo_host() is False
    assert len(sig.warnings()) == 1
    assert sig.blue == []
    assert sig.t1 == []


def test_ocupacao_errada_bloqueia(widget, monkeypatch):
    """T2 ocupado pelo Kimi (MiMo desmarcada) bloqueia mesmo com o CLI no PTY."""
    widget._use_mimo_chk.setChecked(False)
    widget._use_kimi_chk.setChecked(True)
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    with _Signals() as sig:
        assert widget._ensure_t2_mimo_host() is False
    assert len(sig.warnings()) == 1


# ─────────────────────── guard: estado que libera ──────────────────────── #


def test_host_presente_libera_sem_toast(widget, monkeypatch):
    """Ocupacao mimo + processo mimo no PTY: libera e nao emite toast."""
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    with _Signals() as sig:
        assert widget._ensure_t2_mimo_host() is True
    assert sig.toasts == []


# ─────────────────────── clique per-item (rota propria) ────────────────── #


def test_clique_com_host_ausente_bloqueia_e_deixa_pendente(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: False)
    item = widget._find_next_pending()
    with _Signals() as sig:
        item._on_exec_clicked()
    assert sig.blue == []
    assert sig.t1 == []
    assert item.is_pending_run() is True
    assert len(sig.warnings()) == 1


def test_clique_com_host_presente_envia_e_marca(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    item = widget._find_next_pending()
    with _Signals() as sig:
        item._on_exec_clicked()
    assert sig.blue == [(EXPECTED_PAYLOAD, EXPECTED_DELAY_MS)]
    assert sig.t1 == []
    assert item.is_pending_run() is False


def test_payload_com_shell_expansion_e_recusado(qapp, qtbot, monkeypatch):
    """Payload slash com "!`" e recusado: nada sai e o toast cita "!`"."""
    w = _build_widget(qapp, qtbot, monkeypatch, name="/qa:prep !`printf X`")
    monkeypatch.setattr(w, "_t2_pty_hosts_cli", lambda _cli: True)
    item = w._find_next_pending()
    with _Signals() as sig:
        item._on_exec_clicked()
    assert sig.blue == []
    assert sig.t1 == []
    assert item.is_pending_run() is True
    assert len(sig.warnings()) == 1
    assert "!`" in sig.warnings()[0]


# ─────────────────────── step (paridade com o clique) ──────────────────── #


def test_step_com_host_presente_envia_e_marca(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    item = widget._find_next_pending()
    with _Signals() as sig:
        widget._on_step_btn_clicked()
    assert sig.blue == [(EXPECTED_PAYLOAD, EXPECTED_DELAY_MS)]
    assert sig.t1 == []
    assert item.is_pending_run() is False
    assert sig.toasts == []


def test_step_com_host_ausente_nao_envia(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: False)
    item = widget._find_next_pending()
    with _Signals() as sig:
        widget._on_step_btn_clicked()
    assert sig.blue == []
    assert sig.t1 == []
    assert item.is_pending_run() is True
    assert len(sig.warnings()) == 1


def _spy_lifecycle(widget, monkeypatch) -> list[str]:
    """Registra as chamadas de lifecycle do step sem alterar o desfecho."""
    calls: list[str] = []
    begin = widget._begin_rocksmash_subphase
    record = widget._record_loop_dispatch

    def _begin(spec):
        calls.append("begin_rocksmash_subphase")
        return begin(spec)

    def _record(spec, provider):
        calls.append("record_loop_dispatch")
        return record(spec, provider)

    monkeypatch.setattr(widget, "_begin_rocksmash_subphase", _begin)
    monkeypatch.setattr(widget, "_record_loop_dispatch", _record)
    return calls


def test_step_com_host_ausente_nao_abre_lifecycle(widget, monkeypatch):
    """Recusa do host guard acontece ANTES do lifecycle: nenhuma subfase
    rocksmash vai para `in_flight` e nenhum `item_dispatched` fantasma nasce
    (review-executed item 007, finding step-gate-apos-lifecycle)."""
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: False)
    calls = _spy_lifecycle(widget, monkeypatch)
    with _Signals() as sig:
        widget._on_step_btn_clicked()
    assert calls == []
    assert sig.blue == []
    assert len(sig.warnings()) == 1


def test_step_com_payload_recusado_nao_abre_lifecycle(qapp, qtbot, monkeypatch):
    """Recusa do builder ("!`") tambem precede o lifecycle no step."""
    w = _build_widget(qapp, qtbot, monkeypatch, name="/qa:prep !`printf X`")
    monkeypatch.setattr(w, "_t2_pty_hosts_cli", lambda _cli: True)
    calls = _spy_lifecycle(w, monkeypatch)
    item = w._find_next_pending()
    with _Signals() as sig:
        w._on_step_btn_clicked()
    assert calls == []
    assert sig.blue == []
    assert item.is_pending_run() is True
    assert len(sig.warnings()) == 1


def test_step_com_host_presente_abre_lifecycle_uma_vez(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    calls = _spy_lifecycle(widget, monkeypatch)
    with _Signals() as sig:
        widget._on_step_btn_clicked()
    assert calls == ["begin_rocksmash_subphase", "record_loop_dispatch"]
    assert sig.blue == [(EXPECTED_PAYLOAD, EXPECTED_DELAY_MS)]


# ─────────────────────── item isolado (sem queue widget) ───────────────── #


def test_item_isolado_emite_rota_propria_mimo(qtbot):
    """Provider.MIMO emite run_in_mimo_terminal_requested e NAO marca sozinho."""
    item = _mimo_item(qtbot)
    mimo: list[str] = []
    kimi: list[str] = []
    t1: list[str] = []
    codex: list[str] = []
    item.run_in_mimo_terminal_requested.connect(mimo.append)
    item.run_in_kimi_terminal_requested.connect(kimi.append)
    item.run_in_terminal_requested.connect(t1.append)
    item.run_in_codex_terminal_requested.connect(codex.append)
    try:
        item._on_exec_clicked()
    finally:
        item.run_in_mimo_terminal_requested.disconnect(mimo.append)
        item.run_in_kimi_terminal_requested.disconnect(kimi.append)
        item.run_in_terminal_requested.disconnect(t1.append)
        item.run_in_codex_terminal_requested.disconnect(codex.append)
    assert mimo == ["/qa:prep"]
    assert kimi == []
    assert t1 == []
    assert codex == []
    # O mark-as-sent e do slot da fila (depois do envio confirmado).
    assert item.is_pending_run() is True


# ─────────────────────── nao regressao KIMI e QWEN ─────────────────────── #


@pytest.mark.parametrize("provider", [Provider.KIMI, Provider.QWEN])
def test_kimi_qwen_continuam_pelo_caminho_antigo(qtbot, provider):
    """KIMI/QWEN seguem por _on_kimi_clicked com marcacao incondicional."""
    spec = CommandSpec("/qa:prep", ModelName.SONNET, position=0)
    item = CommandItemWidget(spec, provider_resolver=lambda _s: provider)
    qtbot.addWidget(item)
    item.refresh_provider()
    kimi: list[str] = []
    t1: list[str] = []
    item.run_in_kimi_terminal_requested.connect(kimi.append)
    item.run_in_terminal_requested.connect(t1.append)
    try:
        item._on_exec_clicked()
    finally:
        item.run_in_kimi_terminal_requested.disconnect(kimi.append)
        item.run_in_terminal_requested.disconnect(t1.append)
    assert len(kimi) == 1
    assert kimi[0].startswith("/skill:qa:prep")
    assert t1 == []
    assert item.is_pending_run() is False
