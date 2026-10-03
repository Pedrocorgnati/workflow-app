"""Fixtures de tela do MiMo Code CLI e frases-gatilho fora dos docs da lane MiMo.

Duas travas:

1. `tests/fixtures/mimo_screens/` guarda uma captura real da tela RENDERIZADA
   do TUI por estado (spike `mimo-cli-pty`, CLI v0.1.15). Cada fixture existe,
   nao e vazia, tem a geometria medida, contem a agulha do seu estado e nao
   carrega segredo nem o id da sessao de gravacao. O README da pasta documenta
   origem, agulhas e a regra de regravar ao trocar de versao do CLI.
2. Docs, executores e launcher da lane MiMo nao reproduzem frase-gatilho de
   falha fatal. Um painel que hospeda a MiMo exibe o corpo do executor a cada
   envio, e uma frase literal viraria falso vermelho. A fonte da verdade dos
   padroes e `output_panel._CLI_SCOPED_FATAL_PATTERNS`; os padroes "hard" de
   `_FATAL_PATTERNS` entram tambem porque disparam em qualquer painel.
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

import pytest

from workflow_app.output_panel.output_panel import (
    _CLI_SCOPED_FATAL_PATTERNS,
    _FATAL_PATTERNS,
)

_TEST_FILE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _TEST_FILE.parents[3]
_FIXTURES_DIR = _TEST_FILE.parent / "fixtures" / "mimo_screens"
_README = _FIXTURES_DIR / "README.md"

# estado -> (linhas, colunas) do PTY em que a captura foi feita.
_GEOMETRY: dict[str, tuple[int, int]] = {
    "ready": (50, 200),
    "busy": (50, 200),
    "modal": (50, 200),
    "dialog": (50, 200),
    "nomatch": (40, 100),
    "fatal": (40, 100),
    "bypass": (50, 200),
}

_READY_INPUT = "Type your message"
_READY_FOOTER = "/ commands"
_BUSY_FOOTER = "esc interrupt"

# Agulhas dos estados que BLOQUEIAM o envio (todas obrigatorias no estado).
_BLOCKING_NEEDLES: dict[str, tuple[str, ...]] = {
    "modal": ("Select agent",),
    "dialog": ("↑↓ select  enter submit  esc dismiss", "→ Asked 1 question"),
    "nomatch": ("No matching items",),
    "fatal": ("A fatal error occurred!",),
    "bypass": ("Bypass Permissions",),
}

# Telas bloqueantes que TAMBEM exibem o rodape de pronto: o classificador
# precisa testar as agulhas bloqueantes antes do rodape.
_BLOCKING_WITH_READY_FOOTER = ("modal", "nomatch")

_SECRET_PATTERNS = (
    re.compile(r"tp-[a-z0-9]{40,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:XIAOMI|MIMO)_API_KEY\s*[=:]\s*\S"),
)
# Fragmentos de UUID: o caminho do scratchpad quebra de linha na barra lateral
# do TUI, entao o id de sessao pode aparecer partido. So zeros sao aceitos.
_UUID_FRAGMENT_PATTERNS = (
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"),
    re.compile(r"[0-9a-f]{4}-[0-9a-f]{12}"),
)

_ROW_RE = re.compile(r"^(\d{2})\|(.*)$")

# Arquivos da lane MiMo que um TUI hospedado pode exibir (ou que documentam a
# lane ao lado deles). Fora daqui: as fixtures de tela (capturas reais) e o
# `llm-routing-div.md` (documento compartilhado com outras rodadas).
_MIMO_LANE_TEXT_FILES = (
    _REPO_ROOT / ".mimocode" / "commands" / "slash-executor.md",
    _REPO_ROOT / "ai-forge" / "rules" / "mimo-code-cli-contract.md",
    _README,
    _REPO_ROOT / "ai-forge" / "scripts" / "mimod.sh",
    _REPO_ROOT / "ai-forge" / "scripts" / "mimod.test.sh",
    _REPO_ROOT / "ai-forge" / "MCP" / "agents" / "executor-de-slash-commands-rules.md",
    _REPO_ROOT / ".agents" / "skills" / "slash-executor.md",
    _REPO_ROOT / ".grok" / "commands" / "slash-executor.md",
    _REPO_ROOT / ".qwen" / "skills" / "slash-executor" / "SKILL.md",
    _TEST_FILE,
)


def _fixture(state: str) -> pathlib.Path:
    return _FIXTURES_DIR / f"{state}.txt"


def _read(state: str) -> str:
    return _fixture(state).read_text(encoding="utf-8")


def _cells(text: str) -> int:
    """Largura em celulas de terminal (caractere largo ocupa duas)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _rel(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


# ── Fixtures de tela ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", sorted(_GEOMETRY))
def test_fixture_exists_and_is_not_empty(state: str) -> None:
    path = _fixture(state)
    assert path.is_file(), f"Fixture ausente: {_rel(path)}"
    assert path.read_text(encoding="utf-8").strip(), f"Fixture vazia: {_rel(path)}"


@pytest.mark.parametrize("state", sorted(_GEOMETRY))
def test_fixture_keeps_header_and_measured_geometry(state: str) -> None:
    """Cabecalho `# t=... cursor=... modes=...` e uma linha `NN|` por linha da tela."""
    rows, cols = _GEOMETRY[state]
    lines = _read(state).splitlines()
    header = lines[0]
    assert header.startswith("# t="), f"{state}: cabecalho inesperado: {header!r}"
    assert " cursor=" in header and " modes={" in header, f"{state}: cabecalho incompleto"
    body = lines[1:]
    assert len(body) == rows, f"{state}: {len(body)} linhas de tela, esperado {rows}"
    for index, line in enumerate(body):
        match = _ROW_RE.match(line)
        assert match, f"{state}: linha {index} fora do formato NN|texto"
        assert int(match.group(1)) == index, f"{state}: numeracao quebrada na linha {index}"
        width = _cells(match.group(2))
        assert width <= cols, f"{state}: linha {index} com {width} celulas, PTY de {cols}"


def test_ready_fixture_shows_ready_marker() -> None:
    """Pronto: `Type your message` ou o rodape `/ commands` sem `esc interrupt`."""
    text = _read("ready")
    assert _BUSY_FOOTER not in text
    assert _READY_INPUT in text or _READY_FOOTER in text
    for state, needles in _BLOCKING_NEEDLES.items():
        for needle in needles:
            assert needle not in text, f"ready.txt contem agulha de {state}: {needle!r}"


def test_busy_fixture_shows_busy_footer() -> None:
    text = _read("busy")
    assert _BUSY_FOOTER in text
    assert _READY_FOOTER not in text
    assert _READY_INPUT not in text


@pytest.mark.parametrize("state", sorted(_BLOCKING_NEEDLES))
def test_blocking_fixture_shows_its_needles(state: str) -> None:
    text = _read(state)
    missing = [needle for needle in _BLOCKING_NEEDLES[state] if needle not in text]
    assert not missing, f"{state}.txt sem a agulha medida: {missing}"


@pytest.mark.parametrize("state", sorted(_BLOCKING_NEEDLES))
def test_blocking_needles_are_exclusive_to_their_fixture(state: str) -> None:
    """Cada fixture e um exemplo puro: agulha bloqueante nao vaza para outra tela."""
    leaks = [
        (other, needle)
        for other in sorted(_GEOMETRY)
        if other != state
        for needle in _BLOCKING_NEEDLES[state]
        if needle in _read(other)
    ]
    assert not leaks, f"Agulha de {state} presente em outra fixture: {leaks}"


@pytest.mark.parametrize("state", _BLOCKING_WITH_READY_FOOTER)
def test_blocking_screens_also_show_ready_footer(state: str) -> None:
    """Mantem o caso adversarial documentado no README (precedencia no classificador)."""
    text = _read(state)
    assert _READY_FOOTER in text and _BUSY_FOOTER not in text


@pytest.mark.parametrize("state", sorted(_GEOMETRY))
def test_fixture_has_no_secret_nor_session_id(state: str) -> None:
    text = _read(state)
    hits = [pattern.pattern for pattern in _SECRET_PATTERNS if pattern.search(text)]
    assert not hits, f"{state}.txt casa padrao de segredo: {hits}"
    for pattern in _UUID_FRAGMENT_PATTERNS:
        for fragment in pattern.findall(text):
            assert set(fragment) <= {"0", "-"}, f"{state}.txt com id de sessao nao zerado"


def test_readme_documents_every_fixture_and_needle() -> None:
    text = _README.read_text(encoding="utf-8")
    for state in _GEOMETRY:
        assert f"`{state}.txt`" in text, f"README sem a fixture {state}.txt"
    needles = [_READY_INPUT, _READY_FOOTER, _BUSY_FOOTER]
    needles += [needle for group in _BLOCKING_NEEDLES.values() for needle in group]
    missing = [needle for needle in needles if needle not in text]
    assert not missing, f"README sem as agulhas: {missing}"
    assert "v0.1.15" in text, "README sem a versao do CLI das capturas"
    assert "Regravar as fixtures ao trocar de versao do CLI" in text


# ── Frases-gatilho fora dos docs da lane MiMo ───────────────────────────────


def _trigger_patterns() -> list[tuple[str, re.Pattern[str]]]:
    scoped = [(f"{cli}:{reason}", pattern) for cli, reason, pattern in _CLI_SCOPED_FATAL_PATTERNS]
    hard = [
        (f"*:{reason}", pattern)
        for reason, pattern, severity in _FATAL_PATTERNS
        if severity == "hard"
    ]
    return scoped + hard


def test_trigger_pattern_tables_are_populated() -> None:
    """Sem padroes da MiMo o teste abaixo passaria no vazio."""
    clis = {cli for cli, _reason, _pattern in _CLI_SCOPED_FATAL_PATTERNS}
    assert "mimo" in clis
    assert any(severity == "hard" for _reason, _pattern, severity in _FATAL_PATTERNS)


@pytest.mark.parametrize("path", _MIMO_LANE_TEXT_FILES, ids=_rel)
def test_mimo_lane_file_has_no_fatal_trigger_phrase(path: pathlib.Path) -> None:
    assert path.is_file(), f"Arquivo ausente: {_rel(path)}"
    text = path.read_text(encoding="utf-8")
    hits = [
        f"{label} -> {match.group(0)!r}"
        for label, pattern in _trigger_patterns()
        for match in [pattern.search(text)]
        if match
    ]
    assert not hits, (
        f"{_rel(path)} reproduz frase-gatilho de falha fatal (fatiar a frase; "
        f"fonte da verdade: output_panel._CLI_SCOPED_FATAL_PATTERNS): {hits}"
    )
