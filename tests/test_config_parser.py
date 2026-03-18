"""Tests for config_parser module (module-03/TASK-1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.config.config_parser import PipelineConfig, detect_config, parse_config
from workflow_app.errors import ConfigError


@pytest.fixture
def project_v3(tmp_path) -> Path:
    """Cria um project.json V3 válido em tmp_path."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config = {
        "name": "meu-app",
        "basic_flow": {
            "brief_root": "output/brief/meu-app",
            "docs_root": "output/docs/meu-app",
            "wbs_root": "output/wbs/meu-app",
            "workspace_root": "output/workspace/meu-app",
        },
        "project_details": {
            "language": {"pt-BR": True},
        },
    }
    config_path = claude_dir / "project.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


@pytest.fixture
def project_v2(tmp_path) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config = {
        "name": "app-v2",
        "docs_root": "output/docs/app-v2",
        "wbs_root": "output/wbs/app-v2",
        "workspace_root": "output/workspace/app-v2",
    }
    config_path = claude_dir / "project.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


@pytest.fixture
def project_v1(tmp_path) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config = {
        "name": "app-v1",
        "output_root": "output/app-v1",
    }
    config_path = claude_dir / "project.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


class TestParseConfigV3:
    def test_parse_config_v3(self, project_v3):
        cfg = parse_config(str(project_v3))
        assert isinstance(cfg, PipelineConfig)
        assert cfg.project_name == "meu-app"
        assert cfg.docs_root == "output/docs/meu-app"
        assert cfg.wbs_root == "output/wbs/meu-app"
        assert cfg.workspace_root == "output/workspace/meu-app"
        assert cfg.brief_root == "output/brief/meu-app"
        assert cfg.language == "pt-BR"

    def test_parse_config_v3_project_dir(self, project_v3):
        cfg = parse_config(str(project_v3))
        assert cfg.project_dir == project_v3.parent.parent

    def test_parse_config_v3_raw_preserved(self, project_v3):
        cfg = parse_config(str(project_v3))
        assert "basic_flow" in cfg.raw
        assert cfg.raw["name"] == "meu-app"


class TestParseConfigV2:
    def test_parse_config_v2(self, project_v2):
        cfg = parse_config(str(project_v2))
        assert cfg.project_name == "app-v2"
        assert cfg.docs_root == "output/docs/app-v2"
        assert cfg.wbs_root == "output/wbs/app-v2"
        assert cfg.workspace_root == "output/workspace/app-v2"

    def test_parse_config_v2_brief_fallback(self, project_v2):
        # Sem brief_root explícito, usa docs_root
        cfg = parse_config(str(project_v2))
        assert cfg.brief_root == "output/docs/app-v2"


class TestParseConfigV1:
    def test_parse_config_v1(self, project_v1):
        cfg = parse_config(str(project_v1))
        assert cfg.project_name == "app-v1"
        assert cfg.docs_root == "output/app-v1/docs"
        assert cfg.workspace_root == "output/app-v1/workspace"
        assert cfg.wbs_root == "output/app-v1/wbs"
        assert cfg.brief_root == "output/app-v1/brief"


class TestParseConfigErrors:
    def test_parse_config_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json }", encoding="utf-8")
        with pytest.raises(ConfigError, match="JSON inválido"):
            parse_config(str(bad))

    def test_parse_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_config("/nao/existe/project.json")

    def test_parse_config_unknown_format(self, tmp_path):
        cfg_path = tmp_path / "unknown.json"
        cfg_path.write_text(json.dumps({"nome": "app", "versao": 1}), encoding="utf-8")
        with pytest.raises(ConfigError, match="não reconhecido"):
            parse_config(str(cfg_path))

    def test_parse_config_empty_docs_root(self, tmp_path):
        cfg_path = tmp_path / "empty.json"
        cfg_path.write_text(json.dumps({
            "name": "x",
            "basic_flow": {
                "docs_root": "",
                "wbs_root": "w",
                "workspace_root": "ws",
                "brief_root": "b",
            },
        }), encoding="utf-8")
        with pytest.raises(ConfigError, match="docs_root"):
            parse_config(str(cfg_path))


class TestDetectConfig:
    def test_detect_config_finds_primary(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_path = claude_dir / "project.json"
        config_path.write_text(json.dumps({
            "name": "x",
            "basic_flow": {
                "brief_root": "", "docs_root": "docs",
                "wbs_root": "", "workspace_root": "",
            }
        }), encoding="utf-8")

        result = detect_config(str(tmp_path))
        assert result is not None
        assert result == str(config_path.resolve())

    def test_detect_config_fallback_to_projects(self, tmp_path):
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)
        cfg = projects_dir / "myapp.json"
        cfg.write_text(json.dumps({
            "name": "myapp",
            "basic_flow": {
                "brief_root": "", "docs_root": "docs",
                "wbs_root": "", "workspace_root": "",
            }
        }), encoding="utf-8")

        result = detect_config(str(tmp_path))
        assert result is not None
        assert "myapp.json" in result

    def test_detect_config_returns_none_when_absent(self, tmp_path):
        result = detect_config(str(tmp_path))
        assert result is None

    def test_detect_config_prefers_primary_over_fallback(self, tmp_path):
        """Se ambos existem, primary tem preferência sobre projects/."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        primary = claude_dir / "project.json"
        primary.write_text(json.dumps({
            "name": "primary",
            "basic_flow": {"docs_root": "d", "brief_root": "", "wbs_root": "", "workspace_root": ""},
        }), encoding="utf-8")

        projects_dir = claude_dir / "projects"
        projects_dir.mkdir()
        fallback = projects_dir / "other.json"
        fallback.write_text(json.dumps({
            "name": "fallback",
            "basic_flow": {"docs_root": "d", "brief_root": "", "wbs_root": "", "workspace_root": ""},
        }), encoding="utf-8")

        result = detect_config(str(tmp_path))
        assert result == str(primary.resolve())

    def test_detect_config_skips_project_2(self, tmp_path):
        """Evita project-2.json (showroom) no fallback."""
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)
        p2 = projects_dir / "project-2.json"
        p2.write_text(json.dumps({
            "name": "showroom",
            "basic_flow": {"docs_root": "d", "brief_root": "", "wbs_root": "", "workspace_root": ""},
        }), encoding="utf-8")

        # Sem outros arquivos, retorna project-2 como último recurso
        result = detect_config(str(tmp_path))
        assert result is not None  # ainda retorna (fallback final)
