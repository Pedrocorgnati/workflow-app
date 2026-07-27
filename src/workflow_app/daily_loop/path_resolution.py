"""Fonte unica da regra de resolucao de token `.md` do `_LOOP-CONFIG.json`.

Antes deste modulo a regra vivia em DUAS copias que nao se conversavam: o
algoritmo real em `loader._rewrite_bare_relative_md_tokens` e uma reescrita em
prosa no bloco W4b de `.claude/commands/loop/workflow-app.md`. A prosa
divergiu do codigo e passou a reprovar loops que o loader carrega sem
problema. Aqui a regra vira codigo importavel pelos dois lados: o loader
consome em tempo de carga da fila e o shim `ai-forge/scripts/loop-path-resolve.py`
consome na linha de comando (decisao D6, Opcao A).

Premissa corrigida (D1): o cwd de execucao dos comandos da fila e a **raiz do
repo**, nao o `basic_flow.workspace_root`. Por isso a base de maior precedencia
e a raiz do repo, e nao o workspace.

Restricoes deliberadas: stdlib apenas (`os`, `pathlib`, `dataclasses`), sem
importar o pacote de dominio do app, sem I/O alem de `Path.exists` /
`os.path.realpath`. Nada de rede, nada de escrita em disco.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Conjunto FECHADO de vereditos. Qualquer consumidor (loader, W4b, shim) mapeia
# a partir desta lista; veredito novo e mudanca de contrato, nao detalhe.
VERDICTS: tuple[str, ...] = ("ok", "rewrite", "not_found", "ambiguous", "absolute")

# Nomes canonicos das bases, na ordem de precedencia (D5).
BASE_REPO_ROOT = "repo_root"
BASE_WORKSPACE_ROOT = "workspace_root"
BASE_LOOP_ROOT = "loop_root"

BASE_PRECEDENCE: tuple[str, ...] = (BASE_REPO_ROOT, BASE_WORKSPACE_ROOT, BASE_LOOP_ROOT)


@dataclass(frozen=True)
class TokenResolution:
    """Veredito de um unico token `.md`.

    - `verdict`: elemento de `VERDICTS`.
    - `base`: nome da base vencedora (`None` para `absolute` e `not_found`).
    - `resolved_path`: caminho canonico do token na base vencedora (`None` para
      `not_found`; para `absolute` e o proprio token normalizado).
    - `rewrite_to`: token reescrito, preenchido SOMENTE no veredito `rewrite`.
    - `ambiguous_bases`: bases cujos `realpath` divergiram; vazio fora de
      `ambiguous`.
    """

    verdict: str
    base: str | None
    resolved_path: Path | None
    rewrite_to: str | None
    ambiguous_bases: tuple[str, ...] = ()


def canonical_path(path: Path, *, anchor: Path | None = None) -> Path:
    """Normaliza `path`, ancorando relativos em `anchor` quando fornecido.

    Movido de `loader._canonical_path` para ca; o loader passou a importar
    daqui. Mantem `resolve(strict=False)` de proposito: normalizar nao pode
    exigir existencia, a existencia e decidida depois, base a base.
    """
    expanded = path.expanduser()
    if anchor is not None and not expanded.is_absolute():
        expanded = anchor / expanded
    return expanded.resolve(strict=False)


def repo_root_anchor(loop_root: Path) -> Path | None:
    """Raiz do repo que hospeda `loop_root` (1o ancestral com `.claude/`).

    Base canonica para paths RELATIVOS declarados no `_LOOP-CONFIG.json`
    (`basic_flow.workspace_root: "output/workspace/app"`). Sem ela, `resolve()`
    ancorava no cwd do processo, e o workflow-app roda com cwd =
    `ai-forge/workflow-app` (Makefile), nunca a raiz do repo, enquanto o
    terminal que executa os comandos roda na raiz.

    Contrato tri-estado preservado: retorna `None` quando nenhum ancestral tem
    `.claude/` (loop fora de repo SystemForge); nesse caso o caller mantem o
    comportamento legado de duas bases.
    """
    for parent in (loop_root, *loop_root.parents):
        if (parent / ".claude").is_dir():
            return parent
    return None


def resolve_md_token(
    token: str,
    *,
    loop_root: Path,
    workspace_root: Path,
    repo_root: Path | None,
) -> TokenResolution:
    """Classifica um token `.md` contra as bases, na ordem de precedencia.

    Ordem (D5): raiz do repo, depois `workspace_root`, depois `loop_root`.
    Nenhuma das tres e dispensavel: no corpus de `blacksmith/loop-archives/`,
    419 tokens so resolvem por `workspace_root` e 2 so por `loop_root`.

    Vereditos:
      - `absolute`: token comeca com `/`. Decidido SEM tocar o disco (68
        ocorrencias no corpus); um path absoluto ja diz onde mora.
      - `ok`: primeira base que resolve e a raiz do repo ou o `workspace_root`.
        O token e usavel como esta.
      - `rewrite`: a UNICA base que resolve e o `loop_root`, isto e, o token
        e bare-relative ao loop (bug de producer). `rewrite_to` traz o token
        prefixado por `relpath(loop_root, workspace_root)`.
      - `not_found`: nenhuma base resolve.
      - `ambiguous`: mais de uma base resolve e os `realpath` DIVERGEM. Nao
        basta pertencer a mais de uma base: no corpus 3632 tokens estao em
        duas bases apontando para o mesmo arquivo real, e disparar ai
        transformaria o aviso em ruido puro.

    `repo_root=None` (loop fora de repo SystemForge) degrada para duas bases,
    sem excecao.
    """
    if token.startswith("/"):
        return TokenResolution(
            verdict="absolute",
            base=None,
            resolved_path=canonical_path(Path(token)),
            rewrite_to=None,
        )

    bases: list[tuple[str, Path]] = []
    if repo_root is not None:
        bases.append((BASE_REPO_ROOT, repo_root))
    bases.append((BASE_WORKSPACE_ROOT, workspace_root))
    bases.append((BASE_LOOP_ROOT, loop_root))

    hits: list[tuple[str, Path, str]] = []
    for name, base in bases:
        candidate = base / token
        if candidate.exists():
            hits.append((name, canonical_path(candidate), os.path.realpath(str(candidate))))

    if not hits:
        return TokenResolution(
            verdict="not_found", base=None, resolved_path=None, rewrite_to=None
        )

    winner_name, winner_path, _ = hits[0]

    if len({real for _, _, real in hits}) > 1:
        return TokenResolution(
            verdict="ambiguous",
            base=winner_name,
            resolved_path=winner_path,
            rewrite_to=None,
            ambiguous_bases=tuple(name for name, _, _ in hits),
        )

    if winner_name != BASE_LOOP_ROOT:
        return TokenResolution(
            verdict="ok", base=winner_name, resolved_path=winner_path, rewrite_to=None
        )

    try:
        rel_loop = os.path.relpath(loop_root, workspace_root)
    except ValueError:
        # Bases em volumes distintos (Windows): sem relpath possivel, o token
        # nao tem reescrita valida. Degrada para `ok` no loop_root em vez de
        # emitir um `rewrite_to` invalido.
        return TokenResolution(
            verdict="ok", base=BASE_LOOP_ROOT, resolved_path=winner_path, rewrite_to=None
        )

    return TokenResolution(
        verdict="rewrite",
        base=BASE_LOOP_ROOT,
        resolved_path=winner_path,
        rewrite_to=f"{rel_loop}/{token}",
    )
