"""Seta azul do T2: retorno bool, slot unico e /clear da MiMo (item 008).

Trava em testes:
  - `_dispatch_blue_arrow` devolve `False` no abort de payload vazio e `True`
    depois da emissao;
  - os delays da seta azul vem da tabela `_T2_BLUE_ARROW_DELAYS_MS` (MiMo com
    constantes proprias, Kimi e Qwen com as constantes KIMI), lida pelos dois
    dispatchers, e a flag after-clear so e consumida no ponto de emissao;
  - toda seta azul do T2 passa por `_on_single_button_blue_dispatch`, que so
    chama `_on_run_command` e marca o item quando o dispatcher devolve `True`;
  - o espelho do `/clear` no T2 publica `/clear ` (espaco final) quando a
    ocupacao e `mimo`, pelo clique e pelo step; Kimi e Qwen seguem com o
    `/clear` cru.
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.provider_router import Provider
from workflow_app.domain import CommandSpec, ModelName
from workflow_app.signal_bus import signal_bus

# Payload esperado da rota MiMo: builder nativo `/slash-executor` (item 006).
EXPECTED_MIMO_PAYLOAD = "/slash-executor --delegation-runtime=mimo /qa:prep "


class _Signals:
    """Captura seta azul, T1, T2 e toasts, sempre com disconnect no __exit__."""

    def __init__(self) -> None:
        self.blue: list[tuple[str, int]] = []
        self.t1: list[str] = []
        self.t2: list[str] = []
        self.toasts: list[tuple[str, str]] = []

    def _on_blue(self, payload: str, delay: int) -> None:
        self.blue.append((payload, delay))

    def _on_t1(self, cmd: str) -> None:
        self.t1.append(cmd)

    def _on_t2(self, cmd: str) -> None:
        self.t2.append(cmd)

    def _on_toast(self, msg: str, kind: str) -> None:
        self.toasts.append((msg, kind))

    def __enter__(self) -> "_Signals":
        signal_bus.kimi_blue_arrow_dispatched.connect(self._on_blue)
        signal_bus.run_command_in_terminal.connect(self._on_t1)
        signal_bus.run_command_in_workspace_terminal.connect(self._on_t2)
        signal_bus.toast_requested.connect(self._on_toast)
        return self

    def __exit__(self, *_exc) -> bool:
        signal_bus.kimi_blue_arrow_dispatched.disconnect(self._on_blue)
        signal_bus.run_command_in_terminal.disconnect(self._on_t1)
        signal_bus.run_command_in_workspace_terminal.disconnect(self._on_t2)
        signal_bus.toast_requested.disconnect(self._on_toast)
        return False

    def warnings(self) -> list[str]:
        return [msg for msg, kind in self.toasts if kind == "warning"]


def _build_widget(
    qapp,
    qtbot,
    monkeypatch,
    *,
    name: str = "/qa:prep",
    provider: Provider | None = Provider.MIMO,
    mimo_live: bool = True,
    pre_load=None,
) -> CommandQueueWidget:
    """Fixture de fila (mesma base de tests/test_mimo_t2_host_guard.py, sem
    importar dela). `provider=None` mantem o resolver real; `pre_load` recebe
    o widget e aplica patches que precisam valer ANTES do `load_pipeline`
    (os connects do `_make_item` capturam os metodos na criacao do item)."""
    _ = qapp
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    if mimo_live:
        # Worker MiMo vivo: visivel por intencao de boot E checkbox marcado
        # (`_is_mimo_worker_live`), para `_resolve_worker_occupancy()[0] == "mimo"`.
        w._worker_visible["mimo"] = True
        w._use_mimo_chk.setChecked(True)
    # O preflight de credencial depende do host; nao e o alvo aqui.
    monkeypatch.setattr(w, "_orch_preflight_main_credential", lambda *_a, **_k: None)
    if provider is not None:
        # O resolver e injetado na criacao do item: patch ANTES do load_pipeline.
        monkeypatch.setattr(w, "_resolve_item_provider", lambda _s: provider)
    if pre_load is not None:
        pre_load(w)
    w.load_pipeline([CommandSpec(name, ModelName.SONNET, position=1)])
    return w


def _count_run_command(w, monkeypatch) -> list[str]:
    """Substitui `_on_run_command` por um contador (usar ANTES do load)."""
    calls: list[str] = []
    monkeypatch.setattr(w, "_on_run_command", calls.append)
    return calls


@pytest.fixture()
def widget(qapp, qtbot, monkeypatch) -> CommandQueueWidget:
    return _build_widget(qapp, qtbot, monkeypatch)


# ─────────────────────── caso 1: retorno bool ──────────────────────────── #


def test_dispatch_blue_arrow_devolve_bool(widget):
    with _Signals() as sig:
        assert widget._dispatch_blue_arrow("   ") is False
    assert len(sig.warnings()) == 1
    assert sig.blue == []

    with _Signals() as sig:
        assert widget._dispatch_blue_arrow("/skill:qa:prep") is True
    assert len(sig.blue) == 1


# ─────────────────────── caso 2: tabela de delays ──────────────────────── #


def test_tabela_de_delays_t2(widget):
    assert widget._MIMO_BLUE_ARROW_DEFAULT_DELAY_MS == 1000
    assert widget._MIMO_AFTER_CLEAR_EXTRA_DELAY_MS == 2000
    assert widget._T2_BLUE_ARROW_DELAYS_MS["mimo"] == (1000, 2000)
    kimi_row = (
        widget._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS,
        widget._KIMI_AFTER_CLEAR_EXTRA_DELAY_MS,
    )
    assert widget._T2_BLUE_ARROW_DELAYS_MS["kimi"] == kimi_row
    assert widget._T2_BLUE_ARROW_DELAYS_MS["qwen"] == kimi_row


# ─────────────────────── caso 3: delay e consumo da flag ───────────────── #


def test_delay_mimo_e_consumo_da_flag_after_clear(widget, monkeypatch):
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)
    with _Signals() as sig:
        widget._dispatch_mimo_blue_arrow("/qa:prep")
    assert sig.blue == [(EXPECTED_MIMO_PAYLOAD, 1000)]

    widget._last_workspace_dispatch_was_clear = True
    with _Signals() as sig:
        widget._dispatch_mimo_blue_arrow("/qa:prep")
    assert sig.blue == [(EXPECTED_MIMO_PAYLOAD, 3000)]
    assert widget._last_workspace_dispatch_was_clear is False

    # Mesmo consumo no caminho Kimi (so emissao e flag, nao o retorno).
    monkeypatch.setattr(widget, "_resolve_worker_occupancy", lambda: ("kimi", ""))
    widget._last_workspace_dispatch_was_clear = True
    with _Signals() as sig:
        widget._dispatch_blue_arrow("/skill:qa:prep")
    assert len(sig.blue) == 1
    assert sig.blue[0][1] == 3000
    assert widget._last_workspace_dispatch_was_clear is False


# ─────────────────────── caso 4: dispatchers leem a tabela ─────────────── #


def test_os_dois_dispatchers_leem_a_tabela(widget, monkeypatch):
    # O monkeypatch restaura a tabela compartilhada da classe ao fim do teste.
    monkeypatch.setitem(widget._T2_BLUE_ARROW_DELAYS_MS, "mimo", (1234, 2000))
    monkeypatch.setitem(widget._T2_BLUE_ARROW_DELAYS_MS, "kimi", (4321, 2000))
    monkeypatch.setattr(widget, "_t2_pty_hosts_cli", lambda _cli: True)

    # Ocupacao mimo e exigida por `_ensure_t2_mimo_host`.
    monkeypatch.setattr(widget, "_resolve_worker_occupancy", lambda: ("mimo", ""))
    with _Signals() as sig:
        widget._dispatch_mimo_blue_arrow("/qa:prep")
    assert [delay for _p, delay in sig.blue] == [1234]

    # Ocupacao kimi explicita para o dispatch Kimi nao ler a linha "mimo".
    monkeypatch.setattr(widget, "_resolve_worker_occupancy", lambda: ("kimi", ""))
    with _Signals() as sig:
        widget._dispatch_blue_arrow("/skill:qa:prep")
    assert [delay for _p, delay in sig.blue] == [4321]


# ─────────────────────── casos 5 e 6: slot unico Kimi ──────────────────── #


def test_slot_unico_abort_nao_chama_run_command(qapp, qtbot, monkeypatch):
    holder: dict[str, list[str]] = {}

    def _pre_load(w):
        monkeypatch.setattr(w, "_dispatch_blue_arrow", lambda _p: False)
        holder["calls"] = _count_run_command(w, monkeypatch)

    w = _build_widget(
        qapp, qtbot, monkeypatch, provider=Provider.KIMI, pre_load=_pre_load
    )
    item = w._find_next_pending()
    item._on_exec_clicked()
    assert holder["calls"] == []
    # Marcacao incondicional de `_on_kimi_clicked` (decisao de nao corrigir
    # neste loop, registrada no item 008).
    assert item._is_sent is True


def test_slot_unico_sucesso_chama_run_command_uma_vez(qapp, qtbot, monkeypatch):
    holder: dict[str, list[str]] = {}

    def _pre_load(w):
        holder["calls"] = _count_run_command(w, monkeypatch)

    w = _build_widget(
        qapp, qtbot, monkeypatch, provider=Provider.KIMI, pre_load=_pre_load
    )
    item = w._find_next_pending()
    with _Signals() as sig:
        item._on_exec_clicked()
    assert len(sig.blue) == 1
    assert len(holder["calls"]) == 1


# ─────────────────────── caso 7: slot unico MiMo ───────────────────────── #


@pytest.mark.parametrize("host", [True, False], ids=["host-presente", "host-ausente"])
def test_slot_unico_mimo_clique(qapp, qtbot, monkeypatch, host):
    holder: dict[str, list[str]] = {}

    def _pre_load(w):
        holder["calls"] = _count_run_command(w, monkeypatch)

    w = _build_widget(
        qapp, qtbot, monkeypatch, provider=Provider.MIMO, pre_load=_pre_load
    )
    monkeypatch.setattr(w, "_t2_pty_hosts_cli", lambda _cli: host)
    item = w._find_next_pending()
    if not host:
        w._last_workspace_dispatch_was_clear = True
    with _Signals() as sig:
        item._on_exec_clicked()
    if host:
        assert sig.blue == [(EXPECTED_MIMO_PAYLOAD, 1000)]
        assert len(holder["calls"]) == 1
        assert item.is_pending_run() is False
    else:
        assert sig.blue == []
        assert holder["calls"] == []
        assert item.is_pending_run() is True
        # Aborto nao consome a flag after-clear.
        assert w._last_workspace_dispatch_was_clear is True


# ─────────────────────── caso 8: runtime invalido ──────────────────────── #


def test_slot_unico_runtime_invalido_levanta(widget):
    item = widget._find_next_pending()
    with pytest.raises(ValueError):
        widget._on_single_button_blue_dispatch(item, "/qa:prep", runtime="grok")


# ─────────────────────── casos 9 e 10: /clear da MiMo ──────────────────── #


def test_clear_mimo_clique_publica_com_espaco(widget):
    with _Signals() as sig:
        widget._mirror_clear_to_workspace_if_kimi_checked("/clear")
    assert sig.t2 == ["/clear "]
    assert widget._last_workspace_dispatch_was_clear is True


def test_clear_mimo_step_publica_com_espaco(qapp, qtbot, monkeypatch):
    w = _build_widget(qapp, qtbot, monkeypatch, name="/clear", provider=None)
    with _Signals() as sig:
        w._on_step_btn_clicked()
    assert sig.t1 == ["/clear"]
    assert sig.t2 == ["/clear "]


# ─────────────────────── caso 11: nao regressao Kimi e Qwen ────────────── #


@pytest.mark.parametrize("gatilho", ["clique", "step"])
@pytest.mark.parametrize("worker", ["kimi", "qwen"])
def test_clear_kimi_qwen_segue_cru(qapp, qtbot, monkeypatch, worker, gatilho):
    w = _build_widget(
        qapp, qtbot, monkeypatch, name="/clear", provider=None, mimo_live=False
    )
    if worker == "kimi":
        w._use_kimi_chk.setChecked(True)
    else:
        w._use_qwen_chk.setChecked(True)
    with _Signals() as sig:
        if gatilho == "clique":
            w._mirror_clear_to_workspace_if_kimi_checked("/clear")
        else:
            w._on_step_btn_clicked()
    assert sig.t2 == ["/clear"]
