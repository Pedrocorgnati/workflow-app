"""Retrocompatibilidade de snapshots com o LoopExecutionContext (Task 15).

Dois riscos, opostos, cobertos aqui:

1. **Perda de correlacao.** Se o snapshot nao levar o contexto, retomar uma fila
   salva deixaria os itens sem `item_id` e a unica saida seria re-inferi-lo do
   texto do comando — o que 12.2.5 proibe. Um item de `cmd-single`, cujo comando
   expandido nao tem `--item`, ficaria orfao para sempre.

2. **Quebra do que ja existe em disco.** Snapshot gravado antes desta mudanca
   nao tem a chave nova. Ele tem que continuar restaurando, sem excecao e sem
   toast, apenas sem correlacao (13.1, linha Compatibilidade).
"""

from __future__ import annotations

import json

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, LoopExecutionContext, ModelName
from workflow_app.signal_bus import signal_bus

CTX = LoopExecutionContext(
    loop_id="08-24-exemplo",
    queue_id="q-abc",
    item_id="013",
    phase="do",
    bucket_id="b1",
    mode="cmd-single",
)


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    return w


def _entry_legado(name: str, **kw) -> dict:
    """Entrada exatamente no formato gravado ANTES da Task 15."""
    base = {
        "name": name,
        "model": "Sonnet",
        "interaction_type": "auto",
        "position": 1,
        "is_optional": False,
        "config_path": "",
        "phase": "B.3",
        "effort": "medium",
        "kimi_eligible": False,
        "status": "pendente",
        "sent": False,
    }
    base.update(kw)
    return base


class TestSerializacaoDoContexto:
    def test_context_sobrevive_ao_round_trip(self):
        assert LoopExecutionContext.from_dict(CTX.to_dict()) == CTX

    def test_campos_nulos_nao_engordam_o_snapshot(self):
        magro = LoopExecutionContext(loop_id="l", queue_id="q")
        assert magro.to_dict() == {"loop_id": "l", "queue_id": "q"}

    def test_snapshot_e_json_serializavel(self):
        assert json.loads(json.dumps(CTX.to_dict()))["item_id"] == "013"

    @pytest.mark.parametrize("entrada", [None, "", 0, [], "013", {"outro": 1}])
    def test_valor_invalido_degrada_para_none_sem_estourar(self, entrada):
        assert LoopExecutionContext.from_dict(entrada) is None


class TestSnapshotDaFila:
    def test_queue_snapshot_carrega_o_contexto(self, widget):
        widget.load_pipeline(
            [CommandSpec("/loop:iteraction:execute-task", ModelName.OPUS, position=1,
                         loop_context=CTX)]
        )
        snap = widget.get_queue_snapshot()
        assert snap[0]["loop_context"]["item_id"] == "013"
        assert snap[0]["loop_context"]["loop_id"] == "08-24-exemplo"

    def test_comando_fora_de_loop_nao_ganha_chave(self, widget):
        widget.load_pipeline([CommandSpec("/prd-create", ModelName.OPUS, position=1)])
        assert "loop_context" not in widget.get_queue_snapshot()[0]

    def test_round_trip_completo_preserva_a_correlacao(self, widget):
        widget.load_pipeline(
            [CommandSpec("/cmd:update ./x.md", ModelName.OPUS, position=1,
                         loop_context=CTX)]
        )
        snap = json.loads(json.dumps(widget.get_queue_snapshot()))
        widget.restore_queue_snapshot(snap)
        spec = widget.rendered_specs()[0]
        # O comando restaurado NAO tem `--item` no texto: sem o contexto, a
        # correlacao teria se perdido de vez.
        assert "--item" not in spec.name
        assert spec.loop_context is not None
        assert spec.loop_context.item_id == "013"
        assert spec.loop_context.phase == "do"
        assert spec.loop_context.mode == "cmd-single"


class TestSnapshotLegado:
    def test_snapshot_sem_a_chave_restaura_sem_erro(self, widget):
        widget.restore_queue_snapshot([_entry_legado("/prd-create")])
        specs = widget.rendered_specs()
        assert len(specs) == 1
        assert specs[0].loop_context is None

    def test_snapshot_legado_nao_gera_toast(self, widget):
        toasts: list[tuple[str, str]] = []
        handler = lambda m, k: toasts.append((m, k))  # noqa: E731
        signal_bus.toast_requested.connect(handler)
        try:
            widget.restore_queue_snapshot(
                [_entry_legado("/prd-create"), _entry_legado("/hld-create")]
            )
        finally:
            signal_bus.toast_requested.disconnect(handler)
        assert toasts == [], "restauracao de snapshot legado nao pode alarmar"

    def test_chave_presente_mas_corrompida_degrada_em_silencio(self, widget):
        # Snapshot editado a mao / truncado: o item volta sem correlacao em vez
        # de derrubar a retomada inteira da fila.
        widget.restore_queue_snapshot(
            [_entry_legado("/prd-create", loop_context="lixo")]
        )
        assert widget.rendered_specs()[0].loop_context is None

    def test_contexto_parcial_e_aceito(self, widget):
        # Config legada sem `mode` produz contexto sem `mode`. Continua valido.
        widget.restore_queue_snapshot(
            [
                _entry_legado(
                    "/prd-create",
                    loop_context={"loop_id": "l", "queue_id": "q", "item_id": "007"},
                )
            ]
        )
        ctx = widget.rendered_specs()[0].loop_context
        assert ctx.item_id == "007"
        assert ctx.mode is None and ctx.bucket_id is None

    def test_status_e_sent_continuam_preservados(self, widget):
        widget.restore_queue_snapshot(
            [_entry_legado("/prd-create", status="sucesso", sent=True)]
        )
        assert widget.rendered_specs()[0].name == "/prd-create"


class TestDispatcherRecebeOContexto:
    """Ultimo elo da travessia: CommandSpec -> snapshot -> restore -> dispatcher."""

    def test_dispatch_registra_contexto_e_efetivos(self, widget):
        from workflow_app.command_queue.provider_router import Provider

        spec = CommandSpec("/cmd:update ./x.md", ModelName.OPUS, position=1,
                           loop_context=CTX)
        widget._record_loop_dispatch(spec, Provider.CLAUDE)
        assert widget._last_loop_context == CTX
        ev = widget._last_lifecycle_event
        assert ev["event_type"] == "item_dispatched"
        assert ev["item_id"] == "013"
        assert ev["model_effective"] == ModelName.OPUS.value
        assert ev["provider_effective"]

    def test_comando_sem_contexto_nao_herda_o_item_anterior(self, widget):
        from workflow_app.command_queue.provider_router import Provider

        widget._record_loop_dispatch(
            CommandSpec("/x", ModelName.OPUS, position=1, loop_context=CTX),
            Provider.CLAUDE,
        )
        widget._record_loop_dispatch(
            CommandSpec("/prd-create", ModelName.OPUS, position=2), Provider.CLAUDE
        )
        assert widget._last_lifecycle_event is None

    def test_falha_de_telemetria_nunca_derruba_o_dispatch(self, widget):
        class SpecQuebrado:
            loop_context = CTX
            name = "/x"

            @property
            def model(self):
                raise RuntimeError("boom")

        widget._record_loop_dispatch(SpecQuebrado(), None)
        assert widget._last_lifecycle_event is None
