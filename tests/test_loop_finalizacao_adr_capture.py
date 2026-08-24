"""Prova de renderizacao do sufixo `/loop:adr-capture` na fila do loop.

Task 28 do estudo `08-24-systemforge-analise-fluxo-loop`. O aceite exige que
`/loop:adr-capture` apareca RENDERIZADO na lista `data-testid="queue-command-list"`.

O botao `queue-btn-cmd-loop-adr-capture` (main_window `_EXTRA_CMDS`) NAO satisfaz
isso sozinho: ele cola o comando no terminal, nao enfileira. O caminho que de
fato renderiza na fila e o item `kind == "finalizacao"`, cujo array `commands`
o `/loop:integration` materializa e o loader converte em `CommandSpec`.

Estes testes travam o contrato dos tres estados declarados em
`.claude/commands/loop/integration.md` (self-check dos bookends) e em
`.claude/commands/loop/review.md` (`C5.bookend-lifecycle`):

  * sufixo AUSENTE  (len 6) -> valido, nenhum `/loop:adr-capture` na fila;
  * sufixo COMPLETO (len 8) -> valido, `/loop:adr-capture` renderizado na fila;
  * as configs anteriores a 2026-08-24 caem no primeiro caso e NAO viram drift.

Sufixo PARCIAL (len 7) e blocker de producer/validador, nao do loader — o loader
renderiza o que recebe. Isso fica registrado aqui para que a ausencia de
assercao sobre len 7 seja uma escolha declarada, nao um esquecimento.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workflow_app.daily_loop.loader import build_daily_loop_specs


PREFIXO_FINALIZACAO: list[str] = [
    "/loop:iteraction:execute-task --task tasks/task-003.md",
    "/clear",
    "/loop:iteraction:review-executed-task --task tasks/task-003.md",
    "/clear",
    "/loop:reconcile-check --name test-loop",
    "/loop:iteraction:review-executed-loop --name test-loop",
]

SUFIXO_ADR: list[str] = [
    "/clear",
    "/loop:adr-capture --name test-loop",
]


def _write_progress(loop_root: Path) -> None:
    (loop_root / "PROGRESS.md").write_text(
        "# Progress\n"
        "\n"
        "| ID  | Status | Target          | Bucket | Updated |\n"
        "|-----|--------|-----------------|--------|---------|\n"
        "| 003 | [ ]    | finalizacao     | B      | -       |\n",
        encoding="utf-8",
    )


def _config_com(commands: list[str]) -> dict[str, Any]:
    return {
        "daily_loop": {
            "slug": "test-loop",
            "buckets": [
                {
                    "id": "B",
                    "model": "opus",
                    "effort": "high",
                    "items": [
                        {
                            "id": "003",
                            "kind": "finalizacao",
                            "commands": commands,
                        }
                    ],
                }
            ],
        }
    }


def _rendered(specs: Any) -> list[str]:
    """Reconstroi o texto de cada CommandSpec renderizado na fila.

    `CommandSpec.name` carrega o slash-command; as flags vivem separadas em
    `flags_boolean` e `flags_with_value` (ver `workflow_app.domain`).
    """
    out: list[str] = []
    for spec in specs:
        partes: list[str] = [spec.name]
        partes.extend(getattr(spec, "flags_boolean", []) or [])
        for flag in getattr(spec, "flags_with_value", []) or []:
            nome = getattr(flag, "name", None) or getattr(flag, "flag", "")
            valor = getattr(flag, "value", "")
            partes.append(f"{nome} {valor}".strip())
        out.append(" ".join(str(p) for p in partes if p).strip())
    return out


def test_finalizacao_sem_sufixo_nao_renderiza_adr_capture(tmp_path: Path) -> None:
    """Config anterior a 2026-08-24: prefixo de 6, sem adr-capture. Nao e drift."""
    _write_progress(tmp_path)
    specs = build_daily_loop_specs(_config_com(list(PREFIXO_FINALIZACAO)), tmp_path)
    renderizados = _rendered(specs)

    assert renderizados, "loader nao renderizou nenhum CommandSpec para a finalizacao"
    assert not any("/loop:adr-capture" in c for c in renderizados), (
        "config sem sufixo nao pode fazer /loop:adr-capture aparecer na fila; "
        f"renderizados={renderizados!r}"
    )
    assert any("/loop:iteraction:review-executed-loop" in c for c in renderizados), (
        f"review global sumiu da fila; renderizados={renderizados!r}"
    )


def test_finalizacao_com_sufixo_renderiza_adr_capture_na_fila(tmp_path: Path) -> None:
    """Aceite da Task 28: com o sufixo, /loop:adr-capture chega renderizado na fila."""
    _write_progress(tmp_path)
    specs = build_daily_loop_specs(
        _config_com(PREFIXO_FINALIZACAO + SUFIXO_ADR), tmp_path
    )
    renderizados = _rendered(specs)

    assert any("/loop:adr-capture" in c for c in renderizados), (
        "/loop:adr-capture NAO foi renderizado na fila a partir do item de "
        f"finalizacao; renderizados={renderizados!r}"
    )


def test_adr_capture_vem_depois_do_review_global(tmp_path: Path) -> None:
    """O sufixo fica APOS o review global de proposito.

    `adr-capture` le o `## ADR Log` fechado; posiciona-lo antes quebraria a
    adjacencia `reconcile-check` -> review global exigida por C5.
    """
    _write_progress(tmp_path)
    specs = build_daily_loop_specs(
        _config_com(PREFIXO_FINALIZACAO + SUFIXO_ADR), tmp_path
    )
    renderizados = _rendered(specs)

    idx_review = next(
        (i for i, c in enumerate(renderizados) if "review-executed-loop" in c), None
    )
    idx_adr = next(
        (i for i, c in enumerate(renderizados) if "/loop:adr-capture" in c), None
    )
    assert idx_review is not None, f"review global ausente; {renderizados!r}"
    assert idx_adr is not None, f"adr-capture ausente; {renderizados!r}"
    assert idx_adr > idx_review, (
        "/loop:adr-capture precisa vir DEPOIS do review global "
        f"(review={idx_review}, adr={idx_adr}); renderizados={renderizados!r}"
    )
