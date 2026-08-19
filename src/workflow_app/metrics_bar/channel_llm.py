"""Resolver unico canal -> LLM, alimentado pela ocupacao real dos pares.

Fonte canonica do binding: `ai-forge/rules/llm-routing-div.md` secao 2.

    | canal             | terminal | LLM                                      |
    |-------------------|----------|------------------------------------------|
    | interactive       | T1       | Main LLM (radio `queue-div-main-llm`)    |
    | workspace         | T2       | worker marcado do par T2: kimi | qwen    |
    | workspace_xterm   | T3       | worker marcado do par T3: codex | grok   |

Por que este modulo existe (gap C24, 2026-08-19). `recovery_prompt.py` e
`recovery_context.py` carregavam, cada um, uma COPIA do mapa constante
`workspace -> kimi` / `workspace_xterm -> codex`. Sob `SF_PARALLEL_WORKERS_V2`
desligado o mapa esta certo por construcao (os checkboxes qwen/grok sao
desmarcados E escondidos), mas com o kill-switch ligado ele mente em duas das
quatro combinacoes - e mente exatamente no `--context-file` do
`/tools:listener-recovery`, cujo proposito e dizer a verdade sobre quem falhou.
Duas copias do mesmo mapa ja divergiram uma vez; corrigi-las em duplicata
reintroduziria o defeito por construcao. Aqui o mapa deixa de existir: os dois
consumidores delegam a `resolve_channel_llm`.

Modulo PURO (sem Qt, sem IO) para ser trivialmente testavel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Rosters por par. Um valor fora do roster do par NUNCA e aceito como ocupacao
# viva daquele terminal: `t2_llm="codex"` e dado corrompido, nao um T2 rodando
# Codex, e deve cair no fallback em vez de vazar para o snapshot.
T2_ROSTER: frozenset[str] = frozenset({"kimi", "qwen"})
T3_ROSTER: frozenset[str] = frozenset({"codex", "grok"})

# Defaults de FALLBACK - nao binding de pane. O nome importa: eram exatamente
# estes dois valores que viviam como constante de canal nos dois modulos
# consumidores, e trata-los como binding e o defeito C24.
LEGACY_T2_DEFAULT = "kimi"
LEGACY_T3_DEFAULT = "codex"

# Roster do radio Main (T1). Espelha `MetricsBar._MAIN_LLM_SLUGS` e
# `_MAIN_LLM_SLUGS` do main_window: um slug ausente daqui e clampado para
# "claude", e o artefato de recuperacao passa a nomear o agente errado.
MAIN_ROSTER: frozenset[str] = frozenset(
    {"claude", "codex", "kimi", "qwen", "grok"}
)

# Marca canonica de fallback, reusada LITERALMENTE por recovery_context
# (linha `- llm:`), recovery_prompt (cabecalho) e metrics_bar (toast). Um
# terceiro dialeto de marca faria o operador ver textos diferentes para o
# mesmo estado - que e a forma de silencio que este item existe para matar.
FALLBACK_NOTE = {
    "fallback-no-signal": {
        "workspace": "fallback: ocupacao do par T2 nao recebida",
        "workspace_xterm": "fallback: ocupacao do par T3 nao recebida",
    },
    "fallback-empty-pair": {
        "workspace": "fallback: nenhum worker marcado no par T2",
        "workspace_xterm": "fallback: nenhum worker marcado no par T3",
    },
}


@dataclass(frozen=True)
class ChannelLLM:
    """Resultado tipado da resolucao canal -> LLM.

    `source` distingue os quatro regimes, e a distincao e o coracao da regra
    Zero Silencio deste resolver:

    - ``"live"``                -> ocupacao real recebida pelo sinal.
    - ``"fallback-no-signal"``  -> o sinal NUNCA chegou (consumidor com cache
      `None`). Acontece na sessao recem-aberta, que e justamente quando a
      auto-recuperacao mais dispara.
    - ``"fallback-empty-pair"`` -> o sinal chegou dizendo `""`: o par existe e
      esta legitimamente VAZIO (nenhum worker marcado).
    - ``"unmapped"``            -> canal fora dos tres canonicos.

    Os dois fallbacks devolvem o MESMO llm (o default legado) e precisam ser
    distinguiveis mesmo assim: "nao sei" e "sei que esta vazio" pedem acoes
    diferentes do operador.
    """

    llm: str
    source: str

    @property
    def is_fallback(self) -> bool:
        return self.source.startswith("fallback")

    @property
    def note(self) -> str:
        """Texto canonico da marca de fallback; "" quando nao ha marca."""
        return FALLBACK_NOTE.get(self.source, {}).get(self._channel_hint, "")

    # Preenchido por resolve_channel_llm via object.__setattr__ (frozen).
    # Fora de `repr`/`__eq__` de proposito: e um detalhe interno para escolher
    # o texto de `note` (T2 vs T3), nunca parte da identidade do resultado -
    # um teste que compara `ChannelLLM("qwen", "live")` continua valendo.
    _channel_hint: str = field(default="", compare=False, repr=False)


def _resolve_pair(
    channel: str, value: str | None, roster: frozenset[str], default: str
) -> ChannelLLM:
    """Resolve um par (T2/T3) a partir da ocupacao recebida.

    `None` = sinal nunca recebido; `""` = par vazio; valor fora do roster e
    tratado como ausencia de ocupacao viva (nao vaza para o resultado).
    """
    if value is None:
        return _stamp(ChannelLLM(default, "fallback-no-signal"), channel)
    if value in roster:
        return _stamp(ChannelLLM(value, "live"), channel)
    # `""` e o caso declarado; qualquer outro valor fora do roster e dado
    # corrompido e recebe o MESMO tratamento (degradar, nunca vazar).
    return _stamp(ChannelLLM(default, "fallback-empty-pair"), channel)


def _stamp(result: ChannelLLM, channel: str) -> ChannelLLM:
    object.__setattr__(result, "_channel_hint", channel)
    return result


def resolve_channel_llm(
    channel: str,
    *,
    main_llm: str | None = None,
    t2_llm: str | None = None,
    t3_llm: str | None = None,
    unmapped: str = "claude",
) -> ChannelLLM:
    """Resolve qual LLM ocupa `channel`, com a origem do valor declarada.

    Args:
        channel: "interactive" | "workspace" | "workspace_xterm".
        main_llm: Main LLM do radio (T1). Fora de `MAIN_ROSTER` -> "claude".
        t2_llm: ocupacao do par T2. `None` = sinal nunca recebido; `""` = par
            vazio; valor fora de `T2_ROSTER` e tratado como par vazio.
        t3_llm: simetrico para o par T3.
        unmapped: valor devolvido para canal fora dos tres canonicos. Injetado
            pelo chamador porque os dois consumidores divergem DE PROPOSITO:
            `recovery_prompt` sempre precisa de um destinatario ("claude"),
            enquanto `recovery_context` nunca pode inventar um (`INDISPONIVEL`).

    Returns:
        `ChannelLLM(llm, source)`.
    """
    if channel == "interactive":
        llm = main_llm if main_llm in MAIN_ROSTER else "claude"
        return _stamp(ChannelLLM(llm, "live"), channel)
    if channel == "workspace":
        return _resolve_pair(channel, t2_llm, T2_ROSTER, LEGACY_T2_DEFAULT)
    if channel == "workspace_xterm":
        return _resolve_pair(channel, t3_llm, T3_ROSTER, LEGACY_T3_DEFAULT)
    return _stamp(ChannelLLM(unmapped, "unmapped"), channel)
