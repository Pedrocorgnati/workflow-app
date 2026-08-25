"""Contrato do LoopLifecycleEvent e do LoopExecutionContext (Task 15).

Duas coisas sao travadas aqui:

1. a nulabilidade POR TIPO de evento (12.2.5) — item exige item_id/phase, fila
   exige os dois nulos, e provider/model/effort sao obrigatorios a partir do
   despacho;
2. a origem da correlacao — `item_id` nasce no builder da fila e viaja no
   `CommandSpec`. O teste que mais importa e o que prova que a correlacao NAO
   depende do texto do comando: um comando expandido, sem `--item` nenhum,
   continua correlacionado.
"""

from __future__ import annotations

import json

import pytest

from workflow_app.daily_loop.loader import build_loop_specs
from workflow_app.domain import CommandSpec, LoopExecutionContext
from workflow_app.telemetry.loop_lifecycle_event import (
    CAMPOS_NAO_OBSERVAVEIS,
    CAMPOS_SEMPRE_PRESENTES,
    CONTEXTUAL_EVENTS,
    EVENT_TYPES,
    ITEM_EVENTS,
    QUEUE_EVENTS,
    RESULTS,
    SCHEMA_VERSION,
    LoopLifecycleEventError,
    abandonment_metrics_publishable,
    build_lifecycle_event,
    stale_gate_status,
)
from workflow_app.telemetry import loop_lifecycle_event as _lle

CTX = LoopExecutionContext(
    loop_id="08-24-exemplo", queue_id="q-1", item_id="013", phase="do"
)


def _item_event(event_type="item_dispatched", **kw):
    base = dict(
        event_type=event_type,
        loop_id=CTX.loop_id,
        queue_id=CTX.queue_id,
        context=CTX,
        provider_effective="claude",
        model_effective="Opus",
        effort_effective="high",
    )
    base.update(kw)
    return build_lifecycle_event(**base)


class TestCamposEEnums:
    def test_campos_sempre_presentes(self):
        ev = _item_event()
        for campo in CAMPOS_SEMPRE_PRESENTES:
            assert ev.get(campo) is not None, campo
        assert ev["schema_version"] == SCHEMA_VERSION

    def test_enums_batem_com_a_fonte(self):
        assert EVENT_TYPES == {
            "queue_started",
            "item_dispatched",
            "item_completed",
            "item_failed",
            "queue_paused",
            "queue_resumed",
            "queue_canceled",
            "app_closed",
            "provider_blocked",
        }
        assert RESULTS == {
            "started",
            "succeeded",
            "failed",
            "paused",
            "canceled",
            "blocked",
            "unknown",
        }

    def test_event_type_invalido_e_recusado(self):
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(event_type="item_meio_pronto", loop_id="l", queue_id="q")

    def test_result_invalido_e_recusado(self):
        with pytest.raises(LoopLifecycleEventError):
            _item_event(result="mais_ou_menos")

    def test_result_default_e_coerente_com_o_tipo(self):
        assert _item_event("item_completed")["result"] == "succeeded"
        assert _item_event("item_failed")["result"] == "failed"
        assert build_lifecycle_event(
            event_type="queue_paused", loop_id="l", queue_id="q"
        )["result"] == "paused"

    def test_loop_id_e_queue_id_sao_obrigatorios(self):
        # Sem eles o evento nao correlaciona com nada — nao serve a custo.
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(event_type="queue_started", loop_id="", queue_id="q")
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(event_type="queue_started", loop_id="l", queue_id=None)

    def test_event_id_e_unico(self):
        assert len({_item_event()["event_id"] for _ in range(30)}) == 30

    def test_ts_numerico_com_companheiro_iso(self):
        ev = _item_event(ts=1_700_000_000.0)
        assert isinstance(ev["ts"], float)
        assert ev["ts_iso"] == "2023-11-14T22:13:20Z"


class TestNulabilidadePorTipo:
    @pytest.mark.parametrize("tipo", sorted(ITEM_EVENTS))
    def test_evento_de_item_exige_item_id_e_phase(self, tipo):
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(
                event_type=tipo,
                loop_id="l",
                queue_id="q",
                provider_effective="claude",
                model_effective="Opus",
                effort_effective="high",
            )

    @pytest.mark.parametrize("tipo", sorted(ITEM_EVENTS))
    def test_evento_de_item_exige_phase_mesmo_com_item_id(self, tipo):
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(
                event_type=tipo,
                loop_id="l",
                queue_id="q",
                item_id="013",
                provider_effective="claude",
                model_effective="Opus",
                effort_effective="high",
            )

    @pytest.mark.parametrize("tipo", sorted(QUEUE_EVENTS))
    def test_evento_de_fila_exige_item_id_e_phase_nulos(self, tipo):
        ok = build_lifecycle_event(event_type=tipo, loop_id="l", queue_id="q")
        assert ok["item_id"] is None and ok["phase"] is None
        with pytest.raises(LoopLifecycleEventError):
            build_lifecycle_event(
                event_type=tipo, loop_id="l", queue_id="q", item_id="013", phase="do"
            )

    @pytest.mark.parametrize("tipo", sorted(CONTEXTUAL_EVENTS))
    def test_evento_contextual_aceita_os_dois_lados(self, tipo):
        # provider_blocked pode pegar a fila parada OU um item em voo.
        sem = build_lifecycle_event(event_type=tipo, loop_id="l", queue_id="q")
        com = build_lifecycle_event(
            event_type=tipo, loop_id="l", queue_id="q", context=CTX
        )
        assert sem["item_id"] is None
        assert com["item_id"] == "013" and com["phase"] == "do"


class TestEfetivosNoDespacho:
    @pytest.mark.parametrize(
        "faltante", ["provider_effective", "model_effective", "effort_effective"]
    )
    def test_ausencia_de_efetivo_bloqueia_evento_de_item(self, faltante):
        with pytest.raises(LoopLifecycleEventError) as exc:
            _item_event(**{faltante: None})
        assert faltante in str(exc.value)

    def test_queue_started_nao_exige_efetivos(self):
        # Antes do despacho existe intencao, nao valor efetivo.
        ev = build_lifecycle_event(event_type="queue_started", loop_id="l", queue_id="q")
        assert ev["provider_effective"] is None
        assert ev["model_effective"] is None


class TestUsoCustoDuracao:
    def test_nulos_quando_o_provider_nao_expoe(self):
        ev = _item_event("item_completed")
        for campo in CAMPOS_NAO_OBSERVAVEIS:
            assert ev[campo] is None, campo

    def test_preenchidos_quando_observados(self):
        ev = _item_event("item_completed", usage_tokens=12_345, cost=0.42, duration=90.5)
        assert ev["usage_tokens"] == 12_345
        assert ev["cost"] == pytest.approx(0.42)
        assert ev["duration"] == pytest.approx(90.5)

    def test_zero_legitimo_nao_vira_ausencia(self):
        # Custo zero e um valor; confundi-lo com "nao observado" apagaria a
        # unica evidencia de que o provider respondeu de graca.
        ev = _item_event("item_completed", cost=0, usage_tokens=0)
        assert ev["cost"] == 0
        assert ev["usage_tokens"] == 0

    def test_lixo_nao_vira_zero(self):
        ev = _item_event("item_completed", cost="n/d", usage_tokens="?")
        assert ev["cost"] is None and ev["usage_tokens"] is None


class TestContextoNoSpec:
    def test_command_spec_sem_loop_nasce_sem_contexto(self):
        assert CommandSpec(name="/qa:trace").loop_context is None

    def test_contexto_e_imutavel(self):
        with pytest.raises(Exception):
            CTX.item_id = "999"  # frozen dataclass

    def test_with_phase_deriva_sem_mutar(self):
        outro = CTX.with_phase("review-done")
        assert outro.phase == "review-done"
        assert CTX.phase == "do"
        assert outro.item_id == CTX.item_id

    def test_is_item_scoped_separa_diretiva_de_item(self):
        assert CTX.is_item_scoped()
        assert not LoopExecutionContext(loop_id="l", queue_id="q").is_item_scoped()


def _config_minima(commands):
    return {
        "schema_version": "3.0.0",
        "mode": "cmd-single",
        "daily_loop": {
            "slug": "08-24-exemplo",
            "clear_between_items": False,
            "buckets": [
                {
                    "id": "b1",
                    "model": "opus",
                    "effort": "high",
                    # `buckets[*].items[*].commands` e a fonte autoritativa
                    # (daily_loop/CONTRACT.md); items_index e espelho.
                    "items": [
                        {"id": "013", "title": "Item treze", "commands": commands}
                    ],
                }
            ],
            "items_index": {"013": {"commands": commands}},
        },
    }


@pytest.fixture()
def loop_root(tmp_path):
    (tmp_path / "PROGRESS.md").write_text(
        "| ID | Status | Alvo | Bucket |\n"
        "|----|--------|------|--------|\n"
        "| 013 | [ ] | Item treze | b1 |\n",
        encoding="utf-8",
    )
    return tmp_path


class TestCorrelacaoNasceNoBuilder:
    def test_specs_de_item_carregam_contexto(self, loop_root):
        specs = build_loop_specs(
            _config_minima(["/loop:iteraction:execute-task"]), loop_root
        )
        do = [s for s in specs if s.name == "/loop:iteraction:execute-task"]
        assert do, "comando do item nao foi enfileirado"
        ctx = do[0].loop_context
        assert ctx is not None
        assert ctx.item_id == "013"
        assert ctx.loop_id == "08-24-exemplo"
        assert ctx.bucket_id == "b1"
        assert ctx.mode == "cmd-single"

    def test_item_id_nao_vem_do_texto_do_comando(self, loop_root):
        # O comando expandido nao tem `--item` nenhum. Se a correlacao
        # dependesse do texto, este item ficaria orfao — que e exatamente o
        # defeito que 12.2.5 proibe.
        specs = build_loop_specs(_config_minima(["/cmd:update ./x.md"]), loop_root)
        alvo = [s for s in specs if s.name == "/cmd:update ./x.md"]
        assert alvo and "--item" not in alvo[0].name
        assert alvo[0].loop_context.item_id == "013"

    def test_diretivas_nao_recebem_contexto(self, loop_root):
        specs = build_loop_specs(_config_minima(["/loop:iteraction:execute-task"]), loop_root)
        for spec in specs:
            if spec.name.startswith(("/clear", "/model ", "/effort ")):
                assert spec.loop_context is None, spec.name

    def test_queue_id_muda_entre_montagens_da_mesma_fila(self, loop_root):
        cfg = _config_minima(["/loop:iteraction:execute-task"])
        a = build_loop_specs(cfg, loop_root)
        b = build_loop_specs(cfg, loop_root)
        qa = next(s.loop_context.queue_id for s in a if s.loop_context)
        qb = next(s.loop_context.queue_id for s in b if s.loop_context)
        assert qa != qb, "duas execucoes do mesmo loop colidiriam na telemetria"

    def test_review_done_carrega_a_fase_propria(self, loop_root):
        cfg = _config_minima([])
        cfg["daily_loop"]["items_index"]["013"] = {}
        specs = build_loop_specs(cfg, loop_root)
        fases = {
            s.loop_context.phase for s in specs if s.loop_context is not None
        }
        assert "do" in fases and "review-done" in fases

    def test_config_sem_mode_continua_legivel(self, loop_root):
        cfg = _config_minima(["/loop:iteraction:execute-task"])
        del cfg["mode"]
        specs = build_loop_specs(cfg, loop_root)
        ctx = next(s.loop_context for s in specs if s.loop_context)
        # Ausencia vira None, nunca um modo inventado.
        assert ctx.mode is None
        assert ctx.item_id == "013"

    def test_evento_montado_a_partir_do_spec_e_serializavel(self, loop_root):
        specs = build_loop_specs(_config_minima(["/x"]), loop_root)
        spec = next(s for s in specs if s.loop_context)
        ev = build_lifecycle_event(
            event_type="item_dispatched",
            loop_id=spec.loop_context.loop_id,
            queue_id=spec.loop_context.queue_id,
            context=spec.loop_context,
            provider_effective="claude",
            model_effective=spec.model.value,
            effort_effective=spec.effort.value,
        )
        linha = json.dumps(ev, ensure_ascii=False)
        assert json.loads(linha)["item_id"] == "013"


# ────────────────────────────────────────────── gate G-JANELA-STALE ── #


class TestGateJanelaStale:
    """O gate da secao 14.4 de `loop-rules.md` precisava de um consumidor.

    Enquanto o quadro so prometia que `/loop:review` reportaria o vencimento —
    sem uma linha nesse comando lendo o gate — vencer dependia de alguem
    lembrar. Estes testes travam as duas propriedades que importam: o
    vencimento e VERIFICAVEL e ele NAO ratifica nada.
    """

    _LIMITE = "2026-09-21T00:00:00Z"

    def _ts(self, iso: str) -> float:
        from datetime import datetime, timezone

        return (
            datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )

    def test_antes_da_data_limite_nao_esta_vencido(self):
        """Gate ainda ABERTO (ratified=False injetado): antes do prazo,
        `expired` e False. Injetamos o estado nao-ratificado de proposito —
        a propriedade sob teste e a aritmetica de prazo, nao a decisao que o
        operador tomou em 2026-08-24."""
        st = stale_gate_status(
            now=self._ts("2026-08-24T00:00:00Z"), ratified=False
        )
        assert st["open"] is True
        assert st["expired"] is False
        assert st["deadline"] == _lle.JANELA_STALE_GATE_DEADLINE

    def test_depois_da_data_limite_vence(self):
        st = stale_gate_status(
            now=self._ts("2026-10-01T00:00:00Z"), ratified=False
        )
        assert st["expired"] is True

    def test_vencer_nao_ratifica_nem_abre_a_porta(self):
        """Ratificar por decurso de prazo e o default silencioso proibido.

        A janela decide quais loops viram `stale`, e `stale` e o insumo da taxa
        de abandono: um numero que ninguem aceitou nao pode virar denominador so
        porque um prazo passou.

        `ratified=False` e injetado nos DOIS lados (gate e porta) porque o
        operador ja ratificou no repo: sem a injecao este teste viraria uma
        tautologia sobre a decisao vigente e pararia de proteger o proximo gate
        que abrir.
        """
        st = stale_gate_status(
            now=self._ts("2027-01-01T00:00:00Z"), ratified=False
        )
        assert st["expired"] is True
        assert st["ratified"] is False
        porta = abandonment_metrics_publishable(
            stale_window_seconds=14 * 24 * 3600.0,
            window_ratified=False,
            states=["completed"],
        )
        assert porta["publishable"] is False
        assert "janela_stale_nao_ratificada_pelo_operador" in porta["blockers"]

    def test_ratificacao_do_operador_fecha_o_gate(self):
        """Decisao de 2026-08-24: janela de 14 dias RATIFICADA.

        O gate fecha (`open is False`), o vencimento deixa de fazer sentido
        (`expired is False` mesmo depois do prazo — um gate fechado nao vence)
        e o estado passa a carregar DESDE QUANDO e COM QUAL valor.
        """
        assert _lle.JANELA_STALE_RATIFICADA is True
        assert _lle.JANELA_STALE_RATIFICADA_EM == "2026-08-24"
        assert _lle.JANELA_STALE_SEGUNDOS == 14 * 24 * 3600

        st = stale_gate_status(now=self._ts("2027-01-01T00:00:00Z"))
        assert st["ratified"] is True
        assert st["open"] is False
        assert st["expired"] is False
        assert st["ratified_at"] == "2026-08-24"
        assert st["window_seconds"] == 14 * 24 * 3600

    def test_ratificacao_derruba_so_o_proprio_bloqueio(self):
        """A porta da 14.5 tem TRES bloqueios; a ratificacao derruba UM.

        Publicar exige tambem janela declarada na chamada e zero loop
        `indeterminado` no corte. Confundir "o gate fechou" com "a porta abriu"
        e exatamente o atalho que a secao 14.5 existe para impedir.
        """
        porta_ok = abandonment_metrics_publishable(
            stale_window_seconds=float(_lle.JANELA_STALE_SEGUNDOS),
            states=["completed", "stale"],
        )
        assert porta_ok["publishable"] is True
        assert porta_ok["blockers"] == []

        sem_janela = abandonment_metrics_publishable(
            stale_window_seconds=None, states=["completed"]
        )
        assert sem_janela["publishable"] is False
        assert "janela_stale_nao_declarada" in sem_janela["blockers"]

        com_indeterminado = abandonment_metrics_publishable(
            stale_window_seconds=float(_lle.JANELA_STALE_SEGUNDOS),
            states=["completed", _lle.STATE_INDETERMINADO],
        )
        assert com_indeterminado["publishable"] is False
        assert (
            "existem_loops_indeterminados_no_corte"
            in com_indeterminado["blockers"]
        )

    def test_now_e_injetado_nunca_lido_do_relogio(self):
        """Censo reproduzivel: mesmo corte, mesmo veredito, em qualquer dia."""
        a = stale_gate_status(
            now=self._ts("2026-09-20T23:59:59Z"), ratified=False
        )
        b = stale_gate_status(
            now=self._ts("2026-09-20T23:59:59Z"), ratified=False
        )
        assert a == b
        assert a["expired"] is False
