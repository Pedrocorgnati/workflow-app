"""Contrato do sidecar de lifecycle e dos call sites que o alimentam (Task 24).

O que estes testes protegem, e por que cada um existe:

1. **O guard da suite.** `WF_BLOCK_REAL_LIFECYCLE_TELEMETRY` esta armado no
   `conftest` desde o import. Sem ele, rodar a suite despejaria centenas de
   eventos sinteticos em `~/.workflow-app/logs/`, e o corpus que decide se um
   loop foi cancelado ou abandonado passaria a conter execucao que nunca
   houve. E o mesmo desenho de `test_telemetry_no_real_write.py`.

2. **Que a escrita ACONTECE.** Guard que bloqueia tudo passaria nos testes e
   entregaria zero evento em producao — foi exatamente o defeito original
   (envelopes montados, nenhum leitor). Por isso o guard cede a
   `SF_LOOP_LIFECYCLE_DIR`: apontando para `tmp_path` o sink grava de verdade
   e o teste le a linha de volta.

3. **Os quatro call sites que faltavam.** `queue_started`, `queue_paused`,
   `app_closed` e `provider_blocked` nao tinham emissor nenhum. Cada um marca
   um estado que, sem evento, e indistinguivel de abandono: fila com pendentes
   e nenhuma marca. Os testes aqui exercitam o caminho real do widget, nao o
   builder do envelope (esse ja tem oraculo proprio em
   `test_loop_lifecycle_event.py`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, LoopExecutionContext, ModelName
from workflow_app.signal_bus import signal_bus
from workflow_app.telemetry import lifecycle_sink
from workflow_app.telemetry.loop_lifecycle_event import build_lifecycle_event


# ─────────────────────────────────────────────────────────── helpers ── #


@pytest.fixture()
def sink_tmp(tmp_path, monkeypatch) -> Path:
    """Aponta o sink para `tmp_path`. O override vence o guard de proposito.

    Chama `_reset_for_tests` na saida: o sidecar e particionado por PID e a
    suite inteira roda no MESMO PID, entao sem a limpeza um teste herdaria os
    eventos do anterior sempre que dois testes caissem no mesmo `tmp_path`.
    O helper existe para isto; deixa-lo sem chamador seria mante-lo orfao.
    """
    monkeypatch.setenv(lifecycle_sink.SINK_DIR_ENV, str(tmp_path))
    lifecycle_sink._reset_for_tests()
    yield tmp_path
    lifecycle_sink._reset_for_tests()


def _ctx(item_id: str | None = "003", phase: str | None = "execute-task"):
    return LoopExecutionContext(
        loop_id="08-24-teste",
        queue_id="q-42",
        item_id=item_id,
        phase=phase,
    )


def _spec(nome: str = "/loop:iteraction:execute-task", ctx=None) -> CommandSpec:
    spec = CommandSpec(nome, ModelName.SONNET, position=1)
    spec.loop_context = ctx if ctx is not None else _ctx()
    return spec


def _eventos(widget) -> list[dict]:
    return lifecycle_sink.read_events()


def _tipos(widget) -> list[str]:
    return [e.get("event_type") for e in _eventos(widget)]


# ───────────────────────────────────────────────────── guard do sink ── #


class TestGuardDoSink:
    def test_guard_esta_armado_na_suite(self):
        """Se este teste falhar, a suite esta gravando no corpus do operador."""
        assert os.environ.get(lifecycle_sink.SINK_GUARD_ENV) == "1"

    def test_guard_bloqueia_o_diretorio_real(self, monkeypatch):
        monkeypatch.delenv(lifecycle_sink.SINK_DIR_ENV, raising=False)
        assert lifecycle_sink.sink_dir() is None
        assert lifecycle_sink.sink_path() is None

    def test_evento_nao_e_gravado_sob_guard(self, monkeypatch):
        monkeypatch.delenv(lifecycle_sink.SINK_DIR_ENV, raising=False)
        evento = build_lifecycle_event(
            event_type="queue_canceled", loop_id="l", queue_id="q"
        )
        assert lifecycle_sink.record_event(evento) is False

    def test_override_vence_o_guard(self, sink_tmp):
        """O guard protege o corpus real, nao proibe escrever.

        Sem esta cedencia nao haveria como provar que a persistencia funciona,
        e um sink que so bloqueia passaria verde entregando nada.
        """
        assert lifecycle_sink.sink_dir() == sink_tmp
        assert lifecycle_sink.sink_path().parent == sink_tmp


# ──────────────────────────────────────────────────── escrita/leitura ── #


class TestEscritaELeitura:
    def test_grava_e_le_de_volta(self, sink_tmp):
        evento = build_lifecycle_event(
            event_type="queue_canceled", loop_id="l1", queue_id="q1"
        )
        assert lifecycle_sink.record_event(evento) is True
        lidos = lifecycle_sink.read_events()
        assert len(lidos) == 1
        assert lidos[0]["event_type"] == "queue_canceled"
        assert lidos[0]["loop_id"] == "l1"
        assert lidos[0]["pid"] == os.getpid()

    def test_append_preserva_ordem(self, sink_tmp):
        for tipo in ("queue_started", "queue_paused", "queue_resumed"):
            lifecycle_sink.record_event(
                build_lifecycle_event(event_type=tipo, loop_id="l", queue_id="q")
            )
        assert [e["event_type"] for e in lifecycle_sink.read_events()] == [
            "queue_started",
            "queue_paused",
            "queue_resumed",
        ]

    def test_evento_nulo_nao_grava_nem_levanta(self, sink_tmp):
        assert lifecycle_sink.record_event(None) is False
        assert lifecycle_sink.read_events() == []

    def test_linha_corrompida_e_pulada_sem_perder_as_outras(self, sink_tmp):
        """App morto no meio de um write deixa linha truncada.

        Abortar a leitura ali perderia o corpus inteiro por causa do ultimo
        evento — o oposto do que um sidecar append-only deve entregar.
        """
        alvo = lifecycle_sink.sink_path()
        lifecycle_sink.record_event(
            build_lifecycle_event(event_type="app_closed", loop_id="l", queue_id="q")
        )
        with alvo.open("a", encoding="utf-8") as fh:
            fh.write('{"event_type": "trunca')
        lifecycle_sink.record_event(
            build_lifecycle_event(event_type="queue_canceled", loop_id="l", queue_id="q")
        )
        tipos = [e["event_type"] for e in lifecycle_sink.read_events()]
        assert tipos == ["app_closed", "queue_canceled"]

    def test_rotaciona_por_tamanho(self, sink_tmp, monkeypatch):
        """Rotacao e a lacuna que `dispatch_telemetry` deixou aberta.

        Sidecar sem teto acaba apagado a mao, e a evidencia some justamente no
        loop longo — o unico que interessa medir.
        """
        monkeypatch.setattr(lifecycle_sink, "MAX_BYTES", 200)
        for _ in range(12):
            lifecycle_sink.record_event(
                build_lifecycle_event(
                    event_type="item_dispatched",
                    loop_id="l",
                    queue_id="q",
                    context=_ctx(),
                    provider_effective="claude",
                    model_effective="sonnet",
                    effort_effective="medium",
                )
            )
        atual = lifecycle_sink.sink_path()
        rotacionado = Path(str(atual) + ".1")
        assert rotacionado.exists(), "rotacao nao produziu a geracao .1"
        assert atual.stat().st_size < 200 * 4

    def test_mascara_por_formato_no_texto_livre(self, sink_tmp):
        """`loop_id` e slug digitado por gente; pode carregar segredo colado."""
        evento = build_lifecycle_event(
            event_type="queue_canceled",
            loop_id="sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            queue_id="q",
        )
        lifecycle_sink.record_event(evento)
        gravado = lifecycle_sink.read_events()[0]["loop_id"]
        assert "AAAAAAAAAAAAAAAAAAAA" not in gravado


# ─────────────────────────────────────────── call sites: item events ── #


class TestCallSitesDeItem:
    def test_dispatch_persiste_item_dispatched(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        tipos = _tipos(w)
        assert "item_dispatched" in tipos
        evento = [e for e in _eventos(w) if e["event_type"] == "item_dispatched"][0]
        assert evento["item_id"] == "003"
        assert evento["provider_effective"] == "claude"

    def test_comando_fora_de_loop_nao_gera_evento(self, qapp, qtbot, sink_tmp):
        """`/clear` nao pertence a item nenhum. Inventar `item_id` para
        satisfazer o schema criaria correlacao falsa, pior que ausente."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec("/clear", ctx=_ctx(item_id=None, phase=None)), "claude")
        assert _eventos(w) == []

    def test_outcome_persiste_item_completed_com_duration(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec()
        w.load_pipeline([spec])
        w._record_loop_dispatch(spec, "claude")
        w._record_loop_item_outcome(0, failed=False)
        eventos = [e for e in _eventos(w) if e["event_type"] == "item_completed"]
        assert len(eventos) == 1
        assert eventos[0]["duration"] is not None
        assert eventos[0]["provider_effective"] == "claude"

    def test_outcome_sem_despacho_observado_nao_emite(self, qapp, qtbot, sink_tmp):
        """Sem o par despacho/desfecho na mesma sessao nao ha provider efetivo.

        O envelope recusaria o evento, e a recusa esta certa: atribuir custo a
        um tier adivinhado e pior que nao atribuir.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec()
        w.load_pipeline([spec])
        w._record_loop_item_outcome(0, failed=False)
        assert [e for e in _eventos(w) if e["event_type"] == "item_completed"] == []


# ────────────────────────────────────────── call sites: queue events ── #


class TestQueueStarted:
    def test_primeiro_despacho_emite_queue_started(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        assert _tipos(w)[0] == "queue_started"

    def test_queue_started_sai_uma_vez_por_queue_id(self, qapp, qtbot, sink_tmp):
        """O rearme do auto-loop despacha itens da MESMA fila.

        Reemitir ali contaria uma segunda largada e inflaria a contagem de
        filas iniciadas — `queue_id` e a identidade da fila, nao do ciclo.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        for _ in range(3):
            w._record_loop_dispatch(_spec(), "claude")
        assert _tipos(w).count("queue_started") == 1

    def test_queue_started_por_fila_distinta(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        outro = _spec()
        outro.loop_context = LoopExecutionContext(
            loop_id="08-24-teste", queue_id="q-99", item_id="001", phase="p"
        )
        w._record_loop_dispatch(outro, "claude")
        assert _tipos(w).count("queue_started") == 2

    def test_restore_da_mesma_fila_nao_reemite_queue_started(
        self, qapp, qtbot, sink_tmp
    ):
        """Snapshot/restore recarrega a fila preservando `loop_context`.

        A trava de `queue_started` nao pode cair em `load_pipeline`: com o
        `queue_id` preservado, limpar o set faria a MESMA fila largar duas vezes
        no corpus so por ter sido restaurada.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec()
        w.load_pipeline([spec])
        w._record_loop_dispatch(spec, "claude")

        restaurado = _spec()
        w.load_pipeline([restaurado])
        w._record_loop_dispatch(restaurado, "claude")

        assert _tipos(w).count("queue_started") == 1

    def test_queue_started_nao_carrega_item(self, qapp, qtbot, sink_tmp):
        """Evento de fila com item inventaria escopo que ele nao tem."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        evento = [e for e in _eventos(w) if e["event_type"] == "queue_started"][0]
        assert evento["item_id"] is None and evento["phase"] is None


class TestQueuePaused:
    def test_pipeline_paused_emite_uma_vez(self, qapp, qtbot, sink_tmp):
        """`pipeline_paused` chega em duplicata pelo desenho atual
        (module_detail emite e `PipelineManager.pause()` reemite)."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        signal_bus.pipeline_paused.emit()
        signal_bus.pipeline_paused.emit()
        assert _tipos(w).count("queue_paused") == 1

    def test_resume_destrava_e_pausa_volta_a_contar(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        signal_bus.pipeline_paused.emit()
        signal_bus.pipeline_resumed.emit()
        signal_bus.pipeline_paused.emit()
        tipos = _tipos(w)
        assert tipos.count("queue_paused") == 2
        assert tipos.count("queue_resumed") == 1

    def test_resume_sem_pausa_nesta_sessao_ainda_emite(self, qapp, qtbot, sink_tmp):
        """A pausa pode ter sido gravada em OUTRA sessao do app.

        A trava e por `queue_id`, e o `queue_id` sobrevive ao fechamento: pausar
        a fila, fechar o app e reabrir para retomar e o caminho comum. Se a
        retomada so pudesse sair depois de uma pausa observada NESTA sessao,
        aquele loop ficaria `paused` para sempre no corpus, porque
        `classify_loop_state` decide `paused` por pausa sem retomada POSTERIOR.

        A assimetria manda no desenho: retomada a mais nao apaga nada (nao ha
        pausa anterior para cancelar), retomada a menos falsifica o estado de um
        loop que voltou a rodar. Emitir e o lado seguro do erro.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        signal_bus.pipeline_resumed.emit()
        assert "queue_resumed" in _tipos(w)

    def test_resume_repetido_nao_duplica(self, qapp, qtbot, sink_tmp):
        """Emitir e o lado seguro do erro; duplicar nao e.

        A trava e maquina de estado, nao booleano: repeticao do MESMO estado e
        engolida, transicao sempre passa.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        signal_bus.pipeline_resumed.emit()
        signal_bus.pipeline_resumed.emit()
        signal_bus.pipeline_resumed.emit()
        assert _tipos(w).count("queue_resumed") == 1

    def test_pausa_de_outra_fila_nao_e_engolida(self, qapp, qtbot, sink_tmp):
        """Estado de pausa e por `queue_id`. Fila nova comeca indefinida."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        signal_bus.pipeline_paused.emit()

        outro = _spec()
        outro.loop_context = LoopExecutionContext(
            loop_id="08-24-teste", queue_id="q-99", item_id="001", phase="p"
        )
        w._record_loop_dispatch(outro, "claude")
        signal_bus.pipeline_paused.emit()
        assert _tipos(w).count("queue_paused") == 2

    def test_sem_contexto_de_loop_nao_emite(self, qapp, qtbot, sink_tmp):
        """Evento de fila sem fila nao correlaciona com nada."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        signal_bus.pipeline_paused.emit()
        assert _eventos(w) == []


class TestAppClosed:
    def test_emite_uma_vez_por_processo(self, qapp, qtbot, sink_tmp):
        """Dois ancoradouros (closeEvent + aboutToQuit) exigem trava: sem ela
        o fechamento normal dobraria a contagem de sessoes encerradas."""
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w._record_loop_dispatch(_spec(), "claude")
        w.note_app_closing()
        w.note_app_closing()
        assert _tipos(w).count("app_closed") == 1

    def test_app_closed_e_publico_para_a_main_window(self):
        """A MainWindow chama por nome nos dois ancoradouros; renomear sem
        atualizar `main_window.py` deixaria o evento mudo em silencio."""
        assert callable(getattr(CommandQueueWidget, "note_app_closing", None))

    def test_main_window_ancora_nos_dois_pontos(self):
        fonte = Path("src/workflow_app/main_window.py").read_text(encoding="utf-8")
        assert fonte.count("_note_app_closed()") >= 2
        assert "note_app_closing" in fonte


class TestProviderBlocked:
    def test_bloqueio_emite_com_contexto_do_item_barrado(self, qapp, qtbot, sink_tmp):
        """O contexto vem do item BARRADO, nunca de `_last_loop_context`.

        `_last_loop_context` guarda o ultimo item DESPACHADO; usa-lo aqui
        atribuiria o bloqueio ao item anterior.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        anterior = _spec()
        w._record_loop_dispatch(anterior, "claude")

        barrado = _spec("/pictures-create")
        barrado.loop_context = LoopExecutionContext(
            loop_id="08-24-teste", queue_id="q-42", item_id="007", phase="assets"
        )

        class _Item:
            def get_spec(self_inner):
                return barrado

        w._record_provider_blocked(_Item(), provider="kimi")
        evento = [e for e in _eventos(w) if e["event_type"] == "provider_blocked"][0]
        assert evento["item_id"] == "007"
        assert evento["provider_effective"] == "kimi"
        assert evento["result"] == "blocked"

    def test_fora_de_loop_nao_emite(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)

        class _Item:
            def get_spec(self_inner):
                return CommandSpec("/prd-create", ModelName.SONNET, position=1)

        w._record_provider_blocked(_Item(), provider="claude")
        assert _eventos(w) == []

    def test_bloqueio_sem_item_em_voo_e_aceito(self, qapp, qtbot, sink_tmp):
        """`provider_blocked` e contextual: pode pegar a fila parada.

        Forcar item aqui produziria dado falso em metade dos casos.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec("/clear", ctx=_ctx(item_id=None, phase=None))

        class _Item:
            def get_spec(self_inner):
                return spec

        w._record_provider_blocked(_Item(), provider="codex")
        evento = [e for e in _eventos(w) if e["event_type"] == "provider_blocked"][0]
        assert evento["item_id"] is None
        assert evento["provider_effective"] == "codex"


# ──────────────────────────────────────────── nulabilidade declarada ── #


class TestNaoObservavel:
    def test_usage_tokens_e_cost_ficam_nulos(self, qapp, qtbot, sink_tmp):
        """Nulo aqui e "nao observado", nunca zero.

        Nenhum provider local devolve tokens/custo ao app hoje: a cadeia
        `ExtrasOrchestrator.on_command_completed` recebe `model` e NAO recebe
        `tokens_in`/`tokens_out`, e `set_extras_orchestrator` nao tem chamador.
        Preencher zero aqui publicaria custo zero como fato medido.
        """
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec()
        w.load_pipeline([spec])
        w._record_loop_dispatch(spec, "claude")
        w._record_loop_item_outcome(0, failed=False)
        for evento in _eventos(w):
            assert evento["usage_tokens"] is None
            assert evento["cost"] is None

    def test_duration_so_existe_com_despacho_observado(self, qapp, qtbot, sink_tmp):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        spec = _spec()
        w.load_pipeline([spec])
        w._record_loop_dispatch(spec, "claude")
        despacho = [e for e in _eventos(w) if e["event_type"] == "item_dispatched"][0]
        assert despacho["duration"] is None


# ────────────────────────────────── caminho real do botao de dispatch ── #


class TestCaminhoRealDoStep:
    """Exercita `_on_step_btn_clicked`, nao os helpers de gravacao.

    Os testes acima chamam `_record_*` direto porque isolam o contrato do
    envelope. Aqui o alvo e outro: a ORDEM entre o gate de capacidade e o
    registro do despacho. Chamando helper nenhuma ordem e testada — foi
    exatamente assim que o `item_dispatched` acabou ACIMA do gate de image-gen,
    fazendo o item barrado aparecer no corpus como despachado e, na linha
    seguinte, como bloqueado. Um item que nunca saiu contava como saida.
    """

    def test_step_de_item_de_loop_persiste_item_dispatched(
        self, qapp, qtbot, sink_tmp
    ):
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w.load_pipeline([_spec()])
        w._on_step_btn_clicked()
        tipos = _tipos(w)
        assert "item_dispatched" in tipos
        assert "provider_blocked" not in tipos

    def test_bloqueio_de_imagem_nao_conta_como_despacho(
        self, qapp, qtbot, sink_tmp
    ):
        """So o Codex gera imagem; sob outro provider o item e RECUSADO.

        O corpus tem que registrar a recusa e NAO registrar despacho: o item nao
        foi para terminal nenhum.
        """
        barrado = _spec("/pictures-create")
        barrado.loop_context = LoopExecutionContext(
            loop_id="08-24-teste", queue_id="q-42", item_id="007", phase="assets"
        )
        w = CommandQueueWidget()
        qtbot.addWidget(w)
        w.load_pipeline([barrado])
        w._on_step_btn_clicked()

        tipos = _tipos(w)
        assert "provider_blocked" in tipos, (
            "item barrado por capacidade sem evento fica indistinguivel de "
            "loop abandonado"
        )
        assert "item_dispatched" not in tipos, (
            "registrar despacho antes do gate publica saida que nunca houve"
        )
        bloqueio = [e for e in _eventos(w) if e["event_type"] == "provider_blocked"][0]
        assert bloqueio["item_id"] == "007"
        assert bloqueio["result"] == "blocked"
