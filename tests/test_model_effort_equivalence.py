"""Adequacao de `/model` e `/effort` ao Main LLM (queue-command-list, C27).

Contrato coberto:
  - Main `claude`                     -> identidade byte-a-byte
  - Main `codex|kimi|qwen|grok|mimo`  -> as linhas `/model` e `/effort` somem
  - Main desconhecido / vazio         -> identidade (fail-open)
  - residuo de dialeto estrangeiro    -> reconhecido, nunca despachado

A traducao para dialeto de destino (`/model sol high`, `/model k3` +
`/reasoning yes`) existiu por algumas horas em 2026-08-17 e foi REVOGADA: os
dois dialetos foram refutados em terminal real (evidencia e transcricoes no
docstring do modulo e em
`blacksmith/loop-archives/08-17-systemforge-multillm-gaps-refactor/_EVIDENCE-RJ1-RJ2-CLI-SYNTAX.md`).
Nenhum CLI nao-Claude expoe diretiva TEXTUAL de modelo/effort.
"""

from __future__ import annotations

import pytest

from workflow_app.command_queue.model_effort_equivalence import (
    MAIN_LLMS_WITH_NATIVE_DIRECTIVES,
    PROVIDERS_WITHOUT_MODEL_DIRECTIVES,
    adapt_specs_to_main,
    is_directive_line,
    is_foreign_directive,
    is_native_directive,
    is_suppressed_directive,
)
from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName

ALL_MAINS = ["claude", *sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES)]

#: Literais que a traducao revogada produzia. Nenhum e valido em CLI algum;
#: sobrevivem apenas em snapshots salvos antes de 2026-08-17.
LEGACY_FOREIGN = ["/model sol high", "/model spark low", "/model k3", "/reasoning yes"]


def _spec(name: str, model: ModelName = ModelName.OPUS,
          effort: EffortLevel = EffortLevel.HIGH) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=InteractionType.AUTO,
        effort=effort,
    )


def _names(specs: list[CommandSpec]) -> list[str]:
    return [s.name for s in specs]


TRIPLET = ["/clear", "/model opus", "/effort high", "/qa:trace"]


class TestIdentityPaths:
    def test_claude_is_byte_identical(self):
        specs = [_spec(n) for n in TRIPLET]
        out = adapt_specs_to_main(specs, "claude")
        assert out is specs

    def test_unknown_main_is_identity(self):
        """Fail-open: Main desconhecido nunca APAGA diretiva da fila."""
        specs = [_spec(n) for n in TRIPLET]
        assert adapt_specs_to_main(specs, "gemini") is specs

    def test_empty_main_is_identity(self):
        specs = [_spec(n) for n in TRIPLET]
        assert adapt_specs_to_main(specs, "") is specs

    def test_list_without_directives_is_identity(self):
        specs = [_spec("/clear"), _spec("/qa:trace")]
        assert adapt_specs_to_main(specs, "codex") is specs

    def test_input_list_is_never_mutated(self):
        specs = [_spec(n) for n in TRIPLET]
        before = _names(specs)
        for main in ALL_MAINS:
            adapt_specs_to_main(specs, main)
        assert _names(specs) == before

    def test_claude_is_the_only_main_with_native_directives(self):
        assert MAIN_LLMS_WITH_NATIVE_DIRECTIVES == frozenset({"claude"})
        assert not (MAIN_LLMS_WITH_NATIVE_DIRECTIVES & PROVIDERS_WITHOUT_MODEL_DIRECTIVES)


class TestRemovalUnderEveryNonClaudeMain:
    """Codex e Kimi entraram no mesmo conjunto de Qwen/Grok em 2026-08-17.

    Motivo unico para todos: nenhum tem diretiva textual de modelo/effort.
    Nos dois primeiros o `/model` existe, mas como picker interativo que
    DESCARTA o argumento — colar `/model k3` no Kimi ainda abre o picker e
    engole a proxima linha da fila. A MiMo entrou em 2026-10-02 pelo mesmo
    motivo: o TUI dela nao tem `/model`, `/effort` nem `/reasoning`, so os
    pickers `/models` e `/variants`.
    """

    @pytest.mark.parametrize("main", sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES))
    def test_model_and_effort_rows_are_dropped(self, main):
        specs = [_spec(n) for n in TRIPLET]
        assert _names(adapt_specs_to_main(specs, main)) == ["/clear", "/qa:trace"]

    @pytest.mark.parametrize("main", sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES))
    def test_codex_and_kimi_are_in_the_set(self, main):
        assert {"codex", "kimi", "qwen", "grok", "mimo"} == set(
            PROVIDERS_WITHOUT_MODEL_DIRECTIVES
        )

    def test_other_rows_keep_order_and_identity(self):
        specs = [_spec(n) for n in ["/a", "/model opus", "/b", "/effort low", "/c"]]
        out = adapt_specs_to_main(specs, "codex")
        assert _names(out) == ["/a", "/b", "/c"]
        assert out[0] is specs[0] and out[2] is specs[4]

    @pytest.mark.parametrize("main", sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES))
    def test_frozen_foreign_dialect_is_also_dropped(self, main):
        """Snapshot antigo nao volta a ser despachado por nenhum caminho."""
        specs = [_spec(n) for n in LEGACY_FOREIGN] + [_spec("/prd-create")]
        assert _names(adapt_specs_to_main(specs, main)) == ["/prd-create"]

    def test_bare_model_without_value_is_dropped_too(self):
        """`/model` pelado nao pode virar crash nem sobreviver sem valor."""
        assert _names(adapt_specs_to_main([_spec("/model")], "kimi")) == []


class TestNoEnvFlag:
    """A flag `SF_MODEL_EFFORT_EQUIV` foi REMOVIDA junto com a traducao.

    Ela so podia ligar um comportamento comprovadamente quebrado. Este teste
    trava a remocao: se alguem reintroduzir um gate por env-var, o resultado
    deixaria de ser identico com e sem a var e o teste quebra.
    """

    @pytest.mark.parametrize("main", ALL_MAINS)
    @pytest.mark.parametrize("raw", ["1", "0", "", "true"])
    def test_env_var_does_not_change_the_outcome(self, monkeypatch, main, raw):
        monkeypatch.setenv("SF_MODEL_EFFORT_EQUIV", raw)
        with_var = _names(adapt_specs_to_main([_spec(n) for n in TRIPLET], main))
        monkeypatch.delenv("SF_MODEL_EFFORT_EQUIV", raising=False)
        without_var = _names(adapt_specs_to_main([_spec(n) for n in TRIPLET], main))
        assert with_var == without_var

    def test_module_exposes_no_flag_reader(self):
        import workflow_app.command_queue.model_effort_equivalence as mod

        assert not hasattr(mod, "equivalence_enabled")
        assert not hasattr(mod, "translate_specs")


class TestDirectiveMatching:
    """So casa o token EXATO em inicio de linha (mesmo rigor do sentinel C-42)."""

    @pytest.mark.parametrize(
        "name", ["/model-foo bar", "/effortless", "/mkt:portfolio-add /model opus"],
    )
    def test_lookalikes_are_not_directives(self, name):
        specs = [_spec(name)]
        assert adapt_specs_to_main(specs, "qwen") is specs


class TestIsDirectiveLine:
    @pytest.mark.parametrize(
        "name",
        ["/model opus", "/effort high", "/reasoning yes", "/model", "  /MODEL x  "],
    )
    def test_directive_heads(self, name):
        assert is_directive_line(name) is True

    @pytest.mark.parametrize(
        "name",
        ["/clear", "/qa:trace", "/model-foo bar", "/effortless", "", "   ", None,
         "/mkt:portfolio-add /model opus"],
    )
    def test_non_directives(self, name):
        assert is_directive_line(name) is False

    def test_reasoning_stays_a_directive_head(self):
        """Nao e mais produzido, mas precisa continuar sendo RECONHECIDO.

        Sem isto, um `/reasoning yes` restaurado de snapshot seria classificado
        como comando real: o dispatcher tentaria resolver o slug `reasoning`,
        abortaria com toast, e o dot ficaria preso.
        """
        assert is_directive_line("/reasoning yes") is True


class TestIsNativeDirective:
    """O predicado que decide despachar (nativo) ou suprimir (residuo)."""

    @pytest.mark.parametrize(
        "name",
        ["/model opus", "/model sonnet", "/model haiku",
         "/effort low", "/effort medium", "/effort high", "/effort max"],
    )
    def test_claude_accepts_its_own_dialect(self, name):
        assert is_native_directive(name, "claude") is True

    @pytest.mark.parametrize("name", LEGACY_FOREIGN)
    def test_claude_rejects_the_revoked_dialects(self, name):
        assert is_native_directive(name, "claude") is False

    @pytest.mark.parametrize("main", sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES))
    @pytest.mark.parametrize(
        "name", ["/model opus", "/effort high", "/model sol high", "/model k3",
                 "/reasoning yes"],
    )
    def test_no_non_claude_main_has_a_native_directive(self, main, name):
        """A adequacao REMOVE as linhas para esses Mains; nada e nativo.

        Isto e o que faz os quatro dispatchers suprimirem + pulsarem qualquer
        diretiva residual em vez de colar no PTY.
        """
        assert is_native_directive(name, main) is False

    def test_unknown_main_is_never_native(self):
        assert is_native_directive("/model opus", "gemini") is False

    def test_bare_directive_is_never_native(self):
        """`/model` pelado nao tem valor para o CLI aplicar."""
        for main in ALL_MAINS:
            assert is_native_directive("/model", main) is False

    def test_case_is_normalized(self):
        assert is_native_directive("/MODEL OPUS", "claude") is True
        assert is_native_directive("  /Effort HIGH  ", "claude") is True


class TestIsForeignDirective:
    """Predicado do lado Claude: so reprova residuo comprovado."""

    @pytest.mark.parametrize(
        "name",
        [*LEGACY_FOREIGN, "/reasoning no", "/MODEL K3", "  /model sol high  "],
    )
    def test_revoked_dialect_is_flagged(self, name):
        assert is_foreign_directive(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "/model opus",
            "/model sonnet",
            "/model haiku",       # fora do vocabulario antigo: fail-open
            "/effort high",
            "/effort xhigh",      # effort futuro do Claude: nunca suprimir
            "/model",             # pelado
            "/prd-create",
            "/model-foo bar",
            "",
            None,
        ],
    )
    def test_claude_and_unknown_are_not_flagged(self, name):
        assert is_foreign_directive(name) is False


class TestIdempotence:
    """`adapt(adapt(x)) == adapt(x)`.

    `restore_queue_snapshot` reconstroi os specs a partir dos NOMES ja
    renderizados e chama `load_pipeline`, que adequa de novo.
    """

    @pytest.mark.parametrize("main", ALL_MAINS)
    @pytest.mark.parametrize(
        "source",
        [
            ["/model opus", "/effort high"],
            ["/model sonnet", "/effort low", "/prd-create"],
            ["/effort max"],
            ["/clear", "/model opus", "/effort medium", "/qa:trace"],
            LEGACY_FOREIGN,
        ],
    )
    def test_second_pass_is_a_noop(self, main, source):
        once = adapt_specs_to_main([_spec(n) for n in source], main)
        twice = adapt_specs_to_main(once, main)
        assert _names(twice) == _names(once)


class TestSpecFieldsSurvive:
    def test_surviving_specs_are_the_same_objects(self):
        """Nada e reconstruido: quem sobrevive sobrevive intacto."""
        kept = CommandSpec(
            name="/qa:trace",
            model=ModelName.OPUS,
            interaction_type=InteractionType.INTERACTIVE,
            effort=EffortLevel.HIGH,
            phase="F4",
            testid="queue-item-custom",
            kind="slash",
        )
        out = adapt_specs_to_main([_spec("/model opus"), kept], "codex")
        assert out == [kept]
        assert out[0] is kept


class TestIsSuppressedDirective:
    """Item 012 (R-J5): o predicado que o badge de dialeto consome.

    Ele NAO decide dispatch — espelha o guard de diretiva dos dispatchers, para
    que o aviso da UI diga a mesma verdade que o terminal. Por isso cada caso
    abaixo esta amarrado ao guard equivalente do dispatcher; o caso `mimo`
    trava a obrigacao do despacho do Main MiMo (testar `is_directive_line`
    antes de qualquer ramo que publique no PTY ou aborte).
    """

    @pytest.mark.parametrize(
        "main", sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES)
    )
    @pytest.mark.parametrize(
        "name", ["/model opus", "/model sonnet", "/effort high", "/effort max"]
    )
    def test_non_claude_main_suppresses_every_directive(self, main, name):
        """Main nao-Claude fecha em TODA diretiva (`is_directive_line`)."""
        assert is_suppressed_directive(name, main) is True
        assert is_directive_line(name) is True

    @pytest.mark.parametrize(
        "main", ["claude", *sorted(PROVIDERS_WITHOUT_MODEL_DIRECTIVES)]
    )
    @pytest.mark.parametrize("name", ["/prd-create", "/qa:trace --module 1", "/clear"])
    def test_non_directive_is_never_suppressed(self, main, name):
        """Comando comum (e `/clear`, que todo CLI entende) nunca some."""
        assert is_suppressed_directive(name, main) is False

    @pytest.mark.parametrize(
        "name", ["/model opus", "/model haiku", "/effort high", "/effort max"]
    )
    def test_claude_main_keeps_legitimate_directives(self, name):
        """Main Claude e fail-open: diretiva legitima NAO e suprimida."""
        assert is_suppressed_directive(name, "claude") is False

    @pytest.mark.parametrize(
        "name", ["/model sol high", "/model spark low", "/model k3", "/reasoning yes"]
    )
    def test_claude_main_suppresses_proven_foreign_residue(self, name):
        """Main Claude suprime SO o residuo comprovado (`is_foreign_directive`)."""
        assert is_suppressed_directive(name, "claude") is True
        assert is_foreign_directive(name) is True

    @pytest.mark.parametrize("main", ["", None, "   ", "gpt-9"])
    def test_unknown_main_falls_back_to_directive_line(self, main):
        """Main desconhecido/vazio nao e Claude: usa o guard fechado.

        Assimetria deliberada com `adapt_specs_to_main` (que e fail-open para
        Main desconhecido): aqui o retorno so acende um badge de aviso, nunca
        suprime nada — errar para o lado de avisar demais e barato, e o dispatch
        segue sendo a autoridade."""
        assert is_suppressed_directive("/model opus", main) is True
        assert is_suppressed_directive("/prd-create", main) is False

    def test_case_and_whitespace_are_normalized(self):
        """`  /MODEL Opus ` sob ` Codex ` e a mesma linha que `/model opus`."""
        assert is_suppressed_directive("  /MODEL Opus ", "  CODEX ") is True
        assert is_suppressed_directive("/Reasoning Yes", "Claude") is True
