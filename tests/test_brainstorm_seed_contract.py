import subprocess
import sys
from pathlib import Path

import pytest

from workflow_app import brainstorm_seed_contract as contract


REPO_ROOT = Path(__file__).parents[3].resolve()


def test_module_imports_without_pyside6():
    """O modulo deve ser puro: importa-lo isoladamente nao traz PySide6."""
    code = (
        "import sys; "
        "import workflow_app.brainstorm_seed_contract; "
        "print('PySide6' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_canonical_seed_count_is_24():
    assert contract.CANONICAL_SEED_COUNT == 24
    assert contract.CANONICAL_SEED_COUNT == len(contract.CANONICAL_SEED_FILENAMES)


def test_every_seed_filename_exists_on_disk():
    seed_dir = contract.resolve_seed_dir(REPO_ROOT)
    missing = [
        name
        for name in contract.CANONICAL_SEED_FILENAMES
        if not (seed_dir / name).is_file()
    ]
    assert not missing, f"seeds ausentes em {seed_dir}: {missing}"


def test_resolve_seed_dir_returns_absolute_directory():
    seed_dir = contract.resolve_seed_dir(REPO_ROOT)
    assert seed_dir.is_absolute()
    assert seed_dir == (REPO_ROOT / contract.BRAINSTORM_SEEDS_RELDIR)
    assert seed_dir.name == "seeds"
    assert seed_dir.parent.name == "brainstorm-mcp"


def test_supplemental_rel_dir_is_declared():
    assert contract.SUPPLEMENTAL_SEEDS_RELDIR
    assert isinstance(contract.SUPPLEMENTAL_SEEDS_RELDIR, str)


def test_canonical_seed_filenames_are_sorted_and_unique():
    assert contract.CANONICAL_SEED_FILENAMES == tuple(
        sorted(contract.CANONICAL_SEED_FILENAMES)
    )
    assert len(set(contract.CANONICAL_SEED_FILENAMES)) == len(
        contract.CANONICAL_SEED_FILENAMES
    )
