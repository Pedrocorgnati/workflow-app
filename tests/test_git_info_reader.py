"""Tests for GitInfoReader (module-15/TASK-3)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from workflow_app.core.git_info_reader import GitInfo, GitInfoReader


@pytest.fixture()
def reader():
    return GitInfoReader()


def test_returns_none_when_not_git_repo(reader, tmp_path):
    """Diretório sem .git deve retornar None."""
    result = reader.get_info(str(tmp_path))
    # subprocess retorna erro (não é repositório) → None
    assert result is None


def test_returns_none_when_git_not_installed(reader, tmp_path):
    """FileNotFoundError deve ser capturado silenciosamente."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = reader.get_info(str(tmp_path))
    assert result is None


def test_returns_none_on_timeout(reader, tmp_path):
    """TimeoutExpired deve ser capturado silenciosamente."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
        result = reader.get_info(str(tmp_path))
    assert result is None


def test_returns_git_info_on_valid_repo(reader, tmp_path):
    """Simula repositório git válido com mocks de subprocess."""
    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "rev-parse" in cmd:
            result.stdout = "main\n"
        elif "log" in cmd:
            result.stdout = "abc1234567890|fix: update prompt message here\n"
        elif "status" in cmd:
            result.stdout = ""  # limpo
        return result

    with patch("subprocess.run", side_effect=mock_run):
        info = reader.get_info(str(tmp_path))

    assert info is not None
    assert info.branch == "main"
    assert len(info.commit_hash_short) == 7
    assert info.commit_message_short.startswith("fix:")
    assert info.is_dirty is False


def test_is_dirty_when_modified_files(reader, tmp_path):
    """is_dirty deve ser True quando há arquivos modificados."""
    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "rev-parse" in cmd:
            result.stdout = "main\n"
        elif "log" in cmd:
            result.stdout = "abc1234567890|fix: test\n"
        elif "status" in cmd:
            result.stdout = " M src/main.py\n"  # arquivo modificado
        return result

    with patch("subprocess.run", side_effect=mock_run):
        info = reader.get_info(str(tmp_path))

    assert info is not None
    assert info.is_dirty is True


def test_format_for_display(reader):
    info = GitInfo(
        branch="main",
        commit_hash_short="abc1234",
        commit_message_short="fix: update prompt",
        is_dirty=False,
    )
    assert GitInfoReader.format_for_display(info) == "abc1234 fix: update prompt"


def test_format_for_display_dirty(reader):
    info = GitInfo(
        branch="main",
        commit_hash_short="abc1234",
        commit_message_short="wip",
        is_dirty=True,
    )
    assert GitInfoReader.format_for_display(info) == "abc1234 wip *"


def test_message_truncated_to_50_chars(reader, tmp_path):
    long_msg = "a" * 100

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "rev-parse" in cmd:
            result.stdout = "main\n"
        elif "log" in cmd:
            result.stdout = f"abc1234567890|{long_msg}\n"
        elif "status" in cmd:
            result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=mock_run):
        info = reader.get_info(str(tmp_path))

    assert info is not None
    assert len(info.commit_message_short) <= 50


def test_format_with_branch():
    info = GitInfo(
        branch="main",
        commit_hash_short="abc1234",
        commit_message_short="feat: add feature",
        is_dirty=False,
    )
    assert GitInfoReader.format_with_branch(info) == "main · abc1234 feat: add feature"
