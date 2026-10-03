"""Paridade MiMo da area S3: janela principal, barra de metricas, canais,
recuperacao e mascaramento.

Cobre o que o rollout da MiMo mudou fora da fila de comandos:

- Main MiMo nos tres rosters de Main (main_window, MetricsBar e
  channel_llm), com a igualdade travada aqui: sem ela o clamp transforma
  mimo em claude e o app cola comando de Claude no CLI MiMo.
- Pill legada (main/parallel/dual) com Main MiMo: toast warning, nunca cola
  /skill: ou MCP no CLI MiMo (Zero Silencio). Parallel sob Main Claude passa
  a /mcp:mimo (Q9).
- Matriz Thinking/Execution: thinking-mimo-pro -> /mcp:mimo-pro e
  execution-mimo -> /mcp:mimo SEM gate do switch da MiMo (contrato D3).
- Botao de instancia `mimod`: existe so com o switch ligado, passa por
  preflight do launcher, vai para o T2 no ramo legado e repassa o snapshot
  no ramo route-aware.
- Default do par T2 sem ocupacao: mimo com o switch ligado, kimi legado sem
  ele, sempre com marca de fallback no snapshot e no prompt de recuperacao.
- Mascaramento da classe `tp-` (Token Plan MiMo) em create_agent_prompt,
  recovery_context e brainstorm_telemetry.

O switch da MiMo e congelado no import de `feature_flags`. Os testes
in-process trocam o retorno de `feature_flags.mimo_v1_enabled` por
monkeypatch (os consumidores leem pelo atributo do modulo); o que depende do
valor de boot roda em subprocesso. Nomes de flag saem dos helpers de
`feature_flags`, nunca de literal. Amostras de segredo sao SINTETICAS,
montadas por concatenacao: nenhum valor real passa por aqui.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from workflow_app import brainstorm_telemetry as tel
from workflow_app import create_agent_prompt as cap
from workflow_app import main_window as mw
from workflow_app.config import feature_flags
from workflow_app.config.feature_flags import (
    instance_group_route_aware_flag_name,
    llm_config_v2_flag_name,
    mcp_think_exec_v2_enabled,
    mcp_think_exec_v2_flag_name,
    mimo_v1_flag_name,
)
from workflow_app.main_window import MainWindow, TerminalRouteSnapshot
from workflow_app.metrics_bar import channel_llm
from workflow_app.metrics_bar import metrics_bar as mb_mod
from workflow_app.metrics_bar import recovery_context as rc
from workflow_app.metrics_bar import recovery_prompt as rp
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.terminal_helpers import HELPER_COMMANDS

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]
_MAIN_WINDOW_PY = Path(mw.__file__).resolve()

# Regime TE do processo de teste (congelado no boot). Sob t1.sh fica
# desligado, entao a janela in-process monta as pills legadas.
_TE_V2 = mcp_think_exec_v2_enabled()

# Chave sintetica no formato do Token Plan MiMo: `tp-` + 48 alfanumericos.
_TP_SECRET = "tp-" + "zx7" * 16
# Vizinhos que NAO sao segredo: o lookbehind ASCII do padrao (o mesmo do hook)
# deixa http-/ftp-/smtp- de fora (o `t` segue letra) e o `tp-` curto nao chega
# ao piso de 40. Nada de hex (outra classe mascara), barra (path) ou arroba.
_BENIGNOS = (
    "http-" + "zx7" * 16,
    "ftp-" + "zx7" * 16,
    "smtp-" + "zx7" * 16,
    "tp-" + "zx7" * 3,
)


def _switch_mimo(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """Troca o switch da MiMo no ponto em que os consumidores o leem.

    `metrics_bar` chama `feature_flags.mimo_v1_enabled()` pelo atributo do
    modulo, entao o patch vale para a barra construida DEPOIS dele.
    """
    monkeypatch.setattr(feature_flags, "mimo_v1_enabled", lambda: on)


# ---------------------------------------------------------------------------
# Constantes da janela principal e da barra
# ---------------------------------------------------------------------------


def test_te_action_testids_reserva_mimo_pro_na_ordem_da_coluna_thinking():
    ids = list(mw._TE_ACTION_TESTIDS)
    assert len(set(ids)) == len(ids), "testid de alternativa TE duplicado"
    thinking = [t for t in ids if t.startswith("output-mcp-action-thinking-")]
    assert thinking == [
        "output-mcp-action-thinking-fable",
        "output-mcp-action-thinking-opus",
        "output-mcp-action-thinking-codex-ultra",
        "output-mcp-action-thinking-mimo-pro",
        "output-mcp-action-thinking-kimi",
        "output-mcp-action-thinking-grok-xhigh",
    ]
    execution = [t for t in ids if t.startswith("output-mcp-action-execution-")]
    assert thinking + execution == ids, "so alternativas TE, Thinking antes de Execution"
    assert execution.index("output-mcp-action-execution-mimo") < execution.index(
        "output-mcp-action-execution-kimi"
    ), "MiMo vem antes de Kimi na coluna Execution"


def test_main_mimo_nos_tres_rosters_de_main_com_igualdade_travada():
    assert "mimo" in mw._MAIN_LLM_SLUGS
    assert mw._MAIN_LLM_SLUGS == MetricsBar._MAIN_LLM_SLUGS == channel_llm.MAIN_ROSTER, (
        "slug ausente de um dos rosters e clampado para claude naquele consumidor"
    )
    assert mw._MAIN_LLM_LABELS["mimo"] == "MiMo"
    ordem = list(mw._MAIN_LLM_LABELS)
    assert ordem.index("mimo") < ordem.index("kimi"), "MiMo > Kimi na ordem textual"


def test_brainstorm_tem_rotulo_mimo_proprio_e_so_qwen_grok_degradam():
    labels = mw._BRAINSTORM_PROVIDER_LABELS
    assert labels["mimo"] == "MiMo"
    # "MiMo".capitalize() == "Mimo": o rotulo precisa ser explicito.
    assert labels["mimo"] != "mimo".capitalize()
    assert "qwen" not in labels and "grok" not in labels


def test_main_mimo_nao_tem_linha_legada_e_tem_toast_proprio():
    assert mw._MCP_LEGACY_UNSUPPORTED_MAINS == frozenset({"mimo"})
    toast = mw._MCP_LEGACY_UNSUPPORTED_TOAST
    assert "Main MiMo" in toast
    assert "Thinking/Execution" in toast, "o toast aponta a alternativa que funciona"


def test_mcp_test_pinga_mimo_e_descricao_cita_mimo():
    fonte = _MAIN_WINDOW_PY.read_text(encoding="utf-8")
    # Substring sem acento: o literal termina em "conexão" no codigo.
    assert "Pinga MCP Codex, MiMo e Kimi para verificar conex" in fonte
    assert "/mcp:mimo ping test" in fonte


def test_mimod_e_launcher_t2_rotulado_mimo_no_fim_dos_helpers():
    # mimod fica no FIM de HELPER_COMMANDS (decisao do orquestrador): a ordem
    # visivel da barra segue a tupla e nao muda para quem ja tinha os botoes.
    assert HELPER_COMMANDS[-1] == "mimod"
    assert mb_mod._CANONICAL_INSTANCE_NAMES[-1] == "mimod"
    assert mb_mod._MIMO_V1_INSTANCE_NAMES == frozenset({"mimod"})
    assert mb_mod._INSTANCE_BUTTON_LABELS["mimod"] == "mimo"
    assert "mimod" in mb_mod._T2_INSTANCE_LAUNCHERS
    assert "mimod" not in mb_mod._T3_INSTANCE_LAUNCHERS
    # mimo-pro e alias de Thinking, nunca botao de instancia (como kimi-k3).
    assert {"mimo-pro", "kimi-k3"} <= mb_mod._INSTANCE_EXCLUDED_ALIASES


@pytest.mark.parametrize(("ligado", "esperado"), [(True, True), (False, False)])
def test_enabled_instance_names_filtra_mimod_pelo_switch(monkeypatch, ligado, esperado):
    _switch_mimo(monkeypatch, ligado)
    nomes = mb_mod._enabled_instance_names()
    assert ("mimod" in nomes) is esperado
    # O resto da barra nao depende do switch.
    assert [n for n in nomes if n != "mimod"] == [
        n for n in mb_mod._CANONICAL_INSTANCE_NAMES if n != "mimod"
    ]


# ---------------------------------------------------------------------------
# Janela principal com Main MiMo: selects TE, clamp, tooltip e brainstorm
# ---------------------------------------------------------------------------

# Selects Thinking/Execution como o operador os ve, lidos de uma MainWindow em
# subprocesso: o par TE e congelado no boot, entao o regime vem do ambiente.
_TE_COLUNAS_PROBE = '''import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QComboBox
from workflow_app.main_window import MainWindow

app = QApplication.instance() or QApplication([])
window = MainWindow()
colunas = {}
for combo in window.findChildren(QComboBox):
    testid = str(combo.property("testid") or "")
    if testid not in (
        "output-mcp-action-thinking-select",
        "output-mcp-action-execution-select",
    ):
        continue
    colunas[testid] = {
        "rotulos": [combo.itemText(i) for i in range(combo.count())],
        "testids": [str(t) for t in (combo.property("action_item_testids") or [])],
        "comandos": {
            str(k): str(v)
            for k, v in dict(combo.property("te_commands") or {}).items()
        },
    }
print(json.dumps(colunas, sort_keys=True))
window.close()
'''


def _colunas_te(mimo_raw: str | None) -> dict:
    """Selects TE de uma MainWindow nova, com o par TE ligado.

    `mimo_raw` None deixa o switch da MiMo ausente. O ambiente herdado nao
    decide o regime: os switches envolvidos saem antes do boot do filho.
    """
    env = os.environ.copy()
    for nome in (
        mcp_think_exec_v2_flag_name(),
        llm_config_v2_flag_name(),
        mimo_v1_flag_name(),
    ):
        env.pop(nome, None)
    env[mcp_think_exec_v2_flag_name()] = "1"
    if mimo_raw is not None:
        env[mimo_v1_flag_name()] = mimo_raw
    env["QT_QPA_PLATFORM"] = "offscreen"
    res = subprocess.run(
        [sys.executable, "-c", _TE_COLUNAS_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        timeout=180,
        check=False,
    )
    assert res.returncode == 0, f"probe falhou (rc={res.returncode})\n{res.stderr}"
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_te_action_testids_em_paridade_com_os_selects_e_sem_gate_do_switch():
    """`_TE_ACTION_TESTIDS` espelha os selects TE, com e sem o switch MiMo.

    A constante alimenta `_action_testids` (contrato de testids da aba MCPs) e
    os selects sao o que o operador clica: divergencia entre os dois tira uma
    alternativa do contrato. Os rotulos seguem as colunas de `llm_flags`, e o
    switch MiMo nao muda nada aqui (contrato D3).
    """
    from workflow_app.config import llm_flags

    sem = _colunas_te(None)
    com = _colunas_te("1")
    assert com == sem, "o switch MiMo nao pode mexer nos selects TE"
    thinking = sem["output-mcp-action-thinking-select"]
    execution = sem["output-mcp-action-execution-select"]
    assert thinking["testids"] + execution["testids"] == list(mw._TE_ACTION_TESTIDS)
    comandos = {**thinking["comandos"], **execution["comandos"]}
    assert set(comandos) == set(mw._TE_ACTION_TESTIDS)
    assert comandos["output-mcp-action-thinking-mimo-pro"] == "/mcp:mimo-pro"
    assert comandos["output-mcp-action-execution-mimo"] == "/mcp:mimo"
    assert thinking["rotulos"] == [
        flag.removeprefix("--") for flag in llm_flags._THINKING_FLAG_ORDER
    ]
    assert execution["rotulos"] == [
        flag.removeprefix("--") for flag in llm_flags._EXECUTION_FLAG_ORDER
    ]


class _PillFake:
    """Pill legada minima: `property("action_id")` e `setToolTip`."""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        self.tooltip = ""

    def property(self, nome: str) -> str | None:
        return self.action_id if nome == "action_id" else None

    def setToolTip(self, texto: str) -> None:  # noqa: N802 - API Qt
        self.tooltip = texto


class _JanelaMain:
    """Recorte da MainWindow com o Main LLM escolhido pelo teste.

    Reusa os metodos reais sem subir Qt: o que esta sob teste e o caminho do
    slug (clamp, tooltip das pills, FlagsPanel e brainstorm), nao a pintura.
    A tabela legada so tem a linha Claude, como a real: Main MiMo nao tem.
    """

    _current_llm_provider = MainWindow._current_llm_provider
    _mcp_action_tooltip = MainWindow._mcp_action_tooltip
    _on_main_llm_changed = MainWindow._on_main_llm_changed
    _get_brainstorm_runtime_provider = MainWindow._get_brainstorm_runtime_provider

    def __init__(self, main_llm: str) -> None:
        self._command_queue = MagicMock()
        self._command_queue.current_main_llm.return_value = main_llm
        self._mcp_toolbar_commands = {
            "claude": {
                "main": ("/mcp:codex", 1),
                "parallel": ("/mcp:mimo", 1),
                "dual": ("/mcp:dual", 1),
            },
        }
        self._mcp_action_buttons = [
            _PillFake(action_id) for action_id in ("main", "parallel", "dual")
        ]
        self._llm_config_flags_panel = MagicMock()


def test_main_mimo_nao_e_clampado_e_chega_ao_flags_panel():
    janela = _JanelaMain(" MiMo ")
    assert janela._current_llm_provider() == "mimo"
    janela._on_main_llm_changed("mimo")
    # Antes da MiMo entrar no roster o clamp mandava "claude" ao FlagsPanel.
    janela._llm_config_flags_panel.set_main_llm.assert_called_once_with("mimo")


def test_tooltip_das_pills_legadas_com_main_mimo_avisa_indisponivel():
    janela = _JanelaMain("mimo")
    janela._on_main_llm_changed("mimo")
    for pill in janela._mcp_action_buttons:
        assert "\nMain LLM: MiMo" in pill.tooltip, pill.action_id
        assert "Indisponivel com Main MiMo" in pill.tooltip, pill.action_id
        assert "Comando atual" not in pill.tooltip, pill.action_id


def test_tooltip_das_pills_legadas_com_main_claude_nao_cita_indisponivel():
    janela = _JanelaMain("claude")
    janela._on_main_llm_changed("claude")
    for pill in janela._mcp_action_buttons:
        assert "\nMain LLM: Claude" in pill.tooltip, pill.action_id
        assert "Comando atual: " in pill.tooltip, pill.action_id
        assert "Indisponivel" not in pill.tooltip, pill.action_id


@pytest.mark.parametrize(
    ("main_llm", "rotulo"),
    [
        ("mimo", "MiMo"),
        ("kimi", "Kimi"),
        ("codex", "Codex"),
        ("claude", "Claude"),
        ("qwen", "Claude"),
        ("grok", "Claude"),
    ],
)
def test_brainstorm_runtime_rotula_mimo_e_so_qwen_grok_degradam(main_llm, rotulo):
    assert _JanelaMain(main_llm)._get_brainstorm_runtime_provider() == rotulo


def test_current_llm_provider_preserva_o_roster_e_clampa_o_resto():
    for slug in sorted(mw._MAIN_LLM_SLUGS):
        assert _JanelaMain(slug)._current_llm_provider() == slug
    # `mimo-pro` e literal de flag, nunca slug do eixo Main.
    assert _JanelaMain("mimo-pro")._current_llm_provider() == "claude"
    assert _JanelaMain("")._current_llm_provider() == "claude"


# ---------------------------------------------------------------------------
# Resolucao canal -> LLM (funcoes puras)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("ligado", "esperado"), [(True, "mimo"), (False, "kimi")])
def test_t2_fallback_default_segue_o_switch(ligado, esperado):
    assert channel_llm.t2_fallback_default(ligado) == esperado


def test_main_mimo_e_ocupacao_viva_no_interactive():
    res = channel_llm.resolve_channel_llm("interactive", main_llm="mimo")
    assert (res.llm, res.source, res.is_fallback) == ("mimo", "live", False)


def test_t2_mimo_marcado_e_vivo_mesmo_com_default_legado():
    res = channel_llm.resolve_channel_llm(
        "workspace", t2_llm="mimo", t2_default="kimi"
    )
    assert (res.llm, res.source) == ("mimo", "live")


@pytest.mark.parametrize(
    ("t2_llm", "nota"),
    [
        (None, "fallback: ocupacao do par T2 nao recebida"),
        ("", "fallback: nenhum worker marcado no par T2"),
    ],
)
def test_par_t2_sem_ocupacao_cai_no_default_mimo_com_marca(t2_llm, nota):
    res = channel_llm.resolve_channel_llm(
        "workspace", t2_llm=t2_llm, t2_default="mimo"
    )
    assert res.llm == "mimo"
    assert res.is_fallback
    assert res.note == nota


@pytest.mark.parametrize("t2_default", [None, "codex", "claude"])
def test_default_t2_ausente_ou_fora_do_roster_volta_ao_kimi_legado(t2_default):
    res = channel_llm.resolve_channel_llm("workspace", t2_default=t2_default)
    assert res.llm == "kimi"
    assert res.is_fallback


# ---------------------------------------------------------------------------
# Recuperacao: prompt e snapshot
# ---------------------------------------------------------------------------


def test_prompt_de_recuperacao_nomeia_mimo_e_usa_o_bloco_azul_generico():
    texto = rp.build_recovery_prompt(llm="mimo", reason="BLOCKED", channel="workspace")
    assert "[AUTO-RECUPERACAO] Canal: workspace | Falha: BLOCKED | LLM: mimo\n" in texto
    # O CLI MiMo nao tem /tools:auq-interview (slash-command Claude).
    assert ">>> PERGUNTA AO OPERADOR <<<" in texto
    assert "/tools:auq-interview" not in texto
    assert not texto.startswith("["  + "fallback"), "sem llm_source nao ha marca"


def test_prompt_de_recuperacao_marca_o_fallback_do_par_t2():
    fonte = rp.llm_source_for_channel("workspace", "claude", t2_default="mimo")
    assert fonte.llm == "mimo" and fonte.is_fallback
    texto = rp.build_recovery_prompt(
        llm=fonte.llm, reason="BLOCKED", channel="workspace", llm_source=fonte
    )
    assert texto.startswith("[fallback: ocupacao do par T2 nao recebida]\n")
    assert "| LLM: mimo\n" in texto


def test_prompt_de_recuperacao_com_main_mimo_no_interactive():
    assert rp.llm_for_channel("interactive", "mimo") == "mimo"
    texto = rp.build_recovery_prompt(llm="mimo", reason="RESSALVAS", channel="interactive")
    assert "| LLM: mimo\n" in texto


_QUANDO = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("t2_llm", "linha"),
    [
        (None, "- llm: mimo (fallback: ocupacao do par T2 nao recebida)"),
        ("", "- llm: mimo (fallback: nenhum worker marcado no par T2)"),
        ("mimo", "- llm: mimo\n"),
    ],
)
def test_snapshot_de_recuperacao_com_default_mimo(t2_llm, linha):
    ctx = rc.RecoveryContext("workspace", "BLOCKED", t2_llm=t2_llm, t2_default="mimo")
    corpo = rc.render_context(ctx, when=_QUANDO)
    assert linha in corpo


def test_snapshot_sem_t2_default_mantem_o_kimi_legado_byte_a_byte():
    ctx = rc.RecoveryContext("workspace", "BLOCKED")
    corpo = rc.render_context(ctx, when=_QUANDO)
    assert "- llm: kimi (fallback: ocupacao do par T2 nao recebida)" in corpo


def test_snapshot_com_main_mimo_no_interactive_e_vivo():
    ctx = rc.RecoveryContext("interactive", "BLOCKED", main_llm="mimo")
    corpo = rc.render_context(ctx, when=_QUANDO)
    assert "- llm: mimo\n" in corpo
    assert rc.llm_for_channel("interactive", "mimo") == "mimo"


# ---------------------------------------------------------------------------
# Mascaramento da classe tp- (Token Plan MiMo)
# ---------------------------------------------------------------------------


def test_redact_secrets_mascara_token_plan_e_e_idempotente():
    uma = cap.redact_secrets("chave " + _TP_SECRET + " fim")
    assert _TP_SECRET not in uma
    assert uma == "chave [REDACTED] fim"
    assert cap.redact_secrets(uma) == uma


@pytest.mark.parametrize("benigno", _BENIGNOS)
def test_redact_secrets_preserva_vizinhos_benignos(benigno):
    texto = "valor " + benigno + " fim"
    assert cap.redact_secrets(texto) == texto


def test_validate_name_recusa_token_plan_sem_ecoar_o_valor():
    with pytest.raises(cap.CreateAgentPromptError) as info:
        cap.validate_name("agente " + _TP_SECRET)
    assert info.value.field == "name"
    assert _TP_SECRET not in str(info.value)


def test_validate_description_recusa_token_plan_sem_ecoar_o_valor():
    with pytest.raises(cap.CreateAgentPromptError) as info:
        cap.validate_description("descricao com " + _TP_SECRET)
    assert info.value.field == "description"
    assert _TP_SECRET not in str(info.value)


@pytest.mark.parametrize("benigno", _BENIGNOS)
def test_validadores_aceitam_vizinhos_benignos(benigno):
    assert cap.validate_name("agente " + benigno) == "agente " + benigno
    assert cap.validate_description("texto " + benigno) == "texto " + benigno


def test_recovery_context_redige_token_plan_no_output_e_no_comando():
    saida = rc.mask_output("falhou depois de " + _TP_SECRET)
    assert _TP_SECRET not in saida
    assert "[REDACTED]" in saida
    comando = rc.mask_command("export TOKEN_X=" + _TP_SECRET)
    assert _TP_SECRET not in comando
    assert comando == "export TOKEN_X=[REDACTED]"


def test_telemetria_mascara_token_plan_com_rotulo_proprio():
    assert tel.scrub("k " + _TP_SECRET) == "k ***mimo-token-plan***"


@pytest.mark.parametrize("benigno", _BENIGNOS)
def test_telemetria_preserva_vizinhos_benignos(benigno):
    assert tel.scrub(benigno) == benigno
