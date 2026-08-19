"""Loop 08-17-systemforge-multillm-gaps-refactor, item 013 (gap C24).

Resolver unico de `canal -> LLM`. Antes deste modulo existiam DOIS mapas
constantes (`recovery_prompt` e `recovery_context`) afirmando
`workspace=kimi` / `workspace_xterm=codex`. A afirmacao virou mentira quando
`SF_PARALLEL_WORKERS_V2` expos qwen e grok: o snapshot diagnostico da
auto-recuperacao passou a nomear o LLM errado com total confianca.

Invariantes fechadas aqui:

- **G-1 (verdade)**: com ocupacao real propagada, o par responde quem esta la.
- **G-2 (nao-regressao)**: sem ocupacao (regime legado / kill-switch off), o
  comportamento observavel e byte-identico ao anterior. Testes marcados
  `test_legacy_regime_*` para selecao via `-k legacy`.
- **G-3 (Zero Silencio)**: ausencia de sinal NUNCA vira certeza; sai marcada,
  e as duas ausencias possiveis (sinal nao chegou / par vazio) tem textos
  distintos.
"""

from __future__ import annotations

import pytest

from workflow_app.metrics_bar.channel_llm import (
    LEGACY_T2_DEFAULT,
    LEGACY_T3_DEFAULT,
    T2_ROSTER,
    T3_ROSTER,
    ChannelLLM,
    resolve_channel_llm,
)

# ── G-2: regime legado (nenhuma ocupacao propagada) ───────────────────────── #


@pytest.mark.parametrize(
    ("channel", "expected"),
    [("workspace", LEGACY_T2_DEFAULT), ("workspace_xterm", LEGACY_T3_DEFAULT)],
)
def test_legacy_regime_pairs_keep_historic_defaults(channel, expected):
    result = resolve_channel_llm(channel)
    assert result.llm == expected


def test_legacy_regime_interactive_defaults_to_claude():
    assert resolve_channel_llm("interactive").llm == "claude"


def test_legacy_regime_interactive_ignores_pair_occupancy():
    """T1 nunca foi funcao dos pares: ocupacao de worker nao pode vaza-la."""
    result = resolve_channel_llm("interactive", main_llm="grok", t2_llm="qwen")
    assert result.llm == "grok"


def test_legacy_regime_unknown_channel_uses_unmapped():
    result = resolve_channel_llm("garbage", unmapped="INDISPONIVEL")
    assert result.llm == "INDISPONIVEL"
    assert result.source == "unmapped"


def test_legacy_regime_unknown_channel_default_unmapped_is_claude():
    assert resolve_channel_llm("garbage").llm == "claude"


# ── G-1: ocupacao real vence ──────────────────────────────────────────────── #


@pytest.mark.parametrize("llm", sorted(T2_ROSTER))
def test_t2_roster_resolves_live(llm):
    result = resolve_channel_llm("workspace", t2_llm=llm)
    assert result == ChannelLLM(llm, "live")
    assert not result.is_fallback
    assert result.note == ""


@pytest.mark.parametrize("llm", sorted(T3_ROSTER))
def test_t3_roster_resolves_live(llm):
    result = resolve_channel_llm("workspace_xterm", t3_llm=llm)
    assert result == ChannelLLM(llm, "live")
    assert not result.is_fallback


def test_qwen_in_t2_is_named_qwen():
    """A assercao literal do gap C24: qwen no T2 nao pode responder `kimi`."""
    assert resolve_channel_llm("workspace", t2_llm="qwen").llm == "qwen"


def test_pairs_do_not_cross_contaminate():
    """Ocupacao do T2 nao pode responder pelo T3 e vice-versa."""
    result = resolve_channel_llm("workspace_xterm", t2_llm="qwen")
    assert result.llm == LEGACY_T3_DEFAULT
    assert result.is_fallback


# ── G-3: as duas ausencias saem marcadas e distintas ──────────────────────── #


def test_no_signal_is_marked_fallback():
    result = resolve_channel_llm("workspace")
    assert result.source == "fallback-no-signal"
    assert result.is_fallback
    assert "nao recebida" in result.note


def test_empty_pair_is_marked_fallback():
    result = resolve_channel_llm("workspace", t2_llm="")
    assert result.source == "fallback-empty-pair"
    assert result.is_fallback
    assert "nenhum worker marcado" in result.note


def test_the_two_absences_are_distinguishable():
    sem_sinal = resolve_channel_llm("workspace")
    vazio = resolve_channel_llm("workspace", t2_llm="")
    assert sem_sinal.llm == vazio.llm  # mesmo chute...
    assert sem_sinal.note != vazio.note  # ...com procedencias distintas


def test_fallback_notes_name_the_right_pair():
    assert "T2" in resolve_channel_llm("workspace").note
    assert "T3" in resolve_channel_llm("workspace_xterm").note


def test_out_of_roster_value_degrades_to_marked_fallback():
    """Valor invalido nunca e repassado adiante como se fosse ocupacao."""
    result = resolve_channel_llm("workspace", t2_llm="codex")
    assert result.llm == LEGACY_T2_DEFAULT
    assert result.is_fallback


def test_channel_hint_does_not_leak_into_identity():
    """O hint interno de canal nao pode entrar em igualdade nem em repr."""
    result = resolve_channel_llm("workspace", t2_llm="qwen")
    assert result == ChannelLLM("qwen", "live")
    assert "workspace" not in repr(result)


# ── G-2 no widget: kill-switch desligado (ST008.7) ────────────────────────── #
#
# O regime legado NAO se forca pela env var do shell: `SF_PARALLEL_WORKERS_V2`
# e lida por `parallel_workers_v2_enabled()` num import local dentro do
# `__init__` do widget, entao o monkeypatch tem que ser no simbolo do modulo
# de feature flags, antes da construcao.


def _legacy_widget(monkeypatch):
    import workflow_app.config.feature_flags as ff
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    monkeypatch.setattr(ff, "parallel_workers_v2_enabled", lambda: False)
    return CommandQueueWidget()


def test_legacy_regime_occupancy_never_names_qwen_or_grok(qapp, monkeypatch):
    """Com o kill-switch off, qwen/grok sao desmarcados e escondidos.

    A ocupacao emitida so pode ser `("kimi", "")`, `("", "codex")`, `("", "")`
    ou a combinacao dos dois marcados - jamais um provider V2.
    """
    from workflow_app.signal_bus import signal_bus

    w = _legacy_widget(monkeypatch)
    seen: list[tuple[str, str]] = []
    signal_bus.worker_occupancy_changed.connect(
        lambda t2, t3: seen.append((t2, t3))
    )
    try:
        assert not w._use_qwen_chk.isVisible()
        assert not w._use_grok_chk.isVisible()
        assert w._resolve_worker_occupancy() == ("", "")

        w._use_kimi_chk.setChecked(True)
        assert seen[-1] == ("kimi", "")
        w._use_codex_chk.setChecked(True)
        assert seen[-1] == ("kimi", "codex")
        for t2, t3 in seen:
            assert t2 not in {"qwen", "grok"}
            assert t3 not in {"qwen", "grok"}
    finally:
        signal_bus.worker_occupancy_changed.disconnect()


def test_legacy_regime_snapshot_llm_line_unchanged(qapp, monkeypatch, tmp_path):
    """G-2 fim-a-fim: o snapshot do regime legado e o de sempre.

    `kimi` marcado -> ocupacao viva `kimi` (sem marca de fallback), que e
    literalmente o mesmo texto que o mapa constante produzia.
    """
    from workflow_app.metrics_bar.recovery_context import (
        RecoveryContext,
        render_context,
    )

    w = _legacy_widget(monkeypatch)
    w._use_kimi_chk.setChecked(True)
    w._use_codex_chk.setChecked(True)
    t2, t3 = w._resolve_worker_occupancy()

    for channel, expected in (
        ("workspace", "- llm: kimi"),
        ("workspace_xterm", "- llm: codex"),
    ):
        ctx = RecoveryContext(
            channel=channel,
            reason="BLOCKED",
            autocast_state="on",
            t2_llm=t2,
            t3_llm=t3,
        )
        from datetime import datetime, timezone

        rendered = render_context(
            ctx, when=datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        )
        assert expected in rendered.splitlines()
