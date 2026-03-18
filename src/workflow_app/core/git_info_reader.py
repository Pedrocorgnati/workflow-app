"""
GitInfoReader — Lê informações de commit e status do repositório git (module-15/TASK-3).

Usa subprocess com timeout. Todos os erros resultam em None (degradação
silenciosa) com logging de warning.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 5  # segundos máximos para esperar o git responder


@dataclass
class GitInfo:
    """Informações do repositório git no workspace."""

    branch: str
    commit_hash_short: str          # 7 caracteres
    commit_message_short: str       # máx 50 caracteres
    is_dirty: bool                  # True se há arquivos não commitados


class GitInfoReader:
    """Lê informações de commit e status do repositório git.

    Usa subprocess com timeout. Todos os erros resultam em None (degradação
    silenciosa) com logging de warning.
    """

    def get_info(self, workspace_root: str) -> GitInfo | None:
        """Lê informações do git no diretório especificado.

        Args:
            workspace_root: caminho absoluto para o diretório do repositório.

        Returns:
            GitInfo se o diretório for um repositório git válido, None caso contrário.
        """
        try:
            branch = self._get_branch(workspace_root)
            log_info = self._get_last_commit(workspace_root)
            is_dirty = self._check_dirty(workspace_root)

            if log_info is None:
                return None

            commit_hash, commit_msg = log_info
            return GitInfo(
                branch=branch or "HEAD",
                commit_hash_short=commit_hash[:7],
                commit_message_short=commit_msg[:50],
                is_dirty=is_dirty,
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "GitInfoReader: timeout ao executar git em '%s'", workspace_root
            )
            return None
        except FileNotFoundError:
            logger.warning("GitInfoReader: git não encontrado no PATH")
            return None
        except Exception as exc:
            logger.warning("GitInfoReader: erro inesperado — %s", exc)
            return None

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _run_git(self, workspace_root: str, args: list[str]) -> str | None:
        """Executa comando git e retorna stdout, ou None em caso de erro."""
        result = subprocess.run(
            ["git", "-C", workspace_root] + args,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _get_branch(self, workspace_root: str) -> str | None:
        """Retorna o nome do branch atual."""
        return self._run_git(
            workspace_root, ["rev-parse", "--abbrev-ref", "HEAD"]
        )

    def _get_last_commit(self, workspace_root: str) -> tuple[str, str] | None:
        """Retorna (hash_completo, mensagem) do último commit.

        Returns:
            Tupla (hash, subject) ou None se não há commits.
        """
        output = self._run_git(
            workspace_root, ["log", "-1", "--format=%H|%s"]
        )
        if not output or "|" not in output:
            return None

        parts = output.split("|", 1)
        return parts[0].strip(), parts[1].strip()

    def _check_dirty(self, workspace_root: str) -> bool:
        """Verifica se há arquivos modificados não commitados."""
        output = self._run_git(
            workspace_root, ["status", "--porcelain"]
        )
        # Se output é None (erro) ou vazio → não dirty
        return bool(output)

    # ------------------------------------------------------------------
    # Formatação para exibição
    # ------------------------------------------------------------------

    @staticmethod
    def format_for_display(info: GitInfo) -> str:
        """Formata GitInfo para exibição na MetricsBar.

        Returns:
            "abc1234 subject" ou "abc1234 subject *" se dirty.
        """
        dirty_marker = " *" if info.is_dirty else ""
        return f"{info.commit_hash_short} {info.commit_message_short}{dirty_marker}"

    @staticmethod
    def format_with_branch(info: GitInfo) -> str:
        """Formata com branch: "main · abc1234 subject"."""
        dirty_marker = " *" if info.is_dirty else ""
        return f"{info.branch} · {info.commit_hash_short} {info.commit_message_short}{dirty_marker}"
