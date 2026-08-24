"""Contrato do envelope versionado de FailureEvent (Task 14 do estudo 08-24).

O defeito que motivou o envelope: no corte auditado, 2.553 eventos validos
tinham `command`, `exit_code` e `duration_seconds` nulos em 100% dos casos, e
966 nao tinham `run_id`. Estes testes travam o que passa a ser obrigatorio, o
que continua legitimamente nullable, e a compatibilidade com o consumidor que
ja le o corpus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from workflow_app.telemetry.failure_event import (
    CAMPOS_NULLABLE,
    CAMPOS_OBRIGATORIOS,
    CHANNELS,
    FAILURE_CLASSES,
    REASON_UNSPECIFIED,
    REASONS,
    SCHEMA_VERSION,
    SOURCES,
    FailureEventError,
    build_failure_event,
    classify,
    normalize_reason,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _evento(**kw):
    base = {"channel": "interactive", "reason": "EXIT_NONZERO"}
    base.update(kw)
    return build_failure_event(**base)


class TestCamposObrigatorios:
    def test_todo_evento_carrega_os_sete_campos_preenchidos(self):
        ev = _evento()
        for campo in CAMPOS_OBRIGATORIOS:
            assert campo in ev, f"campo obrigatorio ausente: {campo}"
            assert ev[campo] is not None, f"campo obrigatorio nulo: {campo}"

    def test_schema_version_e_semver(self):
        assert re.match(r"^\d+\.\d+\.\d+$", SCHEMA_VERSION)
        assert _evento()["schema_version"] == SCHEMA_VERSION

    def test_event_id_e_unico_entre_eventos_identicos(self):
        ids = {_evento()["event_id"] for _ in range(50)}
        assert len(ids) == 50, "event_id repetiu — nao serve para deduplicar"

    def test_source_e_failure_class_ficam_dentro_do_enum(self):
        for source in sorted(SOURCES):
            ev = _evento(source=source)
            assert ev["source"] in SOURCES
            assert ev["failure_class"] in FAILURE_CLASSES

    def test_channel_fora_do_enum_e_erro_do_emissor(self):
        with pytest.raises(FailureEventError):
            build_failure_event(channel="pty-3", reason="TIMEOUT")

    def test_source_fora_do_enum_e_erro_do_emissor(self):
        with pytest.raises(FailureEventError):
            build_failure_event(channel="interactive", reason="TIMEOUT", source="oraculo")


class TestNullabilidade:
    """Nullable nao e desleixo: e a recusa de inventar dado nao observado."""

    def test_campos_nullable_ficam_none_quando_nao_observados(self):
        ev = _evento()
        for campo in CAMPOS_NULLABLE:
            assert ev[campo] is None, f"{campo} deveria ser None sem observacao"

    def test_campos_nullable_aparecem_quando_observados(self):
        ev = _evento(
            run_id="run-77",
            item_id="013",
            raw_command="/loop:iteraction:execute-task",
            exit_code=2,
            duration_seconds=41.5,
        )
        assert ev["run_id"] == "run-77"
        assert ev["item_id"] == "013"
        assert ev["command_name"] == "/loop:iteraction:execute-task"
        assert ev["exit_code"] == 2
        assert ev["duration_seconds"] == pytest.approx(41.5)

    def test_run_id_string_vazia_vira_none(self):
        # `_last_processed_run_id.get(channel, "")` devolve "" quando nao ha run.
        # Persistir "" fingia presenca de dado: 966 eventos do corte tinham isso.
        assert _evento(run_id="")["run_id"] is None
        assert _evento(run_id="   ")["run_id"] is None

    def test_exit_code_e_duration_lixo_nao_viram_zero(self):
        ev = _evento(exit_code="n/a", duration_seconds="desconhecido")
        assert ev["exit_code"] is None
        assert ev["duration_seconds"] is None

    def test_duration_negativa_e_recusada(self):
        # Relogio andando para tras produz duracao negativa; melhor ausente.
        assert _evento(duration_seconds=-3.0)["duration_seconds"] is None


class TestReasonNotify:
    """10.1.5: `notify` nunca descreveu falha — era o default do payload."""

    def test_notify_vira_unspecified(self):
        assert normalize_reason("notify") == REASON_UNSPECIFIED

    def test_notify_nao_e_categoria_semantica(self):
        ev = _evento(reason="notify")
        assert ev["reason"] == REASON_UNSPECIFIED
        assert ev["failure_class"] == "unknown"
        assert ev["failure_class"] != "semantic"

    def test_vazio_e_nulo_colapsam_no_mesmo_sentinela(self):
        for bruto in (None, "", "   ", "none", "null"):
            assert normalize_reason(bruto) == REASON_UNSPECIFIED

    def test_reason_desconhecido_nao_polui_o_enum(self):
        assert normalize_reason("PANICOU") == REASON_UNSPECIFIED
        assert _evento(reason="PANICOU")["reason"] in REASONS


class TestClassificacao:
    def test_reasons_semanticos_viram_classe_semantic(self):
        for reason in ("BLOCKED", "RESSALVAS", "VERIFY_FAILED", "NO_VERDICT", "MISSING_ARG"):
            assert classify(reason, "listener") == "semantic", reason

    def test_reasons_de_processo_e_infra_se_separam(self):
        assert classify("EXIT_NONZERO", "listener") == "process"
        assert classify("EARLY_EXIT", "listener") == "process"
        assert classify("TIMEOUT", "listener") == "infrastructure"

    def test_falha_da_recuperacao_e_classe_recovery_qualquer_que_seja_o_reason(self):
        # O que se mede ali e o remendo automatico nao ter pego, nao o sintoma.
        for reason in ("BLOCKED", "TIMEOUT", "EXIT_NONZERO"):
            assert classify(reason, "recovery") == "recovery", reason

    def test_failure_class_explicita_do_emissor_prevalece(self):
        ev = _evento(reason="EXIT_NONZERO", failure_class="quota")
        assert ev["failure_class"] == "quota"

    def test_failure_class_explicita_invalida_e_recusada(self):
        with pytest.raises(FailureEventError):
            _evento(failure_class="chateado")


class TestTempo:
    def test_ts_continua_numerico_para_o_consumidor_existente(self):
        # ai-forge/scripts/classify-wf-failures-contamination.py rejeita
        # registro cujo `ts` nao seja int/float. Trocar epoch por ISO teria
        # invalidado todo evento novo em silencio.
        ev = _evento(ts=1_700_000_000.0)
        assert isinstance(ev["ts"], (int, float))
        assert not isinstance(ev["ts"], bool)

    def test_ts_iso_acompanha_em_utc(self):
        ev = _evento(ts=1_700_000_000.0)
        assert ev["ts_iso"] == "2023-11-14T22:13:20Z"
        assert ev["ts_iso"].endswith("Z")

    def test_consumidor_real_aceita_o_envelope_novo(self):
        script = REPO_ROOT / "ai-forge" / "scripts" / "classify-wf-failures-contamination.py"
        if not script.exists():
            pytest.skip("consumidor ausente nesta arvore")
        texto = script.read_text(encoding="utf-8")
        assert 'rec.get("ts")' in texto
        assert 'isinstance(ts, (int, float))' in texto
        # O envelope satisfaz a condicao que o consumidor exige.
        assert isinstance(json.loads(json.dumps(_evento()))["ts"], float)


class TestSerializacao:
    def test_evento_e_json_serializavel_em_uma_linha(self):
        linha = json.dumps(_evento(raw_command="/loop:review"), ensure_ascii=False)
        assert "\n" not in linha
        assert json.loads(linha)["reason"] == "EXIT_NONZERO"

    def test_conjunto_de_chaves_e_estavel(self):
        esperado = set(CAMPOS_OBRIGATORIOS) | set(CAMPOS_NULLABLE) | {"ts_iso"}
        assert set(_evento().keys()) == esperado

    def test_enums_declarados_batem_com_a_task(self):
        assert SOURCES == {"listener", "recovery", "provider", "subprocess", "gate", "test"}
        assert FAILURE_CLASSES == {
            "semantic",
            "infrastructure",
            "auth",
            "quota",
            "process",
            "recovery",
            "unknown",
        }
        assert CHANNELS == {"interactive", "workspace", "workspace_xterm"}
