"""Contrato do resolver de token `.md` (`workflow_app.daily_loop.path_resolution`).

Cobre os oito casos de borda declarados em
`blacksmith/brainstorm-mcp/07-27-md-token-resolution-repo-root.md` (§13), que
sao exatamente os pontos onde a copia em prosa do bloco W4b divergiu do
algoritmo real do loader.

Todos os testes rodam offline, sobre `tmp_path`; nenhuma leitura do corpus
real e nenhuma escrita fora da sandbox do pytest.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from workflow_app.daily_loop.path_resolution import (
    BASE_LOOP_ROOT,
    BASE_REPO_ROOT,
    BASE_WORKSPACE_ROOT,
    VERDICTS,
    repo_root_anchor,
    resolve_md_token,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Repo SystemForge falso: raiz marcada por `.claude/`."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    return root


@pytest.fixture()
def loop_root(repo: Path) -> Path:
    root = repo / "blacksmith" / "loop-archives" / "07-27-fake-loop"
    root.mkdir(parents=True)
    return root


def _touch(path: Path, content: str = "# md\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestRepoRootAnchor:
    def test_finds_first_ancestor_with_claude_dir(self, repo: Path, loop_root: Path) -> None:
        assert repo_root_anchor(loop_root) == repo

    def test_returns_none_outside_systemforge_repo(self, tmp_path: Path) -> None:
        orphan = tmp_path / "orphan" / "loop"
        orphan.mkdir(parents=True)
        assert repo_root_anchor(orphan) is None


class TestVerdicts:
    """Casos de borda 1 a 8 da §13, um teste nomeado por caso."""

    # ── Caso 1: token absoluto ────────────────────────────────────────────
    def test_absolute_token_is_decided_without_touching_disk(
        self, repo: Path, loop_root: Path
    ) -> None:
        result = resolve_md_token(
            "/etc/nao-existe-em-lugar-nenhum.md",
            loop_root=loop_root,
            workspace_root=repo,
            repo_root=repo,
        )
        assert result.verdict == "absolute"
        assert result.base is None
        assert result.rewrite_to is None
        # Decidido pelo prefixo, nao pela existencia: o path nao existe e
        # ainda assim NAO virou `not_found`.
        assert result.resolved_path == Path("/etc/nao-existe-em-lugar-nenhum.md")

    # ── Caso 2: token que ja comeca com `rel_loop` ────────────────────────
    def test_token_already_prefixed_with_rel_loop_resolves_by_repo_root(
        self, repo: Path, loop_root: Path
    ) -> None:
        rel_loop = os.path.relpath(loop_root, repo)
        token = f"{rel_loop}/tasks/items/task-001.md"
        _touch(repo / token)

        result = resolve_md_token(
            token, loop_root=loop_root, workspace_root=repo, repo_root=repo
        )

        # Nao ha curto-circuito por prefixo: o token e classificado como
        # qualquer outro e resolve pela raiz do repo. O importante e o que ele
        # NAO e: nunca `rewrite` (isso duplicaria o prefixo).
        assert result.verdict == "ok"
        assert result.base == BASE_REPO_ROOT
        assert result.rewrite_to is None

    # ── Caso 3: token com `../` ───────────────────────────────────────────
    def test_token_with_parent_traversal_normalizes_and_resolves(
        self, repo: Path, loop_root: Path
    ) -> None:
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        target = _touch(repo / "output" / "workspace" / "shared" / "guide.md")

        result = resolve_md_token(
            "../shared/guide.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )

        assert result.verdict == "ok"
        assert result.base == BASE_WORKSPACE_ROOT
        assert result.resolved_path == target.resolve()
        assert ".." not in str(result.resolved_path)

    # ── Caso 4: token inexistente em toda base ────────────────────────────
    def test_token_missing_from_every_base_is_not_found(
        self, repo: Path, loop_root: Path
    ) -> None:
        result = resolve_md_token(
            "tasks/items/fantasma.md",
            loop_root=loop_root,
            workspace_root=repo,
            repo_root=repo,
        )
        assert result.verdict == "not_found"
        assert result.base is None
        assert result.resolved_path is None
        assert result.rewrite_to is None

    # ── Caso 5: duas bases, MESMO realpath ────────────────────────────────
    def test_same_realpath_in_two_bases_is_not_ambiguous(
        self, repo: Path, loop_root: Path
    ) -> None:
        """Regra que impede 3632 WARN de ruido no corpus real.

        Pertencer a mais de uma base e a situacao NORMAL: o `workspace_root`
        costuma ser subdiretorio da raiz do repo, ou um symlink para o mesmo
        arquivo. Ambiguidade e divergencia de `realpath`, nao multiplicidade.
        """
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        real = _touch(repo / "docs" / "guide.md")
        (workspace / "docs").mkdir()
        (workspace / "docs" / "guide.md").symlink_to(real)

        result = resolve_md_token(
            "docs/guide.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )

        assert result.verdict == "ok"
        assert result.base == BASE_REPO_ROOT
        assert result.ambiguous_bases == ()

    # ── Caso 6: duas bases, realpath DIVERGENTE ───────────────────────────
    def test_divergent_realpath_across_bases_is_ambiguous(
        self, repo: Path, loop_root: Path
    ) -> None:
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        _touch(repo / "docs" / "guide.md", "# raiz\n")
        _touch(workspace / "docs" / "guide.md", "# workspace\n")

        result = resolve_md_token(
            "docs/guide.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )

        assert result.verdict == "ambiguous"
        assert result.ambiguous_bases == (BASE_REPO_ROOT, BASE_WORKSPACE_ROOT)
        # Mesmo ambiguo, a precedencia continua legivel: quem ganharia e
        # exposto, para o consumidor poder seguir sem adivinhar.
        assert result.base == BASE_REPO_ROOT
        assert result.rewrite_to is None

    # ── Caso 7: `workspace_root` igual a raiz do repo ─────────────────────
    def test_workspace_root_equal_to_repo_root_collapses_without_ambiguity(
        self, repo: Path, loop_root: Path
    ) -> None:
        _touch(repo / "docs" / "guide.md")

        result = resolve_md_token(
            "docs/guide.md",
            loop_root=loop_root,
            workspace_root=repo,
            repo_root=repo,
        )

        # As duas primeiras bases sao o MESMO diretorio (32 loops do corpus).
        # Isso nao pode virar ambiguidade nem duplicar veredito.
        assert result.verdict == "ok"
        assert result.base == BASE_REPO_ROOT
        assert result.ambiguous_bases == ()

    # ── Caso 8: `loop_root` fora de repo com `.claude/` ───────────────────
    def test_repo_root_none_falls_back_to_two_bases(self, tmp_path: Path) -> None:
        orphan_loop = tmp_path / "orphan" / "loop"
        orphan_loop.mkdir(parents=True)
        workspace = tmp_path / "orphan" / "ws"
        workspace.mkdir()
        _touch(orphan_loop / "tasks" / "task-001.md")

        result = resolve_md_token(
            "tasks/task-001.md",
            loop_root=orphan_loop,
            workspace_root=workspace,
            repo_root=None,
        )

        # Sem excecao e sem exigir a base ausente: degrada para duas bases.
        assert result.verdict == "rewrite"
        assert result.base == BASE_LOOP_ROOT
        assert result.rewrite_to == (
            f"{os.path.relpath(orphan_loop, workspace)}/tasks/task-001.md"
        )

    def test_repo_root_none_and_token_missing_is_not_found(self, tmp_path: Path) -> None:
        orphan_loop = tmp_path / "orphan" / "loop"
        orphan_loop.mkdir(parents=True)

        result = resolve_md_token(
            "tasks/task-001.md",
            loop_root=orphan_loop,
            workspace_root=tmp_path / "orphan",
            repo_root=None,
        )
        assert result.verdict == "not_found"


class TestPrecedence:
    def test_repo_root_wins_over_workspace_and_loop(
        self, repo: Path, loop_root: Path
    ) -> None:
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        _touch(repo / "docs" / "guide.md", "# raiz\n")

        result = resolve_md_token(
            "docs/guide.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )
        assert (result.verdict, result.base) == ("ok", BASE_REPO_ROOT)

    def test_workspace_root_still_resolves_what_repo_root_misses(
        self, repo: Path, loop_root: Path
    ) -> None:
        """Base intermediaria nao e removivel: 419 tokens do corpus so batem aqui."""
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        _touch(workspace / "docs" / "so-no-workspace.md")

        result = resolve_md_token(
            "docs/so-no-workspace.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )
        assert (result.verdict, result.base) == ("ok", BASE_WORKSPACE_ROOT)

    def test_loop_root_only_token_is_rewritten_to_workspace_relative(
        self, repo: Path, loop_root: Path
    ) -> None:
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)
        _touch(loop_root / "tasks" / "items" / "task-019-finalizacao.md")

        result = resolve_md_token(
            "tasks/items/task-019-finalizacao.md",
            loop_root=loop_root,
            workspace_root=workspace,
            repo_root=repo,
        )

        assert result.verdict == "rewrite"
        assert result.base == BASE_LOOP_ROOT
        assert result.rewrite_to == (
            f"{os.path.relpath(loop_root, workspace)}/tasks/items/task-019-finalizacao.md"
        )

    def test_every_verdict_belongs_to_the_closed_set(
        self, repo: Path, loop_root: Path
    ) -> None:
        _touch(repo / "docs" / "guide.md")
        tokens = [
            "/absoluto.md",
            "docs/guide.md",
            "docs/inexistente.md",
        ]
        for token in tokens:
            result = resolve_md_token(
                token, loop_root=loop_root, workspace_root=repo, repo_root=repo
            )
            assert result.verdict in VERDICTS
