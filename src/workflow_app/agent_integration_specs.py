"""Fonte unica reconstruivel das integracoes opcionais de agentes.

Registry declarativo (literal em codigo) das integracoes suplementares que uma
persona MCP pode ganhar em DOIS destinos opcionais do workflow-app:

- setor MCP (`data-testid="output-toolbar-mcp"`): botao checkable adicional cujo
  `persona_prompt` entra na composicao de Main MCP / Parallel / Dual;
- grade Brainstorm (`data-testid="brainstorm-buttons-grid"`): `MCPPromptButton`
  suplementar renderizado DEPOIS dos 24 seeds canonicos.

Contratos (AGENT-TASK-006 do loop 07-24-criacao-agentes):

1. Fonte unica: `_build_mcp_column()`, `_build_brainstorm_page()` e
   `_rebuild_brainstorm_grid()` consomem estas mesmas specs. Listas paralelas em
   `main_window.py` sao proibidas.
2. Persistencia em codigo: as specs vivem neste modulo (editado por
   `/mcp:create-agent`), portanto sobrevivem a rebuild da grade e a restart do
   app sem depender de estado de widget.
3. Import sem efeito proprio: importar este modulo NAO le disco, NAO escreve
   nada e NAO muta estado global (inclusive os catalogos importados de
   `mcp_prompt_button` / `mcp_prompt_actions`, sempre copiados para frozenset).
   ATENCAO - o import NAO e Qt-free: os catalogos vivem em
   `workflow_app.widgets.mcp_prompt_button`, e qualquer import do pacote
   `workflow_app.widgets` carrega PySide6 e instancia o singleton QObject
   `signal_bus` (`workflow_app/signal_bus.py`). Um consumidor headless NAO pode
   importar este modulo assumindo ausencia de Qt. Desacoplar os catalogos para
   um modulo puro fora de `widgets/` e item estrutural proprio.
4. Leitura pura: as APIs de leitura validam e devolvem tuplas imutaveis; chamar
   duas vezes produz o mesmo resultado e nao altera nada.
5. Unicidade: slug unico por destino, `testid` unico globalmente e `action`
   obrigatoriamente ja existente em `VALID_ACTIONS` E em `ACTION_LITERALS` (uma
   spec NUNCA amplia catalogo de action).

A grade canonica de 24 seeds (`_load_brainstorm_seeds()`) permanece intocada:
uma spec suplementar nao vira 25o arquivo `NN-*.md`. Use
`assert_no_seed_slug_collision()` no caller para provar isso em runtime.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from workflow_app.create_agent_prompt import (
    CreateAgentPromptError,
)
from workflow_app.create_agent_prompt import (
    validate_description as _validate_free_text,
)
from workflow_app.create_agent_prompt import (
    validate_name as _validate_single_line_text,
)
from workflow_app.widgets.mcp_prompt_actions import ACTION_LITERALS
from workflow_app.widgets.mcp_prompt_button import (
    VALID_ACTIONS,
    VALID_BUTTON_TYPES,
    VALID_TERMINALS,
)

# ── Constantes de contrato ───────────────────────────────────────────────────

MCP_TESTID_PREFIX: Final[str] = "output-mcp-agent-"
BRAINSTORM_TESTID_PREFIX: Final[str] = "mcp-prompt-btn-"

DEFAULT_TARGET_TERMINAL: Final[str] = "terminal-interactive-output"
CODEX_TARGET_TERMINAL: Final[str] = "terminal-codex-output"

# slug_regex normativo de ai-forge/MCP/agents/FRONTMATTER-SCHEMA-v1.0.0.yaml.
SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MAX_CHARS: Final[int] = 64

# Copias defensivas: o modulo nunca muta os catalogos de origem.
VALID_BUTTON_TYPES_FROZEN: Final[frozenset[str]] = frozenset(VALID_BUTTON_TYPES)
VALID_TERMINALS_FROZEN: Final[frozenset[str]] = frozenset(VALID_TERMINALS)
# Action suplementar so e aceita quando o widget valida (VALID_ACTIONS) E o
# builder de prompt resolve o literal (ACTION_LITERALS). Interseccao explicita.
SUPPORTED_ACTIONS: Final[frozenset[str]] = frozenset(VALID_ACTIONS) & frozenset(
    ACTION_LITERALS.keys()
)

_MD_SUFFIX: Final[str] = ".md"


class AgentIntegrationSpecError(ValueError):
    """Falha de validacao de uma spec suplementar (campo ou unicidade).

    Mensagens sao genericas por design: nunca ecoam conteudo do operador nem
    valores potencialmente sensiveis para log, toast ou clipboard.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


# ── Validadores puros ────────────────────────────────────────────────────────


def _text_single_line(value: object, field_name: str) -> str:
    """Normaliza texto single-line reusando a higiene de create_agent_prompt."""
    if not isinstance(value, str):
        raise AgentIntegrationSpecError(
            f"{field_name} deve ser string", field=field_name
        )
    try:
        return _validate_single_line_text(value)
    except CreateAgentPromptError as exc:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: {exc.message}", field=field_name
        ) from exc


def _text_multi_line(value: object, field_name: str) -> str:
    """Normaliza texto multi-line (diretiva) reusando a mesma higiene."""
    if not isinstance(value, str):
        raise AgentIntegrationSpecError(
            f"{field_name} deve ser string", field=field_name
        )
    try:
        return _validate_free_text(value)
    except CreateAgentPromptError as exc:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: {exc.message}", field=field_name
        ) from exc


def validate_slug(value: object, *, field_name: str = "slug") -> str:
    """Valida o slug do agente (kebab-case, schema v1.0.0). Retorna normalizado."""
    slug = _text_single_line(value, field_name)
    if len(slug) > SLUG_MAX_CHARS:
        raise AgentIntegrationSpecError(
            f"{field_name} excede o limite de {SLUG_MAX_CHARS} caracteres",
            field=field_name,
        )
    if not SLUG_RE.match(slug):
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: esperado kebab-case [a-z0-9-]",
            field=field_name,
        )
    return slug


def validate_action(value: object, *, field_name: str = "action") -> str:
    """Valida a action contra a interseccao VALID_ACTIONS x ACTION_LITERALS.

    Action ausente, vazia ou fora da interseccao e recusada: uma spec
    suplementar nunca amplia o catalogo de actions.
    """
    action = _text_single_line(value, field_name)
    if action not in SUPPORTED_ACTIONS:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: esperado um de {sorted(SUPPORTED_ACTIONS)}",
            field=field_name,
        )
    return action


def validate_repo_relative_md(value: object, *, field_name: str) -> str:
    """Valida path .md relativo ao repo (sem escape, sem absoluto, sem TODO).

    Puramente lexical: NAO toca o filesystem (gate de existencia, G6, e
    responsabilidade do caller que ja conhece o repo root).
    """
    raw = _text_single_line(value, field_name)
    if "\\" in raw:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: use separador POSIX", field=field_name
        )
    if "TODO" in raw:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: placeholder TODO nao permitido",
            field=field_name,
        )
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: esperado path relativo ao repo",
            field=field_name,
        )
    if any(part == ".." for part in pure.parts):
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: path nao pode escapar do repo",
            field=field_name,
        )
    if pure.suffix != _MD_SUFFIX:
        raise AgentIntegrationSpecError(
            f"{field_name} invalido: esperado arquivo {_MD_SUFFIX}",
            field=field_name,
        )
    return str(pure)


def _validate_button_type(value: object) -> str:
    button_type = _text_single_line(value, "button_type")
    if button_type not in VALID_BUTTON_TYPES_FROZEN:
        raise AgentIntegrationSpecError(
            f"button_type invalido: esperado um de "
            f"{sorted(VALID_BUTTON_TYPES_FROZEN)}",
            field="button_type",
        )
    return button_type


def _validate_target_terminal(value: object) -> str | None:
    if value is None:
        return None
    terminal = _text_single_line(value, "target_terminal")
    if terminal not in VALID_TERMINALS_FROZEN:
        raise AgentIntegrationSpecError(
            f"target_terminal invalido: esperado um de "
            f"{sorted(VALID_TERMINALS_FROZEN)}",
            field="target_terminal",
        )
    return terminal


# ── Modelos tipados ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class McpAgentSpec:
    """Integracao suplementar no setor MCP (`output-toolbar-mcp`).

    Materializa um QPushButton checkable com testid `output-mcp-agent-{slug}`
    cujo `persona_prompt` entra na composicao das TRES acoes existentes
    (Main MCP, Parallel, Dual) somente quando marcado.
    """

    slug: str
    label: str
    directive: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "slug", validate_slug(self.slug))
        object.__setattr__(self, "label", _text_single_line(self.label, "label"))
        object.__setattr__(
            self, "directive", _text_multi_line(self.directive, "directive")
        )

    @property
    def testid(self) -> str:
        """Testid canonico do botao suplementar MCP."""
        return f"{MCP_TESTID_PREFIX}{self.slug}"

    @property
    def persona_prompt(self) -> str:
        """Diretiva composta quando o botao esta ativo.

        Nome espelha a property Qt `persona_prompt` ja lida por
        `_compose_mcp_text()` nos 16 checkboxes de persona existentes.
        """
        return self.directive


@dataclass(frozen=True)
class BrainstormAgentSpec:
    """Integracao suplementar na grade Brainstorm (`brainstorm-buttons-grid`).

    Renderizada como `MCPPromptButton` DEPOIS dos 24 seeds canonicos, com testid
    `mcp-prompt-btn-{slug}`. Nao participa do glob `NN-*.md` nem do loader
    canonico `_load_brainstorm_seeds()`.
    """

    slug: str
    label: str
    button_type: str
    action: str
    agent_name: str
    agent_path: str
    prompt_path: str
    target_terminal: str | None = None
    target_path_edit_inplace: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "slug", validate_slug(self.slug))
        object.__setattr__(self, "label", _text_single_line(self.label, "label"))
        object.__setattr__(
            self, "button_type", _validate_button_type(self.button_type)
        )
        object.__setattr__(self, "action", validate_action(self.action))
        object.__setattr__(
            self, "agent_name", _text_single_line(self.agent_name, "agent_name")
        )
        object.__setattr__(
            self,
            "agent_path",
            validate_repo_relative_md(self.agent_path, field_name="agent_path"),
        )
        object.__setattr__(
            self,
            "prompt_path",
            validate_repo_relative_md(self.prompt_path, field_name="prompt_path"),
        )
        object.__setattr__(
            self, "target_terminal", _validate_target_terminal(self.target_terminal)
        )
        object.__setattr__(
            self, "target_path_edit_inplace", bool(self.target_path_edit_inplace)
        )
        # Regra do widget: Codex so publica em terminal-codex-output. Declarar
        # outro terminal e erro de spec, nao correcao silenciosa.
        if (
            self.button_type == "Codex"
            and self.target_terminal is not None
            and self.target_terminal != CODEX_TARGET_TERMINAL
        ):
            raise AgentIntegrationSpecError(
                "button_type='Codex' exige target_terminal="
                f"'{CODEX_TARGET_TERMINAL}'",
                field="target_terminal",
            )

    @property
    def testid(self) -> str:
        """Testid canonico do botao suplementar Brainstorm."""
        return f"{BRAINSTORM_TESTID_PREFIX}{self.slug}"

    @property
    def resolved_target_terminal(self) -> str:
        """Terminal efetivo, aplicando a mesma regra do build seed-driven."""
        if self.button_type == "Codex":
            return CODEX_TARGET_TERMINAL
        return self.target_terminal or DEFAULT_TARGET_TERMINAL


# ── Registry literal (fonte unica; editado por /mcp:create-agent) ────────────
#
# Vazio ate um agente real pedir integracao opcional. Acrescentar entradas AQUI
# e a unica forma suportada de registrar um botao suplementar: qualquer lista
# paralela em main_window.py e duplicacao proibida.

_MCP_AGENT_SPECS: Final[tuple[McpAgentSpec, ...]] = ()

_BRAINSTORM_AGENT_SPECS: Final[tuple[BrainstormAgentSpec, ...]] = ()


# ── Validacao de unicidade (pura) ────────────────────────────────────────────


def _assert_unique(values: Iterable[str], *, kind: str, field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise AgentIntegrationSpecError(
                f"{kind} duplicado: {value}", field=field_name
            )
        seen.add(value)


def validate_registry(
    mcp_specs: Sequence[McpAgentSpec] | None = None,
    brainstorm_specs: Sequence[BrainstormAgentSpec] | None = None,
) -> None:
    """Valida unicidade cross-registry. Pura: so le e levanta.

    Regras:
    - slug unico DENTRO de cada destino (o mesmo agente pode aparecer nos dois,
      pois os testids tem prefixos distintos);
    - testid unico GLOBALMENTE (MCP + Brainstorm);
    - action de cada spec Brainstorm ja validada no modelo (interseccao dos dois
      catalogos), revalidada aqui para specs construidas fora do dataclass.
    """
    mcp = tuple(_MCP_AGENT_SPECS if mcp_specs is None else mcp_specs)
    brainstorm = tuple(
        _BRAINSTORM_AGENT_SPECS if brainstorm_specs is None else brainstorm_specs
    )

    for mcp_spec in mcp:
        if not isinstance(mcp_spec, McpAgentSpec):
            raise AgentIntegrationSpecError(
                "spec MCP invalida: esperado McpAgentSpec", field="mcp_specs"
            )
    for brainstorm_spec in brainstorm:
        if not isinstance(brainstorm_spec, BrainstormAgentSpec):
            raise AgentIntegrationSpecError(
                "spec Brainstorm invalida: esperado BrainstormAgentSpec",
                field="brainstorm_specs",
            )
        validate_action(brainstorm_spec.action)

    _assert_unique((s.slug for s in mcp), kind="slug MCP", field_name="slug")
    _assert_unique(
        (s.slug for s in brainstorm), kind="slug Brainstorm", field_name="slug"
    )
    _assert_unique(
        [s.testid for s in mcp] + [s.testid for s in brainstorm],
        kind="testid",
        field_name="testid",
    )


def assert_no_seed_slug_collision(
    seed_slugs: Iterable[str],
    brainstorm_specs: Sequence[BrainstormAgentSpec] | None = None,
) -> None:
    """Prova que nenhuma spec suplementar colide com os 24 seeds canonicos.

    Chamado pelo caller que ja carregou os seeds (`_load_brainstorm_seeds()`);
    este modulo nunca toca o filesystem.
    """
    canonical = {str(s).strip() for s in seed_slugs}
    specs = tuple(
        _BRAINSTORM_AGENT_SPECS if brainstorm_specs is None else brainstorm_specs
    )
    for spec in specs:
        if spec.slug in canonical:
            raise AgentIntegrationSpecError(
                f"slug suplementar colide com seed canonico: {spec.slug}",
                field="slug",
            )


def assert_no_testid_collision(
    existing_testids: Iterable[str],
    mcp_specs: Sequence[McpAgentSpec] | None = None,
    brainstorm_specs: Sequence[BrainstormAgentSpec] | None = None,
) -> None:
    """Prova que os testids suplementares nao colidem com testids ja montados."""
    existing = {str(t).strip() for t in existing_testids}
    for testid in registry_testids(mcp_specs, brainstorm_specs):
        if testid in existing:
            raise AgentIntegrationSpecError(
                f"testid duplicado: {testid}", field="testid"
            )


# ── APIs de leitura (puras, sem efeito colateral) ────────────────────────────


def supported_actions() -> tuple[str, ...]:
    """Actions aceitas por specs Brainstorm, ordenadas deterministicamente."""
    return tuple(sorted(SUPPORTED_ACTIONS))


def mcp_agent_specs() -> tuple[McpAgentSpec, ...]:
    """Specs MCP suplementares validadas, em ordem deterministica de registro."""
    validate_registry()
    return _MCP_AGENT_SPECS


def brainstorm_agent_specs() -> tuple[BrainstormAgentSpec, ...]:
    """Specs Brainstorm suplementares validadas, na ordem de registro.

    Consumida IDENTICAMENTE por `_build_brainstorm_page()` e
    `_rebuild_brainstorm_grid()`: e isso que faz o botao sobreviver ao gear.
    """
    validate_registry()
    return _BRAINSTORM_AGENT_SPECS


def registry_testids(
    mcp_specs: Sequence[McpAgentSpec] | None = None,
    brainstorm_specs: Sequence[BrainstormAgentSpec] | None = None,
) -> tuple[str, ...]:
    """Todos os testids suplementares (MCP primeiro, depois Brainstorm)."""
    mcp = tuple(_MCP_AGENT_SPECS if mcp_specs is None else mcp_specs)
    brainstorm = tuple(
        _BRAINSTORM_AGENT_SPECS if brainstorm_specs is None else brainstorm_specs
    )
    return tuple([s.testid for s in mcp] + [s.testid for s in brainstorm])


def find_mcp_agent_spec(slug: str) -> McpAgentSpec | None:
    """Busca spec MCP por slug. Devolve None quando ausente (nunca levanta)."""
    for spec in mcp_agent_specs():
        if spec.slug == slug:
            return spec
    return None


def find_brainstorm_agent_spec(slug: str) -> BrainstormAgentSpec | None:
    """Busca spec Brainstorm por slug. Devolve None quando ausente."""
    for spec in brainstorm_agent_specs():
        if spec.slug == slug:
            return spec
    return None


def brainstorm_button_kwargs(
    spec: BrainstormAgentSpec,
    *,
    repo_root: Path | str | None = None,
    radio_state_getter: object | None = None,
) -> dict[str, object]:
    """Traduz a spec para os kwargs de `MCPPromptButton` (build == rebuild).

    Pura: quando `repo_root` e informado, o prompt vira `repo_root/prompt_path`
    SEM tocar o filesystem; sem `repo_root`, devolve o path relativo como str.
    `radio_state_getter` e repassado inalterado (opcional).
    """
    if not isinstance(spec, BrainstormAgentSpec):
        raise AgentIntegrationSpecError(
            "spec Brainstorm invalida: esperado BrainstormAgentSpec",
            field="spec",
        )
    prompt: str | Path
    if repo_root is None:
        prompt = spec.prompt_path
    else:
        prompt = Path(repo_root) / spec.prompt_path

    kwargs: dict[str, object] = {
        "label": spec.label,
        "button_type": spec.button_type,
        "prompt": prompt,
        "agent_name": spec.agent_name,
        "agent_path": spec.agent_path,
        "action": spec.action,
        "target_path": spec.resolved_target_terminal,
        "testid_slug": spec.slug,
        "target_path_edit_inplace": spec.target_path_edit_inplace,
    }
    if radio_state_getter is not None:
        kwargs["radio_state_getter"] = radio_state_getter
    return kwargs


__all__ = [
    "AgentIntegrationSpecError",
    "BRAINSTORM_TESTID_PREFIX",
    "BrainstormAgentSpec",
    "CODEX_TARGET_TERMINAL",
    "DEFAULT_TARGET_TERMINAL",
    "MCP_TESTID_PREFIX",
    "McpAgentSpec",
    "SLUG_MAX_CHARS",
    "SLUG_RE",
    "SUPPORTED_ACTIONS",
    "assert_no_seed_slug_collision",
    "assert_no_testid_collision",
    "brainstorm_agent_specs",
    "brainstorm_button_kwargs",
    "find_brainstorm_agent_spec",
    "find_mcp_agent_spec",
    "mcp_agent_specs",
    "registry_testids",
    "supported_actions",
    "validate_action",
    "validate_registry",
    "validate_repo_relative_md",
    "validate_slug",
]
