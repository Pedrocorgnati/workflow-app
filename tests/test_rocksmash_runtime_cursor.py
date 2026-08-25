"""Fiacao de RUNTIME do cursor de subfase e do desfecho de item.

`test_rocksmash_cursor.py` (Task 20, primeira metade) ja prova que o PLANO de
retomada le o sidecar corretamente. O que faltava era o outro lado: em
execucao real ninguem escrevia esse sidecar. `init_state`, `begin_subphase` e
`mark_subphase` tinham zero chamador em `src/` — so testes os exercitavam —,
entao o arquivo nascia vazio em toda execucao de verdade e o cursor decidia
sempre a mesma coisa (rodar o bloco inteiro) porque nunca havia progresso para
ler. Pelo mesmo motivo `item_completed` e `item_failed` estavam instrumentados
e mudos: seus unicos gatilhos eram `signal_bus.command_completed` e
`command_failed`, sinais sem um `.emit()` em `src/`.

A ponte esta travada em dois arquivos, de proposito. O lado da EXPANSAO
(sidecar criado em execucao, contexto viajando em cada spec) mora em
`test_rocksmash_cursor.py`, que e o deliverable declarado da Task 20. Aqui fica
o lado do RUNTIME, que nao cabe naquele arquivo porque exige o widget:

* o cursor liga por `from_specs`, inclusive depois de um restore de snapshot;
* `in_flight` e gravado ANTES do dispatch e o desfecho SO apos retorno
  autoritativo do canal;
* Regra L14.7: despachar nao conclui. Um item colado no terminal e que nunca
  volta verde nao produz `item_completed`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app import dispatch_telemetry
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.loop_rocksmash_expander import (
    ROCKSMASH_CONTEXT_MODE,
    build_loop_rocksmash_specs,
)
from workflow_app.command_queue.rocksmash_cursor import RocksmashRuntimeCursor
from workflow_app.daily_loop.rocksmash_state import (
    read_state,
    state_path,
)
from workflow_app.domain import CommandSpec, LoopExecutionContext, ModelName
from workflow_app.signal_bus import signal_bus
from workflow_app.telemetry import lifecycle_sink

# ─────────────────────────────────────────────────────────── fixtures ── #


@pytest.fixture()
def sink_tmp(tmp_path, monkeypatch) -> Path:
    """Aponta o sink de lifecycle para `tmp_path` (o override vence o guard)."""
    monkeypatch.setenv(lifecycle_sink.SINK_DIR_ENV, str(tmp_path))
    lifecycle_sink._reset_for_tests()
    yield tmp_path
    lifecycle_sink._reset_for_tests()


@pytest.fixture()
def dispatch_tmp(tmp_path, monkeypatch) -> Path:
    """Isola o JSONL de dispatch: `_publish_to_terminal` grava nele."""
    path = tmp_path / "dispatch-telemetry.jsonl"
    monkeypatch.setattr(dispatch_telemetry, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(dispatch_telemetry, "_JSONL_PATH", path)
    dispatch_telemetry._reset_for_tests()
    yield path
    dispatch_telemetry._reset_for_tests()


def _config(n: int = 2, *, legacy_two_step: bool = False) -> dict:
    daily_loop: dict = {
        "slug": "08-24-rocksmash",
        "buckets": [
            {
                "id": "T-opus-high",
                "model": "opus",
                "effort": "high",
                "items": [
                    {
                        "id": f"{i:03d}",
                        "kind": "iteration",
                        "task_path": f"tasks/items/task-{i:03d}.md",
                    }
                    for i in range(1, n + 1)
                ],
            }
        ],
    }
    if legacy_two_step:
        daily_loop["rocksmash_legacy_two_step"] = True
    return {"kind": "daily-loop", "daily_loop": daily_loop}


def _loop(tmp_path: Path, cfg: dict, nome: str = "loop") -> Path:
    root = tmp_path / nome
    (root / "tasks" / "items").mkdir(parents=True, exist_ok=True)
    for bucket in cfg["daily_loop"]["buckets"]:
        for item in bucket["items"]:
            (root / item["task_path"]).write_text("# task\n", encoding="utf-8")
    (root / "_LOOP-CONFIG.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


def _subfase_specs(specs) -> list:
    return [s for s in specs if s.name.startswith("/loop-rocksmash:")
            and not s.name.startswith(("/loop-rocksmash:prepare", "/loop-rocksmash:rename"))]


def _eventos() -> list[dict]:
    return lifecycle_sink.read_events()


def _tipos() -> list[str]:
    return [e.get("event_type") for e in _eventos()]


# ────────────────────────────────────────────── bind e escrita do cursor ── #


class TestBindDoCursor:
    def test_from_specs_recupera_o_binding_da_fila(self, tmp_path: Path) -> None:
        cfg = _config(1)
        root = _loop(tmp_path, cfg)
        specs = build_loop_rocksmash_specs(cfg, root)

        cursor = RocksmashRuntimeCursor.from_specs(specs)
        assert cursor is not None
        assert cursor.loop_root == root

    def test_fila_sem_prepare_nao_liga_cursor(self) -> None:
        specs = [CommandSpec("/loop:iteraction:execute-task a/b.md", ModelName.SONNET)]
        assert RocksmashRuntimeCursor.from_specs(specs) is None

    def test_config_ilegivel_desliga_o_cursor(self, tmp_path: Path) -> None:
        """Sem a config nao da para validar o `config_hash`, e escrever sem
        validar e o unico erro que o sidecar nao pode cometer."""
        specs = [
            CommandSpec(
                f"/loop-rocksmash:prepare {tmp_path / 'sumiu' / '_LOOP-CONFIG.json'}",
                ModelName.OPUS,
            )
        ]
        assert RocksmashRuntimeCursor.from_specs(specs) is None

    def test_config_reescrita_apos_o_bind_nao_invalida_a_marcacao(
        self, tmp_path: Path
    ) -> None:
        """`/loop-rocksmash:rename` reescreve o `_LOOP-CONFIG.json` no fim do
        run. Reler o arquivo a cada escrita faria as ultimas subfases baterem
        contra um hash novo e voltarem para a fila."""
        cfg = _config(1)
        root = _loop(tmp_path, cfg)
        specs = build_loop_rocksmash_specs(cfg, root)
        cursor = RocksmashRuntimeCursor.from_specs(specs)
        ctx = _subfase_specs(specs)[-1].loop_context

        (root / "_LOOP-CONFIG.json").write_text(json.dumps(_config(3)), encoding="utf-8")

        assert cursor.begin(ctx).applied is True
        assert cursor.finish(ctx, failed=False).applied is True
        assert read_state(root).items["001"].subphases["integrate"].status == "completed"


class TestEscritaDoCursor:
    def _cursor(self, tmp_path: Path):
        cfg = _config(1)
        root = _loop(tmp_path, cfg)
        specs = build_loop_rocksmash_specs(cfg, root)
        return RocksmashRuntimeCursor.from_specs(specs), root, _subfase_specs(specs)

    def test_begin_marca_in_flight(self, tmp_path: Path) -> None:
        cursor, root, subs = self._cursor(tmp_path)
        assert cursor.begin(subs[0].loop_context).applied is True
        assert read_state(root).items["001"].subphases["do"].status == "in_flight"

    def test_finish_marca_completed(self, tmp_path: Path) -> None:
        cursor, root, subs = self._cursor(tmp_path)
        cursor.begin(subs[0].loop_context)
        assert cursor.finish(subs[0].loop_context, failed=False).applied is True
        assert read_state(root).items["001"].subphases["do"].status == "completed"

    def test_finish_failed_marca_failed(self, tmp_path: Path) -> None:
        cursor, root, subs = self._cursor(tmp_path)
        cursor.begin(subs[0].loop_context)
        cursor.finish(subs[0].loop_context, failed=True, note="listener-failure")
        assert read_state(root).items["001"].subphases["do"].status == "failed"

    def test_dispatch_concorrente_da_mesma_subfase_e_recusado(
        self, tmp_path: Path
    ) -> None:
        cursor, root, subs = self._cursor(tmp_path)
        cursor.begin(subs[0].loop_context)
        segundo = cursor.begin(subs[0].loop_context)
        assert segundo.applied is False
        assert segundo.error

    def test_contexto_de_loop_normal_e_ignorado(self, tmp_path: Path) -> None:
        """Item de `/loop` tambem tem `item_id` e `phase`. Sem o teste de
        `mode`, cada item de loop comum viraria um erro registrado."""
        cursor, root, _ = self._cursor(tmp_path)
        antes = state_path(root).read_text(encoding="utf-8")
        ctx = LoopExecutionContext(
            loop_id="outro", queue_id="q", item_id="001", phase="do"
        )
        resultado = cursor.begin(ctx)
        assert resultado.applied is False and resultado.error is None
        assert state_path(root).read_text(encoding="utf-8") == antes

    def test_subfase_desconhecida_e_ignorada(self, tmp_path: Path) -> None:
        cursor, _root, _ = self._cursor(tmp_path)
        ctx = LoopExecutionContext(
            loop_id="l",
            queue_id="q",
            item_id="001",
            phase="execute-task",
            mode=ROCKSMASH_CONTEXT_MODE,
        )
        assert cursor.begin(ctx).applied is False


# ───────────────────────── Task 24(a): desfecho pelo sinal autoritativo ── #


class TestDesfechoNoWidget:
    def _fila(self, tmp_path: Path, qtbot, n: int = 1):
        cfg = _config(n)
        root = _loop(tmp_path, cfg)
        specs = build_loop_rocksmash_specs(cfg, root)
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w.load_pipeline(specs)
        return w, root, _subfase_specs(specs)

    def test_load_pipeline_liga_o_cursor(self, qapp, qtbot, tmp_path: Path) -> None:
        w, root, _ = self._fila(tmp_path, qtbot)
        assert w._rocksmash_cursor is not None
        assert w._rocksmash_cursor.loop_root == root

    def test_fila_comum_desliga_o_cursor(self, qapp, qtbot, tmp_path: Path) -> None:
        """Cursor pendurado marcaria subfase de OUTRO loop."""
        w, _root, _ = self._fila(tmp_path, qtbot)
        w.load_pipeline([CommandSpec("/qa:report --module 1", ModelName.SONNET)])
        assert w._rocksmash_cursor is None

    def test_dispatch_marca_in_flight_antes_do_envio(
        self, qapp, qtbot, tmp_path: Path
    ) -> None:
        w, root, subs = self._fila(tmp_path, qtbot)
        assert w._begin_rocksmash_subphase(subs[0]) is True
        assert read_state(root).items["001"].subphases["do"].status == "in_flight"

    def test_subfase_em_voo_recusa_o_dispatch(
        self, qapp, qtbot, tmp_path: Path
    ) -> None:
        w, _root, subs = self._fila(tmp_path, qtbot)
        avisos: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: avisos.append((m, k)))
        try:
            assert w._begin_rocksmash_subphase(subs[0]) is True
            assert w._begin_rocksmash_subphase(subs[0]) is False
        finally:
            signal_bus.toast_requested.disconnect()
        assert avisos and avisos[-1][1] == "warning"

    def test_sem_cursor_a_spec_rocksmash_nao_e_despachada(
        self, qapp, qtbot, tmp_path: Path
    ) -> None:
        """Fail-closed: cursor desligado nao pode virar dispatch sem checkpoint.

        `from_specs` devolve `None` quando a config esta ilegivel. Se o widget
        tratasse isso como "sem rocksmash aqui" e liberasse o envio, a subfase
        rodaria sem `in_flight` gravado: um crash no meio dela deixaria o
        sidecar dizendo `pending`, e a retomada rodaria tudo de novo por cima
        de trabalho ja feito. Recusar e a unica saida honesta.
        """
        cfg = _config(1)
        root = _loop(tmp_path, cfg)
        specs = build_loop_rocksmash_specs(cfg, root)
        (root / "_LOOP-CONFIG.json").unlink()

        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w.load_pipeline(specs)
        assert w._rocksmash_cursor is None

        avisos: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: avisos.append((m, k)))
        try:
            assert w._begin_rocksmash_subphase(_subfase_specs(specs)[0]) is False
        finally:
            signal_bus.toast_requested.disconnect()

        assert avisos and avisos[-1][1] == "warning"
        assert "001/do" in avisos[-1][0]
        # O sidecar existe (a expansao o criou), mas segue intocado: sem
        # `in_flight` gravado, o dispatch nao pode acontecer.
        assert read_state(root).items["001"].subphases["do"].status == "pending"

    def test_sem_cursor_a_spec_comum_da_mesma_fila_segue_passando(
        self, qapp, qtbot, tmp_path: Path
    ) -> None:
        """A recusa e escopada na subfase, nao um freio geral da fila."""
        spec = CommandSpec("/qa:report --module 1", ModelName.SONNET)
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w.load_pipeline([spec])
        assert w._rocksmash_cursor is None
        assert w._begin_rocksmash_subphase(spec) is True

    def test_verde_autoritativo_conclui_a_subfase_e_o_item(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        w, root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w._on_listener_authoritative_idle("interactive")

        assert read_state(root).items["001"].subphases["do"].status == "completed"
        concluidos = [e for e in _eventos() if e["event_type"] == "item_completed"]
        assert len(concluidos) == 1
        assert concluidos[0]["item_id"] == "001"
        assert concluidos[0]["phase"] == "do"
        assert concluidos[0]["duration"] is not None

    def test_falha_de_listener_marca_failed(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        w, root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w._on_autocast_abort_requested("listener-failure", "interactive")

        assert read_state(root).items["001"].subphases["do"].status == "failed"
        assert [e for e in _eventos() if e["event_type"] == "item_failed"]

    def test_item_failed_precede_queue_paused(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """A ordem no corpus conta a historia na ordem em que aconteceu: o
        item falhou, e por isso a fila parou."""
        w, _root, subs = self._fila(tmp_path, qtbot)
        w._btn_autocast.setChecked(True)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w._on_autocast_abort_requested("listener-failure", "interactive")

        tipos = _tipos()
        assert "item_failed" in tipos
        if "queue_paused" in tipos:
            assert tipos.index("item_failed") < tipos.index("queue_paused")

    def test_verde_de_outro_canal_nao_conclui(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """T1 verde enquanto o item roda no T3 nao e o desfecho do item do T3."""
        w, root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("workspace_xterm", route="teste", text=spec.name)

        w._on_listener_authoritative_idle("interactive")

        assert read_state(root).items["001"].subphases["do"].status == "in_flight"
        assert [e for e in _eventos() if e["event_type"] == "item_completed"] == []

        w._on_listener_authoritative_idle("workspace_xterm")
        assert read_state(root).items["001"].subphases["do"].status == "completed"

    def test_despachar_nao_conclui(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """Regra L14.7: 'despachado' e 'concluido' sao fatos diferentes.

        Colar o texto no terminal nao prova que o comando rodou; emitir
        conclusao ali transformaria toda falha silenciosa em sucesso
        registrado, e o corpus ficaria sem UM caso de abandono.
        """
        w, root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        assert _tipos().count("item_dispatched") == 1
        assert "item_completed" not in _tipos()
        assert read_state(root).items["001"].subphases["do"].status == "in_flight"

    def test_desfecho_e_one_shot(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """Verde duplo do mesmo canal nao conta o item duas vezes."""
        w, _root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w._on_listener_authoritative_idle("interactive")
        w._on_listener_authoritative_idle("interactive")

        assert _tipos().count("item_completed") == 1

    def test_desfecho_independe_do_auto_loop(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """Amarrar telemetria a um toggle de UI faria todo run manual aparecer
        como abandono."""
        w, _root, subs = self._fila(tmp_path, qtbot)
        w.set_auto_loop_enabled(False)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w._on_listener_authoritative_idle("interactive")

        assert [e for e in _eventos() if e["event_type"] == "item_completed"]

    def test_fila_nova_descarta_despacho_sem_desfecho(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """Emitir `item_completed` na troca de fila inventaria uma conclusao."""
        w, _root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)

        w.load_pipeline([CommandSpec("/qa:report --module 1", ModelName.SONNET)])
        w._on_listener_authoritative_idle("interactive")

        assert "item_completed" not in _tipos()

    def test_falha_de_gravacao_do_desfecho_avisa_o_bloqueio_real(
        self, qapp, qtbot, tmp_path: Path, sink_tmp, dispatch_tmp
    ) -> None:
        """O toast de falha de `finish` tem de nomear a consequencia CERTA.

        Ate 2026-08-24 ele prometia "a subfase sera reenfileirada na proxima
        expansao", o que e falso e perigoso: a subfase fica presa em
        `in_flight`, e `in_flight` cujo processo morreu vira `unknown` na
        reabertura — estado que BLOQUEIA a retomada automatica ate
        reconciliacao manual. Operador que le "sera reenfileirada" fecha o app
        tranquilo e descobre o bloqueio na proxima expansao.

        A falha aqui e real, nao mock: o sidecar e corrompido depois do
        `begin`, entao `read_state` levanta `RocksmashStateError` dentro de
        `mark_subphase` e o cursor devolve `error`.
        """
        w, root, subs = self._fila(tmp_path, qtbot)
        spec = subs[0]
        w._begin_rocksmash_subphase(spec)
        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)
        assert read_state(root).items["001"].subphases["do"].status == "in_flight"

        state_path(root).write_text("{ nao é json", encoding="utf-8")

        avisos: list[tuple[str, str]] = []
        signal_bus.toast_requested.connect(lambda m, k: avisos.append((m, k)))
        try:
            w._on_listener_authoritative_idle("interactive")
        finally:
            signal_bus.toast_requested.disconnect()

        desfecho = [a for a in avisos if "desfecho NAO" in a[0]]
        assert desfecho, f"nenhum toast de falha de desfecho; vieram: {avisos!r}"
        msg, kind = desfecho[-1]
        assert kind == "warning"
        assert "001/do" in msg
        # As tres palavras que mudam o que o operador faz a seguir.
        assert "in_flight" in msg
        assert "unknown" in msg
        assert "bloqueia" in msg
        # E a promessa antiga, que era mentira, nao pode voltar.
        assert "reenfileirada" not in msg


# ───────────────────────────────────────── loop comum nao regride ── #


class TestLoopComumSegueFuncionando:
    def test_item_de_loop_comum_conclui_sem_cursor(
        self, qapp, qtbot, sink_tmp, dispatch_tmp
    ) -> None:
        """A fiacao do desfecho vale para QUALQUER loop, nao so rocksmash."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = CommandSpec("/loop:iteraction:execute-task a/b.md", ModelName.SONNET, position=1)
        spec.loop_context = LoopExecutionContext(
            loop_id="08-24-loop", queue_id="q1", item_id="007", phase="do"
        )
        w.load_pipeline([spec])
        assert w._rocksmash_cursor is None

        w._record_loop_dispatch(spec, "claude")
        w._publish_to_terminal("interactive", route="teste", text=spec.name)
        w._on_listener_authoritative_idle("interactive")

        concluidos = [e for e in _eventos() if e["event_type"] == "item_completed"]
        assert len(concluidos) == 1
        assert concluidos[0]["item_id"] == "007"
