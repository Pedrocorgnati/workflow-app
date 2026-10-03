"""MiMo no roteador (regra 5c), elegibilidade T2 compartilhada e gate de imagem.

Q9 (`ai-forge/rules/mcp-quota-fallback.md`, 2026-10-02): a MiMo substitui o
Kimi como worker T2 e vence o Kimi em toda duvida. Este arquivo trava:

- superficie: `Provider.MIMO`, familia/variante, `RoutingState.mimo_worker_enabled`
  e `T2_PROVIDERS` servido via PEP 562, fora de `dir()` (o snapshot legado
  `tests/fixtures/llm_config_legacy_snapshot.json` trava os simbolos publicos);
- regra 5c avaliada PRIMEIRO no T2 (ordem total MiMo > Kimi > Qwen > Codex >
  Grok > Claude) e paridade com as regras legadas quando a MiMo esta desligada;
- gate de imagem: geracao de imagem nunca e elegivel ao T2, nem com o flag
  herdado `kimi_eligible`;
- `delegate_command` recusa MIMO antes de renderizar ou despachar (caminho
  dormente, como QWEN);
- `/reasoning` sai da fila sob Main mimo e dos gates de shape do loader;
- worker MiMo sem capability na matrix; seta azul (T2) do item roteado a MIMO;
- D3: o router (e a elegibilidade T2 que ele chama) nao le o kill switch.

O router nao le o kill switch: `mimo_worker_enabled` chega pronto do produtor
unico (`_resolve_item_provider`, no widget da fila). Aqui o estado e montado a
mao; so a sonda de D3 mexe na env do switch, e sempre num processo filho.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from workflow_app.command_queue import provider_router
from workflow_app.command_queue.codex_whitelist import (
    CODEX_COMPATIBLE_COMMANDS,
    IMAGE_GENERATION_COMMANDS,
    is_codex_compatible,
)
from workflow_app.command_queue.delegation_transport import delegate_command
from workflow_app.command_queue.kimi_whitelist import (
    KIMI_COMPATIBLE_COMMANDS,
    is_kimi_compatible,
    is_t2_eligible,
)
from workflow_app.command_queue.model_effort_equivalence import (
    PROVIDERS_WITHOUT_MODEL_DIRECTIVES,
    adapt_specs_to_main,
    is_suppressed_directive,
)
from workflow_app.command_queue.provider_router import (
    Provider,
    RoutingState,
    _classify_family_variant,
    classify_provider,
)
from workflow_app.config import feature_flags
from workflow_app.daily_loop import loader
from workflow_app.domain import CommandSpec, ModelName

# `_classify_family_variant` e `_T2_PROVIDERS` sao privados de proposito: o
# snapshot legado compara `dir(provider_router)`, e binding publico novo no
# modulo e regressao de superficie. Os testes consomem os nomes privados.

TESTS_DIR = Path(__file__).resolve().parent
APP_ROOT = TESTS_DIR.parent
REPO_ROOT = TESTS_DIR.parents[2]
GENERATOR_PATH = REPO_ROOT / "ai-forge" / "scripts" / "gen-provider-capability-matrix.py"
SNAPSHOT_PATH = REPO_ROOT / "ai-forge" / "schemas" / "provider-capability-matrix.json"
LEGACY_FIXTURE_PATH = TESTS_DIR / "fixtures" / "llm_config_legacy_snapshot.json"

T2_CMD = "/dcp:matrix-init"  # whitelist Kimi
CODEX_CMD = "/cmd:review"  # whitelist Codex
OTHER_CMD = "/prd-create"  # nenhuma whitelist
IMAGE_CMD = "/pictures-create"  # IMAGE_GENERATION_COMMANDS

#: (kimi, qwen, codex, grok): todas as combinacoes dos workers que nao sao MiMo.
_WORKER_COMBOS = list(itertools.product([False, True], repeat=4))

#: Universo das whitelists sem a geracao de imagem, mais um comando fora de
#: whitelist. A imagem fica de fora da paridade porque o gate dela mudou de
#: proposito (ver `TestImageGenerationNeverT2`).
_NON_IMAGE_NAMES = sorted(
    (KIMI_COMPATIBLE_COMMANDS | CODEX_COMPATIBLE_COMMANDS) - IMAGE_GENERATION_COMMANDS
) + [OTHER_CMD]

#: Ocupantes do T2 esperados (espelho literal de `T2_PROVIDERS`).
_T2_SET = frozenset({Provider.KIMI, Provider.QWEN, Provider.MIMO})


def _spec(name: str, **kw: object) -> CommandSpec:
    """CommandSpec minimo para o router.

    `force_main_llm` e `is_prompt` vao explicitos: as regras 0/0b mandam a
    CLAUDE antes de qualquer worker, e o teste nao pode depender do default do
    dataclass.
    """
    kw.setdefault("force_main_llm", False)
    kw.setdefault("is_prompt", False)
    return CommandSpec(name=name, **kw)  # type: ignore[arg-type]


def _st(
    *,
    kimi: bool = False,
    codex: bool = False,
    qwen: bool = False,
    grok: bool = False,
    mimo: bool = False,
    main: str = "claude",
) -> RoutingState:
    return RoutingState(
        kimi_worker_enabled=kimi,
        codex_worker_enabled=codex,
        main_llm=main,
        qwen_worker_enabled=qwen,
        grok_worker_enabled=grok,
        mimo_worker_enabled=mimo,
    )


def _legacy_rules_3_to_8(name: str, kimi_eligible: bool, st: RoutingState) -> Provider:
    """Oraculo congelado: regras 3..8 como estavam antes da 5c e do gate de imagem.

    Copia do corpo anterior a MiMo, sem `mimo_worker_enabled`. Com a MiMo
    desligada e fora da geracao de imagem, `classify_provider` tem de concordar
    com ele em toda entrada.
    """
    head = provider_router.normalize_command_name(name)
    if not (
        st.kimi_worker_enabled
        or st.codex_worker_enabled
        or st.qwen_worker_enabled
        or st.grok_worker_enabled
    ):
        return Provider.CLAUDE
    t2_ok = kimi_eligible or is_kimi_compatible(head)
    if st.kimi_worker_enabled and t2_ok:
        return Provider.KIMI
    if st.qwen_worker_enabled and t2_ok:
        return Provider.QWEN
    if st.codex_worker_enabled and is_codex_compatible(head):
        return Provider.CODEX
    if st.grok_worker_enabled and is_codex_compatible(head):
        return Provider.GROK
    return Provider.CLAUDE


def _loop_config(mode: str, items: list[dict], *, integrated: bool = True) -> dict:
    """`_LOOP-CONFIG.json` minimo para os gates de shape do loader."""
    metadata = {"integration_completed_at": "2026-10-02T00:00:00Z"} if integrated else {}
    return {
        "mode": mode,
        "metadata": metadata,
        "daily_loop": {"buckets": [{"id": "b1", "items": items}]},
    }


def _load_matrix_generator() -> ModuleType:
    """Importa o gerador da matrix como modulo, sem roda-lo como script.

    Nada e escrito em disco: a matrix sai em memoria a partir do yaml autoral.
    Regenerar o snapshot versionado continua sendo trabalho do gerador + `--check`.
    """
    spec = importlib.util.spec_from_file_location("gen_provider_capability_matrix", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated_matrix() -> dict:
    gen = _load_matrix_generator()
    return gen.generate_matrix(gen.load_authorial(gen.AUTHORIAL_PATH))


# --------------------------------------------------------------------------- #
# Superficie: enum, familia/variante, RoutingState, T2_PROVIDERS               #
# --------------------------------------------------------------------------- #


class TestMimoSurface:
    def test_provider_enum_has_mimo(self) -> None:
        """Provider.MIMO existe com valor 'mimo'; a variante thinking nao e provider."""
        assert hasattr(Provider, "MIMO")
        assert Provider.MIMO.value == "mimo"
        assert Provider.MIMO == "mimo"  # str-Enum
        assert "mimo-pro" not in {p.value for p in Provider}

    def test_enum_and_family(self) -> None:
        """O nome publico historico (PEP 562) resolve a familia da MiMo."""
        assert Provider.MIMO.value == "mimo"
        assert provider_router.classify_family_variant("mimo") == ("mimo", "mimo")
        assert provider_router.classify_family_variant("MiMo") == ("mimo", "mimo")

    @pytest.mark.parametrize(
        ("provider", "expected_family", "expected_variant"),
        [
            ("mimo", "mimo", "mimo"),
            ("MiMo", "mimo", "mimo"),
            ("MIMO", "mimo", "mimo"),
            ("mimo-pro", "unknown", "unknown"),
        ],
        ids=["mimo", "MiMo", "MIMO", "mimo-pro-is-a-variant"],
    )
    def test_classify_family_variant_mimo(
        self, provider: str, expected_family: str, expected_variant: str
    ) -> None:
        assert _classify_family_variant(provider) == (expected_family, expected_variant)

    def test_routing_state_default_is_off(self) -> None:
        st = RoutingState(kimi_worker_enabled=False, codex_worker_enabled=False, main_llm="claude")
        assert st.mimo_worker_enabled is False

    def test_three_positionals_still_valid(self) -> None:
        """O probe do snapshot legado constroi `RoutingState(kimi, codex, main_llm)`."""
        st = RoutingState(True, False, "claude")
        assert st.kimi_worker_enabled is True
        assert (st.qwen_worker_enabled, st.grok_worker_enabled, st.mimo_worker_enabled) == (
            False,
            False,
            False,
        )

    def test_t2_providers_value_and_not_in_dir(self) -> None:
        from workflow_app.command_queue.provider_router import T2_PROVIDERS

        assert T2_PROVIDERS == _T2_SET
        assert T2_PROVIDERS is provider_router._T2_PROVIDERS
        assert "T2_PROVIDERS" not in dir(provider_router)
        assert "is_t2_eligible" not in dir(provider_router)
        assert Provider.CODEX not in T2_PROVIDERS and Provider.GROK not in T2_PROVIDERS

    def test_unknown_module_attribute_still_raises(self) -> None:
        """O `__getattr__` do modulo so serve os nomes que conhece."""
        with pytest.raises(AttributeError):
            getattr(provider_router, "T3_PROVIDERS")

    def test_public_symbols_match_legacy_snapshot(self) -> None:
        """A MiMo nao acrescenta simbolo publico ao router (oraculo versionado)."""
        fixture = json.loads(LEGACY_FIXTURE_PATH.read_text(encoding="utf-8"))
        public = sorted(n for n in dir(provider_router) if not n.startswith("_"))
        assert public == fixture["snapshot"]["public_symbols"]


# --------------------------------------------------------------------------- #
# Regra 5c: MiMo primeiro dentro do T2                                         #
# --------------------------------------------------------------------------- #


class TestMimoT2Routing:
    def test_rule_5c_whitelist(self) -> None:
        # So a MiMo ligada: sem o guard novo da regra 3 o item cairia em CLAUDE
        # antes de chegar ao bloco T2.
        assert classify_provider(_spec(T2_CMD), _st(mimo=True)) is Provider.MIMO

    def test_rule_5c_flag(self) -> None:
        assert (
            classify_provider(_spec(OTHER_CMD, kimi_eligible=True), _st(mimo=True)) is Provider.MIMO
        )

    @pytest.mark.parametrize("main", [p.value for p in Provider])
    def test_rule_3_guard_counts_mimo(self, main: str) -> None:
        # So o worker MiMo ligado, com qualquer Main (o Main nao entra no guard).
        # Sem o termo `mimo_worker_enabled` no guard da regra 3, os itens
        # elegiveis ao T2 sairiam em CLAUDE antes de chegar a regra 5c.
        only_mimo = _st(mimo=True, main=main)
        assert classify_provider(_spec(T2_CMD), only_mimo) is Provider.MIMO
        assert classify_provider(_spec(OTHER_CMD, kimi_eligible=True), only_mimo) is Provider.MIMO
        # Controle negativo: sem elegibilidade T2 e com o Codex desligado, o item
        # atravessa o guard e cai em CLAUDE pela regra 8.
        assert classify_provider(_spec(CODEX_CMD), only_mimo) is Provider.CLAUDE

    @pytest.mark.parametrize(("kimi", "qwen", "codex", "grok"), _WORKER_COMBOS)
    def test_mimo_wins_every_combination(
        self, kimi: bool, qwen: bool, codex: bool, grok: bool
    ) -> None:
        st = _st(kimi=kimi, qwen=qwen, codex=codex, grok=grok, mimo=True)
        assert classify_provider(_spec(T2_CMD), st) is Provider.MIMO
        assert classify_provider(_spec(OTHER_CMD, kimi_eligible=True), st) is Provider.MIMO

    def test_kimi_alone_still_works(self) -> None:
        assert classify_provider(_spec(T2_CMD), _st(kimi=True)) is Provider.KIMI
        assert classify_provider(_spec(T2_CMD), _st(kimi=True, qwen=True)) is Provider.KIMI
        assert classify_provider(_spec(T2_CMD), _st(qwen=True)) is Provider.QWEN

    def test_codex_only_command_still_goes_t3_with_mimo_on(self) -> None:
        assert classify_provider(_spec(CODEX_CMD), _st(mimo=True, codex=True)) is Provider.CODEX
        assert classify_provider(_spec(CODEX_CMD), _st(mimo=True, grok=True)) is Provider.GROK

    @pytest.mark.parametrize(
        "spec",
        [
            _spec("/clear", kimi_eligible=True),
            _spec("/model opus"),
            _spec("/effort high"),
            _spec("/reasoning yes", kimi_eligible=True),
            _spec(T2_CMD, kind="local-action"),
            _spec(T2_CMD, force_main_llm=True),
            _spec(T2_CMD, is_prompt=True),
        ],
        ids=[
            "clear",
            "model",
            "effort",
            "reasoning",
            "local-action",
            "force_main_llm",
            "is_prompt",
        ],
    )
    def test_pre_worker_rules_beat_mimo(self, spec: CommandSpec) -> None:
        assert classify_provider(spec, _st(mimo=True)) is Provider.CLAUDE
        every_worker = _st(kimi=True, qwen=True, codex=True, grok=True, mimo=True)
        assert classify_provider(spec, every_worker) is Provider.CLAUDE

    def test_main_mimo_collision_worker_wins(self) -> None:
        # Invariante 2: o Main nao participa; na colisao Main == Worker o worker vence.
        assert classify_provider(_spec(T2_CMD), _st(mimo=True, main="mimo")) is Provider.MIMO
        assert classify_provider(_spec(OTHER_CMD), _st(mimo=True, main="mimo")) is Provider.CLAUDE


# --------------------------------------------------------------------------- #
# Paridade legada (MiMo desligada) e D1 (MiMo marcada nunca perde para o Kimi) #
# --------------------------------------------------------------------------- #


class TestLegacyParityWithMimoOff:
    @pytest.mark.parametrize(("kimi", "qwen", "codex", "grok"), _WORKER_COMBOS)
    def test_mimo_off_matches_legacy_rules(
        self, kimi: bool, qwen: bool, codex: bool, grok: bool
    ) -> None:
        st = _st(kimi=kimi, qwen=qwen, codex=codex, grok=grok)
        for name in _NON_IMAGE_NAMES:
            for flag in (False, True):
                got = classify_provider(_spec(name, kimi_eligible=flag), st)
                assert got is _legacy_rules_3_to_8(name, flag, st), (name, flag)

    @pytest.mark.parametrize(
        ("qwen", "codex", "grok"), list(itertools.product([False, True], repeat=3))
    )
    def test_kimi_never_returned_with_mimo_checked(
        self, qwen: bool, codex: bool, grok: bool
    ) -> None:
        """D1: com Kimi e MiMo marcados, nenhum comando vai ao Kimi (nem ao Qwen)."""
        st = _st(kimi=True, qwen=qwen, codex=codex, grok=grok, mimo=True)
        for name in _NON_IMAGE_NAMES + sorted(IMAGE_GENERATION_COMMANDS):
            for flag in (False, True):
                got = classify_provider(_spec(name, kimi_eligible=flag), st)
                assert got not in {Provider.KIMI, Provider.QWEN}, (name, flag, got)

    def test_whole_kimi_whitelist_goes_to_mimo_when_checked(self) -> None:
        for name in sorted(KIMI_COMPATIBLE_COMMANDS):
            assert classify_provider(_spec(name), _st(kimi=True, mimo=True)) is Provider.MIMO, name
            assert classify_provider(_spec(name), _st(kimi=True)) is Provider.KIMI, name
            assert classify_provider(_spec(name), _st(qwen=True)) is Provider.QWEN, name


# --------------------------------------------------------------------------- #
# D3: o router nao le o kill switch do CLI MiMo                                #
# --------------------------------------------------------------------------- #

#: Caminho de decisao do router: `classify_provider` e a elegibilidade T2 (com o
#: gate de imagem) que ele chama.
_ROUTER_DECISION_MODULES = (
    "src/workflow_app/command_queue/provider_router.py",
    "src/workflow_app/command_queue/kimi_whitelist.py",
    "src/workflow_app/command_queue/codex_whitelist.py",
)

#: Identificadores que denunciam leitura do switch: o modulo de flags ou a API
#: `mimo_v1_*`.
_SWITCH_MARKERS = ("feature_flags", "mimo_v1")

#: Sonda em processo novo: o switch e congelado no boot, entao mudar `os.environ`
#: depois do import nao provaria nada. Imprime o estado do switch visto pelo
#: filho e a decisao do router para Kimi so, Qwen so, nenhum worker e MiMo so.
_SWITCH_PROBE = """
import json
import sys

from workflow_app.command_queue.provider_router import RoutingState, classify_provider
from workflow_app.config import feature_flags
from workflow_app.domain import CommandSpec

spec = CommandSpec(name=sys.argv[1], force_main_llm=False, is_prompt=False)
states = [
    RoutingState(True, False, "claude"),
    RoutingState(False, False, "claude", qwen_worker_enabled=True),
    RoutingState(False, False, "claude"),
    RoutingState(False, False, "claude", mimo_worker_enabled=True),
]
print(json.dumps({
    "switch_on": feature_flags.mimo_v1_enabled(),
    "decisions": [classify_provider(spec, st).value for st in states],
}))
"""


def _switch_reads(source: str) -> list[str]:
    """Identificadores de codigo (import, nome, atributo) que leriam o switch.

    Docstring e comentario nao contam: podem citar o switch para dizer que o
    router NAO o le.
    """
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            idents = [node.module or ""]
        elif isinstance(node, ast.alias):
            idents = [node.name, node.asname or ""]
        elif isinstance(node, ast.Name):
            idents = [node.id]
        elif isinstance(node, ast.Attribute):
            idents = [node.attr]
        else:
            continue
        hits += [i for i in idents if any(m in i.lower() for m in _SWITCH_MARKERS)]
    return sorted(hits)


class TestRouterNeverReadsTheSwitch:
    """D3: `mimo_worker_enabled` chega pronto do produtor unico; o router nao le o switch."""

    @pytest.mark.parametrize("relpath", _ROUTER_DECISION_MODULES)
    def test_decision_path_has_no_switch_read(self, relpath: str) -> None:
        source = (APP_ROOT / relpath).read_text(encoding="utf-8")
        assert _switch_reads(source) == []
        # Nem leitura direta da env: o literal do switch nao aparece no modulo.
        assert feature_flags.mimo_v1_flag_name() not in source

    @pytest.mark.parametrize(
        "source",
        [
            "from workflow_app.config import feature_flags\nok = feature_flags.mimo_v1_enabled()\n",
            "from workflow_app.config.feature_flags import mimo_v1_enabled\n",
            "import workflow_app.config as cfg\nok = cfg.mimo_v1_state()\n",
        ],
        ids=["module-import", "name-import", "attribute"],
    )
    def test_detector_flags_every_read_form(self, source: str) -> None:
        """O guard acima nao e vacuo: cada forma de leitura e acusada."""
        assert _switch_reads(source) != []

    def test_detector_ignores_docstring_and_comment(self) -> None:
        source = '"""Cita `feature_flags.mimo_v1_enabled()` so para negar."""\n# mimo_v1\n'
        assert _switch_reads(source) == []

    @pytest.mark.parametrize("switch_on", [False, True], ids=["switch-absent", "switch-on"])
    def test_router_output_ignores_the_switch(self, switch_on: bool) -> None:
        env = os.environ.copy()
        flag = feature_flags.mimo_v1_flag_name()
        if switch_on:
            env[flag] = "1"
        else:
            env.pop(flag, None)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(APP_ROOT / "src"), env.get("PYTHONPATH")))
        )
        result = subprocess.run(
            [sys.executable, "-c", _SWITCH_PROBE, T2_CMD],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(APP_ROOT),
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        # Nao vacuo: o filho viu o switch no estado pedido.
        assert report["switch_on"] is switch_on
        # Mesma decisao com o switch ausente ou ligado: o switch nao liga a MiMo
        # sem o campo nem a desliga com o campo.
        assert report["decisions"] == ["kimi", "qwen", "claude", "mimo"]


# --------------------------------------------------------------------------- #
# Gate de imagem: so o Codex gera pixels                                       #
# --------------------------------------------------------------------------- #


class TestImageGenerationNeverT2:
    @pytest.mark.parametrize(
        ("codex", "grok", "expected"),
        [
            (True, False, Provider.CODEX),
            (True, True, Provider.CODEX),
            (False, True, Provider.GROK),
            (False, False, Provider.CLAUDE),
        ],
    )
    def test_image_generation_never_t2(self, codex: bool, grok: bool, expected: Provider) -> None:
        st = _st(kimi=True, qwen=True, mimo=True, codex=codex, grok=grok)
        for name in (IMAGE_CMD, IMAGE_CMD + " --module 3"):
            got = classify_provider(_spec(name, kimi_eligible=True), st)
            assert got not in _T2_SET
            assert got is expected

    @pytest.mark.parametrize(
        "state",
        [
            _st(mimo=True),
            _st(kimi=True),
            _st(qwen=True),
            _st(kimi=True, qwen=True, mimo=True),
        ],
        ids=["mimo", "kimi", "qwen", "all-t2"],
    )
    def test_image_with_only_t2_worker_falls_to_claude(self, state: RoutingState) -> None:
        """Mudanca deliberada: antes, imagem com `kimi_eligible` ia ao T2 ligado."""
        assert classify_provider(_spec(IMAGE_CMD, kimi_eligible=True), state) is Provider.CLAUDE

    def test_image_commands_are_not_in_the_kimi_whitelist(self) -> None:
        assert IMAGE_GENERATION_COMMANDS
        assert not (IMAGE_GENERATION_COMMANDS & KIMI_COMPATIBLE_COMMANDS)
        assert IMAGE_GENERATION_COMMANDS <= CODEX_COMPATIBLE_COMMANDS


# --------------------------------------------------------------------------- #
# kimi_whitelist.is_t2_eligible                                                #
# --------------------------------------------------------------------------- #


class TestIsT2Eligible:
    def test_is_t2_eligible_units(self) -> None:
        assert is_t2_eligible(T2_CMD) is True
        assert is_t2_eligible(T2_CMD + " --module 3") is True
        assert is_t2_eligible(OTHER_CMD) is False
        assert is_t2_eligible(OTHER_CMD, kimi_eligible=True) is True
        assert is_t2_eligible(IMAGE_CMD) is False
        assert is_t2_eligible(IMAGE_CMD, kimi_eligible=True) is False
        assert is_t2_eligible(IMAGE_CMD + " --x", kimi_eligible=True) is False
        assert is_t2_eligible("") is False
        # Nome vazio com o flag herdado: o flag decide, como antes do helper.
        assert is_t2_eligible("   ", kimi_eligible=True) is True

    def test_is_t2_eligible_matches_legacy_outside_image(self) -> None:
        for cmd in sorted(KIMI_COMPATIBLE_COMMANDS) + [CODEX_CMD, OTHER_CMD]:
            for flag in (False, True):
                assert is_t2_eligible(cmd, kimi_eligible=flag) == (flag or is_kimi_compatible(cmd))

    def test_kimi_eligible_is_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            is_t2_eligible(T2_CMD, True)  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# delegation_transport: MIMO e destino dormente                                #
# --------------------------------------------------------------------------- #


class TestMimoDelegation:
    def test_delegate_command_mimo_rejected_without_dispatch(self) -> None:
        calls: list[tuple[str, Provider, str]] = []

        def _dispatch(command_text: str, provider: Provider, topic: str) -> dict:
            calls.append((command_text, provider, topic))
            return {"status": "ok"}

        spec = CommandSpec(name=T2_CMD, model=ModelName.SONNET, position=1, kimi_eligible=True)
        result = delegate_command(spec, Provider.MIMO, [], "s-mimo", dispatch_fn=_dispatch)

        assert result.ok is False
        assert result.error == "unknown-delegation-target:mimo"
        assert result.step_id == "s-mimo"
        assert result.parsed is None
        assert calls == []


# --------------------------------------------------------------------------- #
# Diretivas: o TUI do CLI MiMo nao tem /model, /effort nem /reasoning (D8)     #
# --------------------------------------------------------------------------- #


class TestMimoDirectives:
    def test_mimo_main_has_no_model_directives(self) -> None:
        assert "mimo" in PROVIDERS_WITHOUT_MODEL_DIRECTIVES

    def test_adapt_specs_to_main_drops_directives_keeps_clear(self) -> None:
        names = ["/clear", "/model opus", "/effort high", "/reasoning yes", "/qa:trace --module 1"]
        specs = [CommandSpec(name=n) for n in names]
        kept = adapt_specs_to_main(specs, "mimo")
        assert [s.name for s in kept] == ["/clear", "/qa:trace --module 1"]
        assert adapt_specs_to_main(kept, "mimo") is kept  # idempotente

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("/reasoning yes", True),
            ("/model opus", True),
            ("/effort high", True),
            ("/clear", False),
            ("/qa:trace", False),
        ],
    )
    def test_is_suppressed_directive_under_main_mimo(self, name: str, expected: bool) -> None:
        assert is_suppressed_directive(name, "mimo") is expected

    def test_strip_directives_removes_reasoning(self) -> None:
        cmds = ["/clear", "/model opus", "/effort high", "/reasoning yes", "   ", "/create-task x"]
        assert loader._strip_directives(cmds) == ["/create-task x"]

    def test_strip_directives_keeps_lookalikes(self) -> None:
        cmds = ["/reasoning-foo bar", "/effortless", "/modelo x", "/clearance"]
        assert loader._strip_directives(cmds) == cmds

    def test_rocksmash_gate_accepts_reasoning_residue(self) -> None:
        item = {
            "id": "001",
            "kind": "iteration",
            "commands": [
                "/clear",
                "/reasoning yes",
                "/loop-rocksmash:do --task t.md",
                "/loop-rocksmash:review-done",
                "/loop-rocksmash:compare",
                "/loop-rocksmash:integrate",
            ],
        }
        loader.assert_rocksmash_iteration_shape(_loop_config("rocksmash", [item]))

    def test_rocksmash_gate_still_rejects_wrong_shape(self) -> None:
        item = {
            "id": "001",
            "kind": "iteration",
            "commands": ["/reasoning yes", "/loop-rocksmash:do"],
        }
        with pytest.raises(
            loader.DailyLoopConfigError, match="shape de iteration_template invalido"
        ):
            loader.assert_rocksmash_iteration_shape(_loop_config("rocksmash", [item]))

    def test_mkt_assets_gate_accepts_reasoning_residue(self) -> None:
        item = {
            "id": "001",
            "commands": ["/clear", "/reasoning high", "/mkt-assets:iteraction:generate-post"],
        }
        loader.assert_mkt_assets_iteration_shape(_loop_config("mkt_assets", [item]))

    def test_mkt_assets_gate_rejects_reasoning_lookalike(self) -> None:
        item = {
            "id": "001",
            "commands": ["/reasoning-foo bar", "/mkt-assets:iteraction:generate-post"],
        }
        with pytest.raises(loader.DailyLoopConfigError, match="fora da lane"):
            loader.assert_mkt_assets_iteration_shape(_loop_config("mkt_assets", [item]))

    def test_directive_only_item_is_empty_after_integration(self) -> None:
        item = {"id": "001", "commands": ["/clear", "/reasoning yes"]}
        with pytest.raises(loader.DailyLoopConfigError, match="vazio apos integracao"):
            loader.assert_mkt_assets_iteration_shape(_loop_config("mkt_assets", [item]))
        # Antes da integracao o placeholder e tolerado.
        loader.assert_mkt_assets_iteration_shape(
            _loop_config("mkt_assets", [item], integrated=False)
        )

    @pytest.mark.parametrize("kind", ["preparo", "finalizacao"])
    def test_preparo_and_finalizacao_are_skipped_by_both_gates(self, kind: str) -> None:
        item = {
            "id": "000",
            "kind": kind,
            "commands": ["/reasoning x", "/loop:iteraction:review-executed-loop"],
        }
        loader.assert_rocksmash_iteration_shape(_loop_config("rocksmash", [item]))
        loader.assert_mkt_assets_iteration_shape(_loop_config("mkt_assets", [item]))

    def test_kimi_pair_commands_untouched(self) -> None:
        """D2: a familia kimi-pair continua exclusiva do Kimi."""
        assert loader._KIMI_PAIR_COMMANDS == ("/cmd:kimi-pair-analyse", "/cmd:kimi-pair-execute")


# --------------------------------------------------------------------------- #
# Matrix de capability (yaml autoral -> gerador, em memoria)                   #
# --------------------------------------------------------------------------- #


class TestMimoCapabilityMatrix:
    _MAIN_RUNTIME_CAPS = frozenset(
        {"tool_execution", "file_write", "mcp_access", "shell_execution"}
    )

    def test_mimo_worker_indisponivel(self, generated_matrix: dict) -> None:
        """Worker MiMo sem capability: tudo indisponivel (fail-closed, D-37)."""
        assert generated_matrix
        for cmd_name, cmd_data in generated_matrix.items():
            assert set(cmd_data["mimo"]) == {"main", "worker"}, cmd_name
            for cap, status in cmd_data["mimo"]["worker"].items():
                assert status == "indisponivel", f"{cmd_name}/mimo/worker/{cap}"
            for cap, status in cmd_data["mimo"]["main"].items():
                if cap in self._MAIN_RUNTIME_CAPS:
                    assert status == "disponivel", f"{cmd_name}/mimo/main/{cap}"

    def test_versioned_snapshot_carries_the_same_mimo_rows(self, generated_matrix: dict) -> None:
        """Leitura apenas: o snapshot em disco bate com a geracao em memoria."""
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for cmd_name, cmd_data in generated_matrix.items():
            assert snapshot["matrix"][cmd_name]["mimo"] == cmd_data["mimo"], cmd_name


# --------------------------------------------------------------------------- #
# Seta unica do item: MIMO pinta o azul do T2                                  #
# --------------------------------------------------------------------------- #


class TestMimoItemWidget:
    def test_mimo_provider_paints_t2_blue(self, qtbot) -> None:
        # Import local: so este teste precisa de Qt.
        from workflow_app.command_queue.command_item_widget import CommandItemWidget

        spec = CommandSpec("/qa:prep", ModelName.SONNET, position=0)
        item = CommandItemWidget(spec, provider_resolver=lambda _s: Provider.MIMO)
        qtbot.addWidget(item)
        item.refresh_provider()

        assert item.effective_provider() is Provider.MIMO
        assert item._exec_btn.isEnabled()
        assert "#3B82F6" in item._exec_btn.styleSheet()
        tooltip = item._exec_btn.toolTip()
        assert "MiMo worker" in tooltip
        assert "T2 terminal-workspace (mimo)" in tooltip
