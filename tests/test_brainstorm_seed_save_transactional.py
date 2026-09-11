"""C2a.1 -- o save multi-seed da engrenagem e tudo-ou-nada observavel.

O laco anterior chamava `save_seed` 24 vezes em sequencia. Falha no K-esimo
arquivo deixava K-1 ja reescritos, sem `saved` emitido e com a grade servindo
o texto velho de arquivos que ja tinham mudado em disco -- exatamente o modo
de falha que fica caro depois que o CORPO do seed vira a fonte do prompt
despachado (C2c). Estes testes travam a compensacao.
"""

from pathlib import Path

import pytest

from workflow_app.widgets import brainstorm_mcp_config_dialog as gear
from workflow_app.widgets.brainstorm_mcp_config_dialog import (
    SeedError,
    save_seeds_transactional,
)


def _seed_text(label: str, prompt: str) -> str:
    return (
        "---\n"
        f"label: {label}\n"
        "button_type: Claude\n"
        "agent_name: ag\n"
        "agent_path: ai-forge/MCP/agents/x.md\n"
        "action: Analisar\n"
        "target_path: true\n"
        "target_terminal: terminal-interactive-output\n"
        "schema_version: 1\n"
        "---\n"
        "# Titulo\n"
        "\n"
        "## Prompt canonico\n"
        f"{prompt}\n"
        "\n"
    )


def _mk(tmp_path: Path, n: int) -> list[Path]:
    paths = []
    for i in range(n):
        p = tmp_path / f"{i:02d}-seed.md"
        p.write_text(_seed_text(f"L{i}", f"corpo original {i}"), encoding="utf-8")
        paths.append(p)
    return paths


def _items(paths, prompt_prefix="corpo NOVO"):
    return [
        (p, {"label": f"novo-{i}"}, f"{prompt_prefix} {i}")
        for i, p in enumerate(paths)
    ]


def test_happy_path_grava_todos(tmp_path):
    paths = _mk(tmp_path, 5)
    save_seeds_transactional(_items(paths))
    for i, p in enumerate(paths):
        t = p.read_text(encoding="utf-8")
        assert f"corpo NOVO {i}" in t
        assert f"label: novo-{i}" in t


def test_falha_no_k_esimo_write_restaura_os_k_menos_1(tmp_path, monkeypatch):
    """O ponto do cluster: falha no meio do commit nao deixa subconjunto."""
    paths = _mk(tmp_path, 6)
    originais = [p.read_text(encoding="utf-8") for p in paths]
    K = 4  # falha na 4a escrita (indices 0..2 ja gravados)

    real = gear._atomic_write
    chamadas = {"n": 0}

    def flaky(path: Path, out: str) -> None:
        chamadas["n"] += 1
        if chamadas["n"] == K:
            raise OSError("disco cheio (injetado)")
        real(path, out)

    monkeypatch.setattr(gear, "_atomic_write", flaky)

    with pytest.raises(OSError, match="injetado"):
        save_seeds_transactional(_items(paths))

    # As 3 primeiras foram gravadas E restauradas; as demais nunca tocadas.
    for p, original in zip(paths, originais):
        assert p.read_text(encoding="utf-8") == original, f"{p.name} ficou divergente"


def test_recusa_no_prepare_nao_escreve_nada(tmp_path):
    """Seed invalido no meio da lista aborta antes de qualquer escrita."""
    paths = _mk(tmp_path, 4)
    originais = [p.read_text(encoding="utf-8") for p in paths]
    # O 3o perde o bloco: recusa de prepare, nao de write.
    paths[2].write_text(
        _seed_text("L2", "x").replace("## Prompt canonico\n", "## Outra coisa\n"),
        encoding="utf-8",
    )
    originais[2] = paths[2].read_text(encoding="utf-8")

    with pytest.raises(SeedError, match="Prompt canonico"):
        save_seeds_transactional(_items(paths))

    for p, original in zip(paths, originais):
        assert p.read_text(encoding="utf-8") == original, f"{p.name} foi escrito"


def test_falha_na_restauracao_nomeia_os_divergentes(tmp_path, monkeypatch):
    """Se a compensacao tambem falha, o erro diz QUAIS arquivos ficaram sujos."""
    paths = _mk(tmp_path, 3)
    real = gear._atomic_write
    estado = {"n": 0, "modo": "commit"}

    def flaky(path: Path, out: str) -> None:
        estado["n"] += 1
        if estado["n"] == 3:          # falha o 3o commit
            estado["modo"] = "restore"
            raise OSError("disco cheio (injetado)")
        if estado["modo"] == "restore":
            raise OSError("restauracao tambem falhou (injetado)")
        real(path, out)

    monkeypatch.setattr(gear, "_atomic_write", flaky)

    with pytest.raises(SeedError) as exc:
        save_seeds_transactional(_items(paths))
    msg = str(exc.value)
    assert "divergentes" in msg
    assert "00-seed.md" in msg and "01-seed.md" in msg
    assert isinstance(exc.value.__cause__, OSError)


def test_lock_liberado_mesmo_apos_falha(tmp_path, monkeypatch):
    """Sem release, o proximo save morreria com 'seed em uso'."""
    paths = _mk(tmp_path, 3)
    real = gear._atomic_write
    n = {"i": 0}

    def flaky(path: Path, out: str) -> None:
        n["i"] += 1
        if n["i"] == 2:
            raise OSError("injetado")
        real(path, out)

    monkeypatch.setattr(gear, "_atomic_write", flaky)
    with pytest.raises(OSError):
        save_seeds_transactional(_items(paths))

    monkeypatch.undo()
    save_seeds_transactional(_items(paths, "segunda tentativa"))
    for i, p in enumerate(paths):
        assert f"segunda tentativa {i}" in p.read_text(encoding="utf-8")
