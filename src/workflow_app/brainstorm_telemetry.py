"""
Telemetria do bloco brainstorm-mcp -- torna o USO dos botoes observavel.

Motivacao (C4 do loop `08-25-systemforge-analise-fluxo-brainstorm`). O bloco
inteiro persistia exatamente UM evento estruturado: o `t3_publish_failed` do
handler. Consequencia pratica: nao existe base para decidir aposentadoria de
botao (G14), "zero uso" nao distingue botao nunca clicado de botao clicado e
BLOQUEADO, e a degradacao qwen/grok -> Claude do radio de provider e invisivel.

Este modulo espelha o precedente vivo `dispatch_telemetry.py` (sidecar JSONL
por PID em `~/.workflow-app/logs`, `_lock`, `_seq`, `except OSError: pass`,
`jsonl_path`, `_reset_for_tests`) com quatro endurecimentos proprios:

1. **Allowlist FECHADA de campos** (`FIELD_ALLOWLIST`). O sidecar so aceita as
   chaves declaradas; campo desconhecido e descartado em producao e LEVANTA em
   modo estrito (teste). Sem isso a allowlist seria documentacao, e o teste que
   a verifica so provaria que ninguem errou ainda.
2. **`reason` de conjunto fechado** (`HANDLER_REASONS`, `WIDGET_REASONS`), com
   os dois conjuntos DISJUNTOS: um motivo de widget gravado como evento de
   handler e erro de instrumentacao, nao um dado curioso.
3. **Nunca o prompt.** O texto despachado nao entra aqui em nenhuma forma --
   nem truncado, nem hasheado. Entra `prompt_chars`, que responde "houve texto"
   sem carregar o texto. (`dispatch_telemetry` grava 240 chars do comando; ali
   o comando e um slash-command curto, aqui o prompt e o corpo inteiro de uma
   persona somado ao contexto publico do projeto.)
4. **Scrub no ESCRITOR, nao no chamador.** Todo valor string passa por
   `scrub()` antes de virar linha, entao um chamador futuro descuidado nao
   consegue vazar por esquecimento **as classes que `scrub()` reconhece**.
   O alcance exato, para nao ser lido como promessa maior do que e:

   - A allowlist fecha NOMES DE CAMPO, nunca a natureza do conteudo.
     `action`, `button_id`, `testid_slug` e `artifact_id` sao texto livre do
     ponto de vista do escritor: quem chamar `record_dispatch(action=prompt)`
     grava prompt. O que limita o estrago e `scrub()` -- corte na primeira
     quebra de linha e teto de `_MAX_VALUE_CHARS` -- e nao a allowlist.
   - `scrub()` mascara por FORMATO. Segredo sem formato reconhecivel (um
     token opaco curto, uma senha que e uma palavra) passa intacto. As
     classes cobertas sao exatamente `_SECRET_PATTERNS`, e a lista e
     ampliavel: quando uma classe nova aparecer, ela entra la.
   - O que E garantido: nenhum valor multi-linha e persistido inteiro,
     nenhum valor passa de `_MAX_VALUE_CHARS`, nenhum path absoluto
     sobrevive e as 13 classes do hook de segredos sao mascaradas.

## Mascaramento: por FORMATO, nunca por nome de chave

Mascarar por nome de chave falha no dia em que o segredo chega numa chave com
outro nome -- e o valor sob `artifact_id` e tao capaz de conter um path
absoluto quanto o valor sob `path`. Aqui o julgamento e sempre sobre o VALOR.

**Paridade com `pretool-bash-secrets.sh`: medida, nao herdada.** O comentario
de `dispatch_telemetry.py:46-57` afirma cobrir "as mesmas classes que
`pretool-bash-secrets.sh` bloqueia". A afirmacao foi VERIFICADA em 2026-08-26
contra `.claude/hooks/pretool-bash-secrets.sh` e e **falsa**. Medicao, classe a
classe, com uma amostra por classe gerada a partir do padrao do proprio hook:
dos 4 padroes do precedente, 3 cobrem 6 das 13 classes -- e duas dessas seis
por acidente, nao por desenho (`sk-[A-Za-z0-9_-]{16,}` engloba as tres chaves
`sk-*`, e o `bearer` case-insensitive engloba tambem o `Authorization:
Bearer`). Ficam
DESCOBERTAS sete: `sbp_` (supabase-pat), `ghp_` (github-pat), `ghs_`
(github-app-secret), `vcp_` (vercel-token), `rly_` (railway-pat), `password=`
e `secret=`. Este modulo NAO herda aquela promessa: `_SECRET_PATTERNS` abaixo
reimplementa as 13 classes do hook explicitamente, mais o email (que o hook nao
tem e o precedente tem).

A verificacao nao vive so aqui: `tests/test_brainstorm_telemetry.py`
(`test_toda_classe_do_hook_de_segredos_e_mascarada_aqui`) reparseia o hook a
cada execucao e falha quando ele ganha uma classe que este modulo nao mascara.
Provado nao-vacuo por mutacao: removidos `ghp_` e `sbp_` daqui, o gate acusa
exatamente essas duas.

## Politica de telemetria: local, sem opt-out, declarada

Ate aqui a politica existia por omissao. Declarada: os eventos ficam APENAS em
disco local, no home do proprio operador (`~/.workflow-app/logs`), nunca sao
transmitidos para lugar nenhum, nao ha coleta remota, nao ha identificador de
usuario e nao ha opt-out. Quem quiser parar de gerar sidecar apaga o
diretorio -- ele e recriado no proximo evento. O conteudo e limitado pela
allowlist deste modulo e por `scrub()`; auditar o que e gravado e ler
`FIELD_ALLOWLIST` e rodar `tests/test_brainstorm_telemetry.py`.

## Limitacao conhecida do `dispatch_id`

O formato e `{pid}-{seq}` e ele **nao e unico entre execucoes**: o SO recicla
PID e `_seq` reinicia em 1 a cada processo. Dois eventos de dias diferentes
podem colidir. Ele serve para correlacionar eventos DENTRO de uma execucao (e
o sidecar e por PID, entao dentro de um arquivo a colisao nao acontece);
qualquer agregacao entre arquivos precisa parear `dispatch_id` com `pid` e com
`ts`, nunca usar `dispatch_id` sozinho como chave.

Correlacao entre widget e handler NAO existe por desenho: um clique bloqueado
(`click_blocked`) nunca chega ao handler, entao nao ha par a formar. Um clique
que passa produz o `dispatch` do handler e nada no widget.

## Nada aqui pode derrubar um dispatch

Toda funcao publica e best-effort e engole as proprias excecoes -- com uma
excecao deliberada: em modo estrito (so testes), violacao de allowlist ou de
conjunto de `reason` LEVANTA, porque um gate que se cala em teste nao e gate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Versao do schema do sidecar. Muda quando um campo sai ou muda de sentido.
SCHEMA_VERSION = "brainstorm-mcp-dispatch/1"

#: Diretorio REAL do sidecar. Capturado uma unica vez no import e NUNCA
#: reatribuido -- `_reset_for_tests` move `_LOG_DIR`, nao este. E a
#: referencia contra a qual a guarda de suite compara.
_DEFAULT_LOG_DIR = Path.home() / ".workflow-app" / "logs"

#: Guarda de suite, no mesmo desenho de `WF_BLOCK_REAL_FAILURE_TELEMETRY`.
#:
#: A licao ja foi paga uma vez neste repo: 760 dos 2.553 eventos do corte
#: auditado de `.claude/wf-failures/` eram ruido de pytest, nao de
#: producao. Instrumentar os pontos de termino do brainstorm sem esta
#: guarda reproduziria exatamente isso -- cada MainWindow construida na
#: suite despacha cliques, e cada clique viraria um evento no sidecar real
#: do operador.
GUARD_ENV = "WF_BLOCK_REAL_BRAINSTORM_TELEMETRY"

_LOG_DIR = _DEFAULT_LOG_DIR
_JSONL_PATH = _LOG_DIR / f"brainstorm-telemetry-{os.getpid()}.jsonl"

# ---------------------------------------------------------------------------
# Allowlist de campos (FECHADA)
# ---------------------------------------------------------------------------

#: Chaves que o sidecar aceita. Qualquer outra e descartada (producao) ou
#: levanta (modo estrito). Adicionar campo aqui e mudanca de schema: bumpar
#: `SCHEMA_VERSION` junto.
FIELD_ALLOWLIST: frozenset[str] = frozenset({
    # Cabecalho, escrito por `_emit_record` em todo evento.
    "schema",
    "ts",
    "monotonic",
    "pid",
    "seq",
    "dispatch_id",
    "event",
    "reason",
    # Identidade do botao. `testid_slug` e o slug canonico do seed; `button_id`
    # e o objectName do widget. Nenhum dos dois carrega path.
    "button_id",
    "testid_slug",
    "action",
    "source_kind",
    # Identidade do artefato alvo: sha256 truncado do path RELATIVO ao repo.
    # Nunca o path.
    "artifact_id",
    # Os DOIS eixos de provider. So o par torna a degradacao mensuravel.
    "requested_provider",
    "resolved_provider",
    # Roteamento e resultado.
    "terminal",
    "ok",
    # Tamanho do prompt. O prompt em si NUNCA entra.
    "prompt_chars",
})

#: Eventos possiveis.
EVENT_CLICK_BLOCKED = "click_blocked"
EVENT_DISPATCH = "dispatch"
EVENTS: frozenset[str] = frozenset({EVENT_CLICK_BLOCKED, EVENT_DISPATCH})

#: Motivos de termino do handler `_on_mcp_prompt_requested`.
#:
#: Um por caminho de termino, contados NO CODIGO ATUAL (pos-C2/C5/C6) e nao na
#: leitura antiga do plano: sao NOVE, nao sete. Os dois a mais nasceram do PR1
#: -- a revalidacao `is_file()` do `.md` (`md_missing`) e o invariante de rota
#: unica (`route_ambiguous`) -- e instrumentar "sete" deixaria justamente os
#: dois caminhos mais novos mudos.
HANDLER_REASONS: frozenset[str] = frozenset({
    "in_flight",           # gate de reentrancia; era o ponto cego prioritario
    "no_md_selected",      # gate Zero Silencio: edit_inplace sem picker
    "md_missing",          # revalidacao no dispatch: o .md sumiu do disco
    "prompt_rejected",     # build_prompt levantou ValueError (contrato)
    "prompt_build_error",  # build_prompt levantou TypeError (defeito)
    "route_ambiguous",     # len(targets) != 1
    "publish_exception",   # a publicacao levantou
    "publish_failed",      # T3 devolveu False (shell nao iniciado)
    "handler_exception",   # excecao inesperada: registra, avisa e relevanta
    "ok",                  # sucesso real
})

#: Motivos de termino de `MCPPromptButton._on_clicked` ANTES do emit.
#:
#: Sem estes, "zero uso" confunde botao nunca clicado com botao clicado e
#: bloqueado -- e o segundo caso e o oposto de um candidato a aposentadoria.
WIDGET_REASONS: frozenset[str] = frozenset({
    "codex_unavailable",   # gate T7: button_type fixo Codex sem T3 vivo
    "debounced",           # gate T6: clique dentro da janela de 300ms
    "redispatch_declined", # gate T6: operador recusou o "disparar de novo?"
})

_REASONS: frozenset[str] = HANDLER_REASONS | WIDGET_REASONS

if HANDLER_REASONS & WIDGET_REASONS:  # pragma: no cover - invariante de import
    raise AssertionError(
        "HANDLER_REASONS e WIDGET_REASONS precisam ser disjuntos: "
        f"{sorted(HANDLER_REASONS & WIDGET_REASONS)}"
    )

_REASONS_BY_EVENT: dict[str, frozenset[str]] = {
    EVENT_DISPATCH: HANDLER_REASONS,
    EVENT_CLICK_BLOCKED: WIDGET_REASONS,
}

# ---------------------------------------------------------------------------
# Mascaramento por FORMATO
# ---------------------------------------------------------------------------

#: As 13 classes de `.claude/hooks/pretool-bash-secrets.sh`, reimplementadas
#: aqui de proposito (ver o bloco "Paridade" na docstring do modulo), mais o
#: email. Cada entrada e (padrao, rotulo) -- o rotulo entra na substituicao
#: para que o sidecar diga O QUE foi mascarado sem dizer qual valor era.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-api\d+-[A-Za-z0-9_-]{80,}"), "anthropic-api-key"),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{40,}"), "openai-sk-proj"),
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "sk-token"),
    (re.compile(r"sbp_[a-f0-9]{40}"), "supabase-pat"),
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "github-pat"),
    (re.compile(r"ghs_[A-Za-z0-9]{36,}"), "github-app-secret"),
    (re.compile(r"vcp_[A-Za-z0-9]{30,}"), "vercel-token"),
    (re.compile(r"rly_[A-Za-z0-9]{20,}"), "railway-pat"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        "jwt",
    ),
    (re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{12,}"), "auth-header"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"), "bearer-token"),
    (re.compile(r"(?i)password=[^\s'\"]{8,}"), "password-inline"),
    (re.compile(r"(?i)secret=[^\s'\"]{8,}"), "secret-inline"),
    # Generico de atribuicao: `TAVILY_API_KEY=tvly-...`, `apiToken: abc...`.
    # O hook so conhece `password=` e `secret=`; segredo de terceiro com
    # prefixo proprio (tvly-, SG., xoxb-) nao casa nenhum dos 13 padroes e
    # chegava intacto ao JSONL. Aqui o gatilho e o NOME a esquerda do `=`,
    # que e o que esses valores tem em comum.
    (
        re.compile(
            r"(?i)\b[a-z0-9_.-]*(?:api[_-]?key|access[_-]?key|secret[_-]?key"
            r"|auth[_-]?token|api[_-]?token|credential)[a-z0-9_.-]*"
            r"\s*[=:]\s*[^\s'\"]{8,}"
        ),
        "credential-assignment",
    ),
    # Token hexadecimal longo (Twilio, chaves de servico sem prefixo). O
    # piso de 32 e deliberado: `artifact_id` tem 16 e nao pode ser
    # mascarado -- ele existe justamente para ser o identificador legivel.
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "hex-token"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
)

#: Path absoluto POSIX (`/home/...`) ou Windows (`C:\...`, `\\servidor\...`).
#:
#: Path absoluto nao e segredo, mas identifica a maquina e o usuario, e o
#: criterio de aceite de C4 e "nenhum VALOR casa padrao de path absoluto".
#: Redigir no escritor faz o criterio valer para chamador que ainda nao existe.
_ABS_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![A-Za-z0-9_])/(?:[^\s/\\:*?\"<>|]+/)*[^\s/\\:*?\"<>|]*"),
    re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\[^\s\"<>|]*"),
    re.compile(r"\\\\[^\s\"<>|]+"),
)

#: Teto por valor string. Nenhum campo da allowlist e texto livre; um valor
#: longo aqui significa que alguem passou conteudo por engano.
_MAX_VALUE_CHARS = 200


def scrub(text: str) -> str:
    """Mascara segredos por formato e redige paths absolutos.

    Aplicado pelo ESCRITOR a todo valor string, antes de qualquer persistencia.
    A ordem importa: segredo primeiro (um `Bearer ...` pode conter `/`), path
    depois.
    """
    out = text
    # Nenhum campo da allowlist e texto de multiplas linhas: os quatro que
    # aceitam string livre (`action`, `button_id`, `testid_slug`,
    # `artifact_id`) sao identificadores de uma linha so. Prompt, traceback
    # e bloco de configuracao -- as tres coisas que um chamador descuidado
    # depositaria aqui -- sao multi-linha. Cortar na primeira quebra nao
    # torna o vazamento impossivel; tira dele o corpo, e o resto cai no teto.
    if "\n" in out or "\r" in out:
        out = re.split(r"[\r\n]", out, maxsplit=1)[0] + "...(+multilinha)"
    for pattern, rotulo in _SECRET_PATTERNS:
        out = pattern.sub(f"***{rotulo}***", out)
    for pattern in _ABS_PATH_PATTERNS:
        out = pattern.sub("***path***", out)
    if len(out) > _MAX_VALUE_CHARS:
        out = out[:_MAX_VALUE_CHARS] + f"...(+{len(out) - _MAX_VALUE_CHARS})"
    return out


def artifact_id(path: str | Path | None, root: str | Path | None) -> str:
    """sha256 truncado (16 hex) do path RELATIVO a `root`. Nunca o path.

    Devolve `""` quando nao ha artefato selecionado -- ausencia e um dado
    legitimo (a maioria dos botoes nao edita `.md`) e nao deve virar hash de
    string vazia, que pareceria um artefato real.

    Path FORA de `root` tambem vira `""`: o path relativo seria uma escada de
    `..` carregando a topologia da maquina, exatamente o que o hash existe
    para nao carregar.

    **Limitacao declarada:** o id segue o PATH, nao o conteudo. Renomear ou
    mover o `.md` quebra a cadeia e o mesmo trabalho aparece como dois
    artefatos. Usar o id como proxy de retrabalho e hipotese, nao medicao.
    """
    if not path or root is None:
        return ""
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return ""
    return hashlib.sha256(rel.as_posix().encode("utf-8")).hexdigest()[:16]


def source_kind_for(seed_path: str | Path | None, root: str | Path | None) -> str:
    """`seed` | `supplemental` | `unknown` a partir do path do corpo do botao.

    Le os dois diretorios do contrato canonico (`brainstorm_seed_contract`) em
    vez de repetir as strings: a localizacao dos seeds ja mudou uma vez
    (migracao da Task 08) e uma copia aqui teria envelhecido calada.

    `unknown` nao e erro: botao construido por caller programatico ou por
    registry de agente pode legitimamente nao ter corpo em `seeds/`.
    """
    if not seed_path or root is None:
        return "unknown"
    try:
        from workflow_app.brainstorm_seed_contract import (
            BRAINSTORM_SEEDS_RELDIR,
            SUPPLEMENTAL_SEEDS_RELDIR,
        )

        base = Path(root).resolve()
        alvo = Path(seed_path).resolve()
        if alvo.is_relative_to(base / SUPPLEMENTAL_SEEDS_RELDIR):
            return "supplemental"
        if alvo.is_relative_to(base / BRAINSTORM_SEEDS_RELDIR):
            return "seed"
    except (OSError, ValueError, ImportError):
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Estado do modulo
# ---------------------------------------------------------------------------

#: Teto de latencia de UMA escrita, em segundos.
#:
#: `_write_jsonl` roda na thread da UI, dentro do clique, e o `finally` do
#: handler so agenda a liberacao de `_prompt_in_flight` DEPOIS que ela
#: retorna. Em home montado em rede, disco cheio ou antivirus interceptando
#: `open`, a latencia da telemetria estica a janela de reentrancia e o
#: proprio bloco passa a classificar cliques legitimos como `in_flight` --
#: a instrumentacao fabricando o evento que ela existe para medir.
#:
#: Uma escrita lenta e aceitavel; uma sessao inteira delas nao. Na primeira
#: que estoura o teto o sidecar se desliga ate o proximo processo. Perder
#: telemetria e o dano menor: o dano maior e congelar o dispatch.
_SLOW_WRITE_SECONDS = 0.25
_writer_disabled = False

_lock = threading.Lock()
_seq = 0
_strict = os.environ.get("WORKFLOW_APP_TELEMETRY_STRICT") == "1"


def _strict_mode() -> bool:
    return _strict


def _violation(msg: str) -> None:
    """Allowlist/conjunto violado: levanta em teste, descarta em producao."""
    if _strict_mode():
        raise ValueError(msg)
    logger.debug("[brainstorm-telemetry] %s", msg)


def _mesmo_diretorio(a: str | Path, b: str | Path) -> bool:
    """Igualdade de diretorio RESOLVIDA, nunca lexical.

    `~/.workflow-app/logs/../logs` e `~/.workflow-app/logs` sao strings
    diferentes e o mesmo diretorio para o SO. Comparar texto deixava a
    guarda liberar e o byte cair no disco do operador.
    """
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except (OSError, RuntimeError):  # pragma: no cover - FS hostil
        return str(a) == str(b)


def real_sidecar_blocked(log_dir: str | Path | None) -> bool:
    """A guarda de suite veda ESTE diretorio?

    So o diretorio real e vedado. Um `log_dir` de `tmp_path` continua
    gravando normalmente -- sem isso a propria suite da telemetria, que
    precisa ler o que escreveu, nao teria como se testar.
    """
    if log_dir is None or os.environ.get(GUARD_ENV) != "1":
        return False
    return _mesmo_diretorio(log_dir, _DEFAULT_LOG_DIR)


def _write_jsonl(record: dict[str, Any]) -> None:
    global _writer_disabled
    if _writer_disabled:
        return
    # A guarda julga o diretorio que ESTA linha vai abrir, nunca o global
    # que alguem pretendia usar. Enquanto ela lia `_LOG_DIR`, bastava
    # `_LOG_DIR` e `_JSONL_PATH` divergirem -- dois globais, um so
    # atualizado -- para a guarda liberar um `tmp_path` e o `open` cair no
    # home real. Mesma razao para o `mkdir` abaixo sair de `_JSONL_PATH`.
    destino = _JSONL_PATH
    if real_sidecar_blocked(destino.parent):
        # Sanitizacao e validacao ja rodaram: o que se suprime aqui e o
        # byte no disco do operador, nao a checagem que faz o teste valer.
        return
    inicio = time.monotonic()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Sidecar indisponivel nao pode derrubar o dispatch nem poluir o app.
        pass
    if time.monotonic() - inicio > _SLOW_WRITE_SECONDS:
        _writer_disabled = True
        logger.warning(
            "[brainstorm-telemetry] escrita levou mais de %.0fms; sidecar "
            "desligado ate o proximo processo",
            _SLOW_WRITE_SECONDS * 1000,
        )


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Filtra pela allowlist e passa todo valor string por `scrub()`."""
    limpo: dict[str, Any] = {}
    for chave, valor in payload.items():
        if chave not in FIELD_ALLOWLIST:
            _violation(
                f"campo fora da allowlist descartado: {chave!r} "
                f"(permitidos: {sorted(FIELD_ALLOWLIST)})"
            )
            continue
        if isinstance(valor, str):
            limpo[chave] = scrub(valor)
        elif isinstance(valor, (int, float, bool)) or valor is None:
            limpo[chave] = valor
        else:
            # Tipo composto nao tem campo na allowlist; aceitar aqui abriria a
            # porta para dict/list carregando o que a allowlist barrou.
            _violation(
                f"valor de tipo nao escalar descartado em {chave!r}: "
                f"{type(valor).__name__}"
            )
    return limpo


def _emit_record(event: str, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _seq
    if event not in EVENTS:
        _violation(f"event fora do conjunto fechado: {event!r}")
        return {}
    permitidos = _REASONS_BY_EVENT[event]
    if reason not in permitidos:
        _violation(
            f"reason {reason!r} nao pertence ao evento {event!r} "
            f"(permitidos: {sorted(permitidos)})"
        )
        return {}
    with _lock:
        _seq += 1
        seq = _seq
    record = {
        "schema": SCHEMA_VERSION,
        "ts": time.time(),
        "monotonic": time.monotonic(),
        "pid": os.getpid(),
        "seq": seq,
        "dispatch_id": f"{os.getpid()}-{seq}",
        "event": event,
        "reason": reason,
        **_sanitize(payload),
    }
    _write_jsonl(record)
    return record


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


def record_click_blocked(
    *,
    reason: str,
    button_id: str = "",
    testid_slug: str = "",
    action: str = "",
    requested_provider: str = "",
    source_kind: str = "unknown",
) -> dict[str, Any]:
    """Clique que terminou em `_on_clicked` ANTES do `emit`.

    Nao ha `resolved_provider` aqui de proposito: a resolucao qwen/grok ->
    Claude acontece no handler, que este caminho nunca alcanca. Gravar o
    requisitado como se fosse resolvido inventaria uma resolucao.
    """
    try:
        return _emit_record(EVENT_CLICK_BLOCKED, reason, {
            "button_id": button_id,
            "testid_slug": testid_slug,
            "action": action,
            "requested_provider": requested_provider,
            "source_kind": source_kind,
            "ok": False,
        })
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - telemetria nunca derruba o clique
        logger.debug("[brainstorm-telemetry] record_click_blocked falhou", exc_info=True)
        return {}


def record_dispatch(
    *,
    reason: str,
    button_id: str = "",
    testid_slug: str = "",
    action: str = "",
    requested_provider: str = "",
    resolved_provider: str = "",
    source_kind: str = "unknown",
    artifact: str = "",
    terminal: int | None = None,
    prompt_chars: int | None = None,
) -> dict[str, Any]:
    """Um ponto de termino do handler `_on_mcp_prompt_requested`.

    Exatamente uma chamada por caminho de termino, incluindo o sucesso. O
    `finally` do handler NAO emite: ele so reabre a janela de debounce e um
    evento ali duplicaria todos os outros.

    `requested_provider` e o `button_type` CRU que chegou no payload (inclusive
    o literal `type-selector-radio-input`); `resolved_provider` e o valor
    calculado no handler. So o par mede a degradacao: so o resolvido apaga o
    pedido, so o pedido esconde a queda.
    """
    try:
        return _emit_record(EVENT_DISPATCH, reason, {
            "button_id": button_id,
            "testid_slug": testid_slug,
            "action": action,
            "requested_provider": requested_provider,
            "resolved_provider": resolved_provider,
            "source_kind": source_kind,
            "artifact_id": artifact,
            "terminal": terminal,
            "prompt_chars": prompt_chars,
            "ok": reason == "ok",
        })
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - telemetria nunca derruba o dispatch
        logger.debug("[brainstorm-telemetry] record_dispatch falhou", exc_info=True)
        return {}


def jsonl_path() -> Path:
    """Path do sidecar desta instancia (usado em diagnostico e testes)."""
    return _JSONL_PATH


def _reset_for_tests(*, log_dir: Path | None = None, strict: bool = True) -> None:
    """Zera o contador, redireciona o sidecar e liga o modo estrito.

    Uso exclusivo de teste. `strict=True` por default porque violacao de
    allowlist silenciosa e o unico jeito de o gate de C4 passar sem valer.
    """
    global _seq, _strict, _LOG_DIR, _JSONL_PATH, _writer_disabled
    with _lock:
        _seq = 0
    _strict = strict
    # Sem isto, um teste que exercite o disjuntor de escrita lenta deixaria
    # o sidecar desligado para todos os testes seguintes do processo.
    _writer_disabled = False
    if log_dir is not None:
        _LOG_DIR = Path(log_dir)
        _JSONL_PATH = _LOG_DIR / f"brainstorm-telemetry-{os.getpid()}.jsonl"


__all__ = [
    "SCHEMA_VERSION",
    "GUARD_ENV",
    "FIELD_ALLOWLIST",
    "EVENTS",
    "EVENT_CLICK_BLOCKED",
    "EVENT_DISPATCH",
    "HANDLER_REASONS",
    "WIDGET_REASONS",
    "scrub",
    "artifact_id",
    "source_kind_for",
    "record_click_blocked",
    "record_dispatch",
    "real_sidecar_blocked",
    "jsonl_path",
]
