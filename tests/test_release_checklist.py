"""Verifica itens do release checklist automaticamente (module-16/TASK-4)."""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


def test_pyproject_has_required_fields():
    """pyproject.toml deve ter campos obrigatórios."""
    p = Path("pyproject.toml")
    assert p.exists(), "pyproject.toml não encontrado"
    with open(p, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["name"] == "workflow-app"
    assert "version" in data["project"]
    assert "requires-python" in data["project"]


def test_makefile_exists():
    """Makefile deve existir com targets run/test/lint."""
    makefile = Path("Makefile")
    assert makefile.exists(), "Makefile não encontrado"
    content = makefile.read_text()
    assert "run:" in content
    assert "test:" in content
    assert "lint:" in content


def test_gitignore_exists():
    """.gitignore deve existir com entradas essenciais."""
    gitignore = Path(".gitignore")
    assert gitignore.exists(), ".gitignore não encontrado"
    content = gitignore.read_text()
    assert "__pycache__" in content
    assert ("venv/" in content or ".venv" in content)
    assert "*.db" in content


def test_src_structure():
    """Estrutura de diretórios src/ deve estar completa."""
    required = [
        "src/workflow_app/__init__.py",
        "src/workflow_app/main.py",
        "src/workflow_app/domain.py",
        "src/workflow_app/signal_bus.py",
        "src/workflow_app/db/__init__.py",
        "src/workflow_app/db/models.py",
        "src/workflow_app/main_window.py",
    ]
    for path_str in required:
        p = Path(path_str)
        assert p.exists(), f"Required file missing: {path_str}"


def test_assets_icon_exists():
    """assets/icon.svg deve existir."""
    assert Path("assets/icon.svg").exists(), "assets/icon.svg não encontrado"


def test_tests_conftest_exists():
    """tests/conftest.py deve existir com fixtures."""
    conftest = Path("tests/conftest.py")
    assert conftest.exists(), "tests/conftest.py não encontrado"
    content = conftest.read_text()
    assert "qapp" in content
    assert "db_session" in content
