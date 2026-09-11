"""Observacao de tokens/custo no caminho vivo do workflow-app (Task 33).

B3 do estudo 08-24: a cadeia PipelineManager -> ExtrasOrchestrator existe, mas
dois cortes a matam (orquestrador nunca injetado; tokens_in/out nunca passam).
Alem disso o caminho que o operador realmente usa (colar no terminal) nem
passa por PipelineManager.

Este modulo e a FONTE. Sem numero observado > 0, ninguem emite custo. Zero e
valor; ausencia e None. Inventar 0 a partir de silencio e o mesmo defeito que
a Regra L14.7 nomeia noutro contexto.

Fontes, nesta ordem:

1. texto do terminal (JSON de usage, pares input/output, totais rotulados);
2. JSONL do Claude Code em ``~/.claude/projects/<encoded-cwd>/``, somente
   eventos com timestamp >= inicio do despacho.

A leitura de JSONL real e recusada quando
``WF_BLOCK_REAL_USAGE_JSONL=1`` (armada no conftest) ou quando
``claude_projects_root`` e passado como diretorio de teste.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

JSONL_GUARD_ENV = "WF_BLOCK_REAL_USAGE_JSONL"


@dataclass(frozen=True)
class ObservedUsage:
    """Tokens observados. So existe quando pelo menos um lado e > 0."""

    tokens_in: int
    tokens_out: int
    source: str

    @property
    def usage_tokens(self) -> int:
        return int(self.tokens_in) + int(self.tokens_out)

    def is_observed(self) -> bool:
        return self.tokens_in > 0 or self.tokens_out > 0


_USAGE_OBJECT = re.compile(
    r'"usage"\s*:\s*\{([^}]{0,400})\}',
    re.IGNORECASE | re.DOTALL,
)
_INPUT = re.compile(r'"input_tokens"\s*:\s*(\d+)', re.IGNORECASE)
_OUTPUT = re.compile(r'"output_tokens"\s*:\s*(\d+)', re.IGNORECASE)
_PAIR_LABELED = re.compile(
    r"(?:input|prompt)[^\d]{0,12}(\d[\d.,]*)[^\d]{0,24}(?:output|completion)[^\d]{0,12}(\d[\d.,]*)",
    re.IGNORECASE,
)
_TOTAL_LABELED = re.compile(
    r"(?:tokens? used|token usage|total tokens?)\s*[:=]?\s*(\d[\d.,]*)\s*k?\b",
    re.IGNORECASE,
)


def _to_int(raw: str) -> int:
    texto = raw.replace(",", "").strip()
    if texto.endswith(("k", "K")) and texto[:-1]:
        try:
            return int(float(texto[:-1]) * 1000)
        except ValueError:
            return 0
    try:
        if "." in texto:
            return int(float(texto))
        return int(texto)
    except ValueError:
        return 0


def _from_usage_fields(
    tokens_in: int,
    tokens_out: int,
    source: str = "terminal",
) -> ObservedUsage | None:
    # Cache read/create NAO entram no input cobrado: a tabela so tem preco de
    # input/output Anthropic. Somar cache no mesmo tarifa inventaria custo.
    if tokens_in <= 0 and tokens_out <= 0:
        return None
    return ObservedUsage(tokens_in=tokens_in, tokens_out=tokens_out, source=source)


def parse_usage_from_text(text: str) -> ObservedUsage | None:
    """Extrai usage de um pedaco de terminal. None se nada observavel."""
    if not text:
        return None
    bloco = _USAGE_OBJECT.search(text)
    if bloco is not None:
        corpo = bloco.group(1)
        entrada = int(_INPUT.search(corpo).group(1)) if _INPUT.search(corpo) else 0
        saida = int(_OUTPUT.search(corpo).group(1)) if _OUTPUT.search(corpo) else 0
        visto = _from_usage_fields(entrada, saida, source="terminal")
        if visto is not None:
            return visto
    par = _PAIR_LABELED.search(text)
    if par is not None:
        visto = _from_usage_fields(_to_int(par.group(1)), _to_int(par.group(2)), source="terminal")
        if visto is not None:
            return visto
    # Total rotulado sozinho nao distingue in/out. Nao inventar a particao:
    # devolver o total em tokens_in e 0 em out so se o rotulo for inequivoco
    # e o numero > 0. O consumidor soma usage_tokens, entao o total chega.
    total = _TOTAL_LABELED.search(text)
    if total is not None:
        n = _to_int(total.group(1))
        if n > 0:
            return ObservedUsage(tokens_in=n, tokens_out=0, source="terminal-total")
    return None


def encode_claude_project_dirname(cwd: Path) -> str:
    """Espelha o encoding do Claude Code: ``/`` e nao-ASCII viram ``-``."""
    bruto = str(Path(cwd).resolve())
    return "".join("-" if (ch == "/" or ord(ch) > 127) else ch for ch in bruto)


def _parse_ts(valor: Any) -> float | None:
    if isinstance(valor, (int, float)):
        return float(valor)
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip()
    try:
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        return datetime.fromisoformat(texto).timestamp()
    except ValueError:
        return None


def parse_usage_from_claude_jsonl(
    *,
    cwd: Path,
    since_ts: float,
    claude_projects_root: Path | None = None,
) -> ObservedUsage | None:
    """Soma ``message.usage`` dos assistant events posteriores a ``since_ts``.

    Recusa o diretorio real quando o guard de teste esta armado e nenhum
    ``claude_projects_root`` de teste foi passado.
    """
    if claude_projects_root is None and os.environ.get(JSONL_GUARD_ENV) == "1":
        return None
    raiz = Path(claude_projects_root) if claude_projects_root is not None else (
        Path.home() / ".claude" / "projects"
    )
    pasta = raiz / encode_claude_project_dirname(cwd)
    if not pasta.is_dir():
        return None
    total_in = 0
    total_out = 0
    arquivos = sorted(pasta.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jsonl in arquivos[:8]:
        try:
            linhas = jsonl.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for linha in linhas:
            linha = linha.strip()
            if not linha or '"usage"' not in linha:
                continue
            try:
                obj = json.loads(linha)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(obj.get("timestamp") or obj.get("ts"))
            if ts is None or ts < since_ts:
                continue
            if obj.get("type") != "assistant":
                continue
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            total_in += int(usage.get("input_tokens") or 0)
            total_out += int(usage.get("output_tokens") or 0)
    return _from_usage_fields(total_in, total_out, source="claude_jsonl")


def observe_usage(
    *,
    terminal_text: str = "",
    provider: str | None = None,
    cwd: Path | None = None,
    since_ts: float | None = None,
    claude_projects_root: Path | None = None,
) -> ObservedUsage | None:
    """Fonte do caminho vivo: so o texto do proprio comando.

    JSONL do Claude NAO e fallback automatico: soma qualquer sessao do mesmo
    cwd apos ``since_ts`` e contamina custo entre loops concorrentes. O parser
    de JSONL permanece para uso explicito em teste/auditoria.
    """
    del provider, cwd, since_ts, claude_projects_root
    return parse_usage_from_text(terminal_text)
