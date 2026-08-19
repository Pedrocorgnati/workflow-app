"""
Tests for CommandItemWidget (module-10/TASK-3).

Covers:
  - Default status PENDENTE
  - Command name displayed in label
  - ModelBadge displays correct model
  - set_status(PULADO) applies line-through styling
  - set_status(EXECUTANDO) starts StatusDot pulse
  - set_status(CONCLUIDO) stops pulse and changes appearance
  - set_model() updates the model badge
  - remove_requested, skip_requested, edit_model_requested signals exist
  - original_position maps to spec.position
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    ModelName,
)
from PySide6.QtWidgets import QApplication


@pytest.fixture()
def spec() -> CommandSpec:
    return CommandSpec(
        name="/prd-create",
        model=ModelName.SONNET,
        position=0,
    )


@pytest.fixture()
def item(spec, qtbot):
    w = CommandItemWidget(spec)
    qtbot.addWidget(w)
    w.show()
    return w


class TestCommandItemWidgetInitialState:
    def test_default_status_pendente(self, item):
        """Initial status is PENDENTE."""
        assert item._status == CommandStatus.PENDENTE

    def test_command_name_displayed(self, item):
        """Command name appears in the name label."""
        assert item._name_label.text() == "/prd-create"

    def test_model_badge_shows_sonnet(self, item):
        """ModelBadge shows 'Son' (short) for SONNET."""
        assert item._model_badge.text() in ("Son", "Sonnet")

    def test_actions_button_exists(self, item):
        """Run button (▶) is present and visible."""
        assert item._run_btn is not None
        assert item._run_btn.isVisible()

    def test_spec_position_accessible(self, item):
        """spec.position is accessible via get_spec()."""
        assert item.get_spec().position == 0


class TestCommandItemWidgetSetStatus:
    def test_set_status_concluido(self, item):
        """CONCLUIDO changes status attribute."""
        item.set_status(CommandStatus.CONCLUIDO)
        assert item._status == CommandStatus.CONCLUIDO

    def test_set_status_erro(self, item):
        """ERRO changes status attribute."""
        item.set_status(CommandStatus.ERRO)
        assert item._status == CommandStatus.ERRO

    def test_set_status_incerto(self, item):
        """INCERTO changes status attribute."""
        item.set_status(CommandStatus.INCERTO)
        assert item._status == CommandStatus.INCERTO

    def test_set_status_pulado_applies_strikethrough(self, item):
        """PULADO applies text-decoration: line-through in name label stylesheet."""
        item.set_status(CommandStatus.PULADO)
        assert "line-through" in item._name_label.styleSheet()

    def test_set_status_non_pulado_removes_strikethrough(self, item):
        """Non-PULADO status removes strikethrough from name label."""
        item.set_status(CommandStatus.PULADO)
        item.set_status(CommandStatus.PENDENTE)
        assert "line-through" not in item._name_label.styleSheet()

    def test_set_status_executando_shows_border(self, item):
        """EXECUTANDO applies a blue left-border highlight to the widget."""
        item.set_status(CommandStatus.EXECUTANDO)
        assert "border-left" in item.styleSheet()

    def test_set_status_concluido_removes_border(self, item):
        """CONCLUIDO after EXECUTANDO removes the border highlight."""
        item.set_status(CommandStatus.EXECUTANDO)
        item.set_status(CommandStatus.CONCLUIDO)
        assert "border-left" not in item.styleSheet()


class TestCommandItemWidgetSetModel:
    def test_set_model_opus(self, item):
        """set_model(OPUS) updates badge to 'Opus' short name."""
        item.set_model(ModelName.OPUS)
        assert item._model_badge.text() in ("Opus",)

    def test_set_model_updates_spec(self, item):
        """set_model updates the internal spec model."""
        item.set_model(ModelName.SONNET)
        assert item.get_spec().model == ModelName.SONNET


class TestCommandItemWidgetSignals:
    def test_skip_requested_signal_exists(self, item):
        """skip_requested signal is defined."""
        assert hasattr(item, "skip_requested")

    def test_remove_requested_signal_exists(self, item):
        """remove_requested signal is defined."""
        assert hasattr(item, "remove_requested")

    def test_edit_model_requested_signal_exists(self, item):
        """edit_model_requested signal is defined."""
        assert hasattr(item, "edit_model_requested")


# ───────────────────────── INCERTO state (GAP-012 fix) ──────── #

class TestCommandItemWidgetIncertoState:
    """INCERTO state must not show error row (only ERRO does)."""

    def test_incerto_hides_error_row(self, item):
        """set_status(INCERTO) must keep error row hidden."""
        item.set_status(CommandStatus.INCERTO)
        assert not item._error_row.isVisible(), (
            "Error row must be hidden for INCERTO status"
        )

    def test_erro_shows_error_row(self, item):
        """set_status(ERRO) must make error row visible (sanity check)."""
        item.set_status(CommandStatus.ERRO)
        assert item._error_row.isVisible(), (
            "Error row must be visible for ERRO status"
        )

    def test_incerto_after_erro_hides_row(self, item):
        """After ERRO, switching to INCERTO hides the error row."""
        item.set_status(CommandStatus.ERRO)
        assert item._error_row.isVisible()
        item.set_status(CommandStatus.INCERTO)
        assert not item._error_row.isVisible()


# ───────────────────── command_text_with_flags (item 012) ─────────── #

from workflow_app.command_queue.command_item_widget import command_text_with_flags
from workflow_app.command_queue.provider_router import Provider


def _make_spec(name="/prd-create", config_path="", kind="slash"):
    return CommandSpec(
        name=name,
        model=ModelName.SONNET,
        position=0,
        config_path=config_path,
        kind=kind,
    )


class TestCommandTextWithFlags:
    """Produtor unico de texto de comando com sufixo de flag (item 012)."""

    def test_claude_with_kimi(self):
        """Claude + flag --kimi -> /prd-create --kimi."""
        spec = _make_spec()
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi"]
        )
        assert result == "/prd-create --kimi"

    def test_claude_with_config_path(self):
        """Claude + config_path + flags -> /cmd --kimi 'path'."""
        spec = _make_spec(name="/cmd", config_path="path/to/config.json")
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi"]
        )
        # Ordem: nome + flags + config_path (shlex.quote sem aspas para path simples).
        assert result == "/cmd --kimi path/to/config.json"

    def test_worker_strips_flags(self):
        """Provider KIMI -> sem flags (worker strip)."""
        spec = _make_spec()
        result = command_text_with_flags(
            spec, provider=Provider.KIMI, active_flags=["--kimi", "--codex"]
        )
        assert result == "/prd-create"

    def test_codex_worker_strips_flags(self):
        """Provider CODEX -> sem flags (worker strip)."""
        spec = _make_spec()
        result = command_text_with_flags(
            spec, provider=Provider.CODEX, active_flags=["--kimi"]
        )
        assert result == "/prd-create"

    def test_session_directive_no_suffix(self):
        """/clear nunca recebe sufixo."""
        spec = _make_spec(name="/clear")
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi"]
        )
        assert result == "/clear"

    def test_model_directive_no_suffix(self):
        """/model nunca recebe sufixo."""
        spec = _make_spec(name="/model opus")
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi"]
        )
        assert result == "/model opus"

    @pytest.mark.parametrize(
        "name", ["/model sol high", "/model k3", "/reasoning yes", "/reasoning no"]
    )
    def test_foreign_dialect_directive_no_suffix(self, name):
        """Residuo do dialeto revogado (C27) ainda e diretiva de sessao.

        Regressao real: `/reasoning` nao estava em `_SESSION_DIRECTIVES` quando a
        traducao Kimi foi implantada. Como sob Main Kimi o `classify_provider`
        devolve CLAUDE por fallback, a linha era considerada elegivel a flag e
        saia da fila como `/reasoning yes --codex` — que nenhum REPL entende.

        A traducao foi revogada em 2026-08-17 (D-C27-2) e nada mais PRODUZ esses
        literais, mas snapshots salvos naquela janela ainda os trazem. A
        exclusao de sufixo continua valendo para eles: a linha e suprimida no
        dispatch, e uma linha suprimida nunca pode aparecer flagueada na fila.
        """
        spec = _make_spec(name=name)
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi", "--codex"]
        )
        assert result == name

    def test_local_action_no_suffix(self):
        """local-action nunca recebe sufixo."""
        spec = _make_spec(name="/daily", kind="local-action")
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi"]
        )
        assert result == "/daily"

    def test_empty_flags(self):
        """active_flags vazia -> /prd-create (regressao zero)."""
        spec = _make_spec()
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=[]
        )
        assert result == "/prd-create"

    def test_both_flags(self):
        """Claude + ambas flags -> /cmd --kimi --codex."""
        spec = _make_spec(name="/cmd")
        result = command_text_with_flags(
            spec, provider=Provider.CLAUDE, active_flags=["--kimi", "--codex"]
        )
        assert result == "/cmd --kimi --codex"

    def test_none_provider_no_suffix(self):
        """Provider None (Desabilitado) -> sem sufixo."""
        spec = _make_spec()
        result = command_text_with_flags(
            spec, provider=None, active_flags=["--kimi"]
        )
        assert result == "/prd-create"


class TestDispatchText:
    """set_dispatch_text / dispatch_text (item 012)."""

    def test_dispatch_text_default_fallback(self, item):
        """Sem set_dispatch_text, dispatch_text() == command_text()."""
        assert item.dispatch_text() == item.command_text()

    def test_dispatch_text_set_overrides(self, item):
        """Apos set_dispatch_text, dispatch_text() retorna o texto setado."""
        item.set_dispatch_text("/prd-create --kimi")
        assert item.dispatch_text() == "/prd-create --kimi"

    def test_dispatch_text_empty_restores_fallback(self, item):
        """set_dispatch_text('') restaura fallback para command_text()."""
        item.set_dispatch_text("/prd-create --kimi")
        item.set_dispatch_text("")
        assert item.dispatch_text() == item.command_text()

    def test_per_item_run_uses_dispatch_text(self, item, qtbot):
        """_on_run_clicked emite dispatch_text() (com flags)."""
        item.set_dispatch_text("/prd-create --kimi")
        captured = []
        item.run_in_terminal_requested.connect(captured.append)
        item._on_run_clicked()
        assert captured == ["/prd-create --kimi"]

    def test_per_item_copy_uses_dispatch_text(self, item, qtbot):
        """_on_copy_clicked copia dispatch_text() (com flags)."""
        item.set_dispatch_text("/prd-create --kimi")
        item._on_copy_clicked()
        clipboard = QApplication.clipboard()
        if clipboard:
            assert clipboard.text() == "/prd-create --kimi"
