"""Preview de retomada no proprio botao Loop (Task 16 do estudo 08-24).

O que estava errado antes: o botao ja retomava corretamente — so nao contava.
O operador clicava e descobria o escopo da retomada lendo a fila resultante.
Quando o loop tinha itens `[!]`, o silencio era pior: nada na tela distinguia
"loop terminado" de "loop parou com falhas que ninguem vai reprocessar".

O que estes testes travam:

- o preview e derivado do PROGRESS.md, que continua a UNICA autoridade de
  elegibilidade — nao ha segunda fonte a divergir dele;
- `[!]` e visivel, terminal e fora da fila (retry so depois do contrato de
  reconciliacao atomica, Task 17);
- marcador invalido bloqueia com os IDs afetados, em vez de virar chute;
- a tentativa de retomada e registrada inclusive quando falha;
- nenhum comando `/loop:resume` nasce disso, e o loader normal segue sendo o
  caminho de retomada.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.daily_loop import (
    build_loop_resume_preview,
    build_loop_specs,
    read_loop_resume_preview,
)
from workflow_app.signal_bus import signal_bus

_APP_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_ROOT.parents[1]


def _progress(*linhas: str) -> str:
    cabecalho = "| ID | Status | Alvo | Bucket |\n|----|--------|------|--------|\n"
    return cabecalho + "".join(linhas)


LINHA_PENDENTE = "| 013 | [ ] | Item treze | b1 |\n"
LINHA_FEITA = "| 011 | [x] | Item onze | b1 |\n"
LINHA_FALHA = "| 012 | [!] | Item doze | b1 |\n"
LINHA_INVALIDA = "| 014 | [~] | Item catorze | b1 |\n"


def _config(commands=("/loop:iteraction:execute-task",), ids=("013",)):
    itens = [{"id": i, "title": f"Item {i}", "commands": list(commands)} for i in ids]
    return {
        "schema_version": "3.0.0",
        "mode": "cmd",
        "daily_loop": {
            "slug": "08-24-resume",
            "clear_between_items": False,
            "buckets": [
                {"id": "b1", "model": "opus", "effort": "high", "items": itens}
            ],
            "items_index": {i: {"commands": list(commands)} for i in ids},
        },
    }


class TestPreviewPuro:
    def test_conta_e_lista_ids_por_status(self):
        pv = build_loop_resume_preview(
            _progress(LINHA_FEITA, LINHA_FALHA, LINHA_PENDENTE)
        )
        assert pv.pending_ids == ("013",)
        assert pv.done_ids == ("011",)
        assert pv.failed_ids == ("012",)
        assert (pv.pending_count, pv.done_count, pv.failed_count) == (1, 1, 1)
        assert pv.total_count == 3

    def test_ids_aparecem_no_texto_do_preview(self):
        # Contagem sem ID nao e acionavel: "3 falhos" nao diz se sao os mesmos
        # 3 de ontem.
        texto = build_loop_resume_preview(
            _progress(LINHA_FEITA, LINHA_FALHA, LINHA_PENDENTE)
        ).ids_line()
        assert "013" in texto and "011" in texto and "012" in texto

    def test_falho_aparece_no_preview_e_e_marcado_terminal(self):
        pv = build_loop_resume_preview(_progress(LINHA_FALHA))
        assert pv.failed_ids == ("012",)
        assert "terminais" in pv.ids_line()

    def test_marcador_invalido_bloqueia_e_identifica_a_linha(self):
        pv = build_loop_resume_preview(_progress(LINHA_PENDENTE, LINHA_INVALIDA))
        assert pv.blocked
        assert pv.invalid_count == 1
        detalhe = pv.invalid_detail()
        assert "014" in detalhe and "[~]" in detalhe

    def test_invalido_entra_no_total(self):
        # Omiti-lo faria o preview reportar um universo menor que o real
        # justamente quando o arquivo esta errado.
        pv = build_loop_resume_preview(_progress(LINHA_PENDENTE, LINHA_INVALIDA))
        assert pv.total_count == 2

    def test_progresso_vazio_nao_e_bloqueio(self):
        pv = build_loop_resume_preview(_progress())
        assert not pv.blocked
        assert pv.total_count == 0

    def test_to_dict_serializa_contagens_e_ids(self):
        d = build_loop_resume_preview(_progress(LINHA_PENDENTE, LINHA_FALHA)).to_dict()
        assert d["pending_ids"] == ["013"]
        assert d["failed_ids"] == ["012"]
        assert d["blocked"] is False


class TestLeituraDoDisco:
    def test_le_o_progress_declarado_no_config(self, tmp_path):
        (tmp_path / "PROGRESS.md").write_text(
            _progress(LINHA_PENDENTE, LINHA_FALHA), encoding="utf-8"
        )
        pv = read_loop_resume_preview(_config(), tmp_path)
        assert pv is not None and pv.pending_ids == ("013",)

    def test_progress_ausente_devolve_none_em_vez_de_erro_duplicado(self, tmp_path):
        # O loader ja levanta DailyLoopConfigError com diagnostico de path
        # duplicado; um segundo erro aqui daria duas mensagens para a mesma causa.
        assert read_loop_resume_preview(_config(), tmp_path) is None


class TestElegibilidadeContinuaNoProgress:
    def test_apenas_pendentes_viram_fila(self, tmp_path):
        (tmp_path / "PROGRESS.md").write_text(
            _progress(LINHA_FEITA, LINHA_FALHA, LINHA_PENDENTE), encoding="utf-8"
        )
        specs = build_loop_specs(_config(ids=("011", "012", "013")), tmp_path)
        contextos = [s.loop_context for s in specs if s.loop_context is not None]
        ids = {c.item_id for c in contextos}
        assert ids == {"013"}, "so o [ ] pode ser materializado"

    def test_cada_pendente_entra_exatamente_uma_vez(self, tmp_path):
        (tmp_path / "PROGRESS.md").write_text(
            _progress(LINHA_PENDENTE, "| 015 | [ ] | Item quinze | b1 |\n"),
            encoding="utf-8",
        )
        specs = build_loop_specs(_config(ids=("013", "015")), tmp_path)
        despachos = [
            s for s in specs if s.name == "/loop:iteraction:execute-task"
        ]
        ids = [s.loop_context.item_id for s in despachos]
        assert sorted(ids) == ["013", "015"]
        assert len(ids) == len(set(ids)), "item duplicado seria reexecucao"

    def test_o_app_nunca_escreve_o_progress(self):
        # Autoridade de elegibilidade com writer unico: quem grava PROGRESS.md e
        # o lado dos slash-commands, sob lock. Se o app tambem gravasse, dois
        # escritores disputariam o mesmo arquivo sem coordenacao.
        alvos = [
            _APP_ROOT / "src" / "workflow_app" / "command_queue" / "command_queue_widget.py",
            _APP_ROOT / "src" / "workflow_app" / "daily_loop" / "loader.py",
        ]
        for path in alvos:
            texto = path.read_text(encoding="utf-8")
            for linha in texto.splitlines():
                if "progress_path" not in linha:
                    continue
                assert "write_text" not in linha, f"{path.name}: {linha.strip()}"
                assert "open(" not in linha, f"{path.name}: {linha.strip()}"


class TestNenhumComandoNovo:
    def test_nao_existe_slash_loop_resume(self):
        assert not (_REPO_ROOT / ".claude" / "commands" / "loop" / "resume.md").exists()

    def test_o_codigo_nao_referencia_loop_resume(self):
        # Ignora comentario: o que importa e que nenhum CODIGO emita o token.
        # Citar a decisao em prosa e o oposto de implementa-la.
        src = _APP_ROOT / "src"
        for path in src.rglob("*.py"):
            for linha in path.read_text(encoding="utf-8").splitlines():
                if linha.lstrip().startswith("#"):
                    continue
                assert "/loop:resume" not in linha, f"{path}: {linha.strip()}"

    def test_retomada_continua_no_loader_normal(self, tmp_path):
        # Nao ha entrypoint alternativo: o mesmo build_loop_specs que sempre
        # montou a fila e quem retoma.
        (tmp_path / "PROGRESS.md").write_text(_progress(LINHA_PENDENTE), encoding="utf-8")
        assert build_loop_specs(_config(), tmp_path)


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    return w


def _anexa_loop(tmp_path, progress_text: str, cfg=None):
    from workflow_app.config.app_state import app_state
    import json

    raw = cfg or _config()
    raw = {"kind": "daily-loop", **raw}
    (tmp_path / "PROGRESS.md").write_text(progress_text, encoding="utf-8")
    cfg_path = tmp_path / "_LOOP-CONFIG.json"
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")
    app_state.clear_all()
    app_state.set_loop_config(
        SimpleNamespace(
            config_path=str(cfg_path), raw=raw, project_name="08-24-resume"
        )
    )
    return raw


def _clica(widget):
    toasts: list[tuple[str, str]] = []
    pipelines: list[list] = []
    on_toast = lambda m, l: toasts.append((m, l))
    on_pipe = lambda specs: pipelines.append(list(specs))
    signal_bus.toast_requested.connect(on_toast)
    signal_bus.pipeline_ready.connect(on_pipe)
    try:
        widget._on_loop_clicked()
    finally:
        signal_bus.toast_requested.disconnect(on_toast)
        signal_bus.pipeline_ready.disconnect(on_pipe)
    return toasts, pipelines


class TestPreviewNoBotaoLoop:
    def test_botao_mostra_contagem_e_registra_a_retomada(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        _anexa_loop(
            tmp_path,
            _progress(LINHA_FEITA, LINHA_FALHA, LINHA_PENDENTE),
            cfg=_config(ids=("011", "012", "013")),
        )
        try:
            toasts, pipelines = _clica(widget)
        finally:
            app_state.clear_all()

        assert pipelines, f"fila deveria materializar; toasts={toasts}"
        rec = widget._last_resume_record
        assert rec["resume_attempted"] is True
        assert rec["result"] == "materialized"
        assert rec["pending_ids"] == ["013"]
        assert rec["failed_ids"] == ["012"]
        assert rec["queue_id"], "correlacao da fila deveria estar no registro"
        assert widget._last_resume_event["event_type"] == "queue_resumed"
        assert widget._last_resume_event["queue_id"] == rec["queue_id"]

    def test_label_do_botao_expoe_o_estado_lido(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        _anexa_loop(
            tmp_path,
            _progress(LINHA_FEITA, LINHA_FALHA, LINHA_PENDENTE),
            cfg=_config(ids=("011", "012", "013")),
        )
        try:
            _clica(widget)
        finally:
            app_state.clear_all()

        texto = widget._template_label.text()
        assert "1 pendente(s)" in texto
        assert "1 falho(s)" in texto

    def test_marcador_invalido_bloqueia_a_materializacao(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        _anexa_loop(
            tmp_path,
            _progress(LINHA_PENDENTE, LINHA_INVALIDA),
            cfg=_config(ids=("013", "014")),
        )
        try:
            toasts, pipelines = _clica(widget)
        finally:
            app_state.clear_all()

        assert pipelines == [], "marcador invalido nao pode virar fila"
        erros = [m for m, lvl in toasts if lvl == "error"]
        assert erros and "014" in erros[0] and "[~]" in erros[0]
        rec = widget._last_resume_record
        assert rec["result"] == "blocked_invalid_marker"
        assert rec["resume_attempted"] is True

    def test_falho_nao_entra_na_fila_pelo_botao(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        _anexa_loop(
            tmp_path,
            _progress(LINHA_FALHA, LINHA_PENDENTE),
            cfg=_config(ids=("012", "013")),
        )
        try:
            _, pipelines = _clica(widget)
        finally:
            app_state.clear_all()

        ids = {
            s.loop_context.item_id
            for s in pipelines[0]
            if getattr(s, "loop_context", None) is not None
        }
        assert ids == {"013"}, "retry de [!] nao existe nesta tranche"

    def test_loop_sem_pendentes_registra_tentativa_vazia(self, widget, tmp_path):
        from workflow_app.config.app_state import app_state

        _anexa_loop(
            tmp_path,
            _progress(LINHA_FEITA, LINHA_FALHA),
            cfg=_config(ids=("011", "012")),
        )
        try:
            toasts, pipelines = _clica(widget)
        finally:
            app_state.clear_all()

        assert pipelines == []
        rec = widget._last_resume_record
        assert rec["result"] == "empty"
        assert rec["resume_attempted"] is True
        assert rec["queue_id"] is None
        # Sem fila nao ha queue_id — e sem queue_id nao se inventa evento.
        assert widget._last_resume_event is None
        infos = [m for m, lvl in toasts if lvl == "info"]
        assert infos and "1 falho(s)" in infos[0]
