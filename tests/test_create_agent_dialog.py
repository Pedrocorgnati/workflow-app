"""Tests for CreateAgentDialog (AGENT-TASK-003).

Covers validation, focus, limits, keyboard (Escape/Enter), feedback copy,
double-submit guard, state matrix, and retry after FAILED.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton

from workflow_app.create_agent_prompt import (
    DESCRIPTION_MAX_CHARS,
    NAME_MAX_CHARS,
    extract_request_json,
)
from workflow_app.widgets.create_agent_dialog import (
    CreateAgentDialog,
    CreateAgentRequest,
    DialogState,
    DispatchReport,
)

# Synthetic secrets only — never real credentials.
_SYNTH_SK = "sk-" + ("a" * 20)


@pytest.fixture()
def dialog(qapp, qtbot):
    d = CreateAgentDialog()
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    return d


def _find_by_testid(root, testid: str):
    for w in root.findChildren(type(root)):
        pass
    # Walk all QWidget children
    from PySide6.QtWidgets import QWidget

    for w in root.findChildren(QWidget):
        if w.property("testid") == testid:
            return w
    if root.property("testid") == testid:
        return root
    return None


# ── Structure / accessibility ────────────────────────────────────────────────


class TestDialogStructure:
    def test_is_application_modal_qdialog(self, dialog):
        assert isinstance(dialog, QDialog)
        assert dialog.windowModality() == Qt.WindowModality.ApplicationModal
        assert dialog.property("testid") == "create-agent-dialog"

    def test_required_testids_present(self, dialog):
        required = [
            "create-agent-dialog",
            "create-agent-name-input",
            "create-agent-description-input",
            "create-agent-target-mcp-checkbox",
            "create-agent-target-brainstorm-checkbox",
            "create-agent-validation-error",
            "create-agent-progress",
            "create-agent-submit",
            "create-agent-cancel",
        ]
        for tid in required:
            assert _find_by_testid(dialog, tid) is not None, f"missing testid {tid}"

    def test_labels_linked_via_buddy(self, dialog):
        assert dialog._name_label.buddy() is dialog._name_input
        assert dialog._description_label.buddy() is dialog._description_input

    def test_submit_label_exact(self, dialog):
        assert dialog._submit_btn.text() == "Criar agente"

    def test_checkboxes_default_unchecked(self, dialog):
        assert dialog.include_mcp() is False
        assert dialog.include_brainstorm() is False

    def test_initial_focus_on_name(self, dialog, qtbot):
        # showEvent focuses name; process events to apply
        qtbot.wait(10)
        assert dialog.focusWidget() is dialog._name_input or (
            dialog._name_input.hasFocus()
        )


# ── Validation / submit enablement ───────────────────────────────────────────


class TestValidation:
    def test_submit_disabled_when_empty(self, dialog):
        dialog.set_fields(name="", description="")
        assert dialog._submit_btn.isEnabled() is False

    def test_submit_disabled_when_only_name(self, dialog):
        dialog.set_fields(name="Agente X", description="")
        assert dialog._submit_btn.isEnabled() is False

    def test_submit_disabled_when_only_description(self, dialog):
        dialog.set_fields(name="", description="proposito")
        assert dialog._submit_btn.isEnabled() is False

    def test_submit_enabled_when_both_filled(self, dialog):
        dialog.set_fields(name="Agente X", description="proposito util")
        assert dialog._submit_btn.isEnabled() is True

    def test_whitespace_only_keeps_submit_disabled(self, dialog):
        dialog.set_fields(name="   ", description="\n\t  ")
        # strip()-empty -> disabled
        assert dialog._submit_btn.isEnabled() is False

    def test_empty_name_on_submit_shows_error_and_stays_open(self, dialog, qtbot):
        # Force-enable path: fill then clear after enabling, click submit with
        # whitespace that passes reactive check if we force call.
        dialog.set_fields(name="x", description="ok")
        dialog._name_input.setText("   ")
        # Reactive disables submit; call _on_submit directly to exercise gate.
        dialog._submit_btn.setEnabled(True)
        dialog._on_submit()
        assert dialog.isVisible()
        assert dialog.state == DialogState.INVALID
        assert dialog._error_label.isVisible()
        assert "nome" in dialog.last_feedback.lower()
        assert dialog._last_request is None

    def test_empty_description_on_submit(self, dialog):
        dialog.set_fields(name="Agente", description="ok")
        dialog._description_input.setPlainText("   ")
        dialog._submit_btn.setEnabled(True)
        dialog._on_submit()
        assert dialog.state == DialogState.INVALID
        assert "descricao" in dialog.last_feedback.lower()
        assert dialog.isVisible()

    def test_name_limit_rejected(self, dialog):
        dialog.set_fields(
            name="n" * (NAME_MAX_CHARS + 1),
            description="proposito",
        )
        dialog._on_submit()
        assert dialog.state == DialogState.INVALID
        assert "limite" in dialog.last_feedback.lower()
        assert dialog.isVisible()

    def test_description_limit_rejected(self, dialog):
        dialog.set_fields(
            name="Agente",
            description="d" * (DESCRIPTION_MAX_CHARS + 1),
        )
        dialog._on_submit()
        assert dialog.state == DialogState.INVALID
        assert "limite" in dialog.last_feedback.lower()

    def test_secret_pattern_rejected_without_echo(self, dialog):
        dialog.set_fields(name=_SYNTH_SK, description="proposito")
        dialog._on_submit()
        assert dialog.state == DialogState.INVALID
        assert _SYNTH_SK not in dialog.last_feedback
        assert "sk-" not in dialog.last_feedback

    def test_name_rejects_newline(self, dialog):
        dialog.set_fields(name="foo\nbar", description="proposito")
        dialog._on_submit()
        assert dialog.state == DialogState.INVALID


# ── Submit success path / signals ────────────────────────────────────────────


class TestSubmitFlow:
    def test_valid_submit_emits_request_and_enters_dispatching(self, dialog, qtbot):
        requests: list[CreateAgentRequest] = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(
            name="  Revisor de APIs  ",
            description="  Revisao de contratos OpenAPI  ",
            include_mcp=True,
            include_brainstorm=False,
        )
        with qtbot.waitSignal(dialog.submit_requested, timeout=1000):
            dialog._on_submit()

        assert dialog.state == DialogState.DISPATCHING
        assert dialog.in_flight is True
        assert dialog._submit_btn.isEnabled() is False
        assert dialog._cancel_btn.isEnabled() is False
        assert dialog._name_input.isEnabled() is False
        assert len(requests) == 1
        req = requests[0]
        assert req.name == "Revisor de APIs"
        assert req.description == "Revisao de contratos OpenAPI"
        assert req.include_mcp is True
        assert req.include_brainstorm is False
        assert "<agent-request-json>" in req.prompt
        payload = json.loads(extract_request_json(req.prompt))
        assert payload["name"] == "Revisor de APIs"
        assert payload["destinations"]["mcp"] is True
        assert payload["destinations"]["brainstorm"] is False

    def test_double_submit_ignored(self, dialog, qtbot):
        requests: list[CreateAgentRequest] = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog._on_submit()
        dialog._on_submit()
        assert len(requests) == 1
        assert dialog.state == DialogState.DISPATCHING

    def test_report_accepted_closes_with_safe_feedback(self, dialog, qtbot):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        assert dialog.state == DialogState.DISPATCHING

        dialog.report_dispatch_result(
            DispatchReport(accepted=("T1", "T2"), failed=())
        )
        assert dialog.state == DialogState.ACCEPTED
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert "Prompt de criacao publicado" in dialog.last_feedback
        assert "Agente criado" not in dialog.last_feedback

    def test_report_partial_closes_with_lists(self, dialog):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog.report_dispatch_result(
            DispatchReport(accepted=("T1",), failed=("T3",))
        )
        assert dialog.state == DialogState.PARTIAL
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert "T1" in dialog.last_feedback
        assert "T3" in dialog.last_feedback
        assert "Agente criado" not in dialog.last_feedback

    def test_report_failed_stays_open_allows_retry(self, dialog, qtbot):
        requests: list[CreateAgentRequest] = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog.report_dispatch_result(
            DispatchReport(accepted=(), failed=("T3",), errors=("sink indisponivel",))
        )
        assert dialog.isVisible()
        assert dialog.state == DialogState.OPEN_IDLE
        assert dialog.in_flight is False
        assert dialog._name_input.isEnabled() is True
        assert dialog._submit_btn.isEnabled() is True
        assert "sink" in dialog.last_feedback.lower() or "falha" in dialog.last_feedback.lower()

        # Retry
        dialog._on_submit()
        assert len(requests) == 2
        assert dialog.state == DialogState.DISPATCHING

    def test_report_builder_failure_stays_open(self, dialog):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog.report_builder_failure("builder falhou")
        assert dialog.isVisible()
        assert dialog.state == DialogState.OPEN_IDLE
        assert dialog.in_flight is False
        assert "builder" in dialog.last_feedback.lower()

    def test_feedback_never_contains_agente_criado(self, dialog):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog.report_dispatch_result(DispatchReport(accepted=("T1",)))
        assert "Agente criado" not in dialog.last_feedback
        assert "agente criado" not in dialog.last_feedback.lower()


# ── Keyboard / cancel ────────────────────────────────────────────────────────


class TestKeyboardAndCancel:
    def test_cancel_button_rejects_without_request(self, dialog, qtbot):
        requests: list = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(name="A", description="B")
        dialog._cancel_btn.click()
        assert dialog.state == DialogState.CANCELLED
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert requests == []

    def test_escape_cancels_in_open_idle(self, dialog, qtbot):
        dialog.set_fields(name="A", description="B")
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.state == DialogState.CANCELLED
        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_escape_blocked_during_dispatching(self, dialog, qtbot):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        assert dialog.state == DialogState.DISPATCHING
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.state == DialogState.DISPATCHING
        assert dialog.isVisible()
        # cancel button also blocked
        dialog._cancel_btn.click()
        assert dialog.state == DialogState.DISPATCHING

    def test_enter_in_description_does_not_submit(self, dialog, qtbot):
        requests: list = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(name="Agente", description="linha1")
        dialog._description_input.setFocus()
        qtbot.wait(10)
        # Type Enter — should insert newline, not submit
        qtbot.keyClick(dialog._description_input, Qt.Key.Key_Return)
        assert requests == []
        assert dialog.state == DialogState.OPEN_IDLE
        assert dialog.isVisible()
        # Description should still be editable with possible extra newline
        text = dialog.description_text()
        assert "linha1" in text


# ── Widget types ─────────────────────────────────────────────────────────────


class TestWidgetTypes:
    def test_name_is_line_edit(self, dialog):
        assert isinstance(dialog._name_input, QLineEdit)

    def test_description_is_plain_text_edit(self, dialog):
        assert isinstance(dialog._description_input, QPlainTextEdit)

    def test_error_label_hidden_initially(self, dialog):
        assert isinstance(dialog._error_label, QLabel)
        assert dialog._error_label.isVisible() is False

    def test_submit_is_push_button(self, dialog):
        assert isinstance(dialog._submit_btn, QPushButton)


# ── MCP / Brainstorm flags in snapshot ───────────────────────────────────────


class TestDestinationFlags:
    @pytest.mark.parametrize(
        "mcp,brainstorm",
        [
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ],
    )
    def test_flags_snapshotted(self, dialog, mcp, brainstorm):
        requests: list[CreateAgentRequest] = []
        dialog.submit_requested.connect(requests.append)
        dialog.set_fields(
            name="Agente",
            description="proposito",
            include_mcp=mcp,
            include_brainstorm=brainstorm,
        )
        dialog._on_submit()
        assert len(requests) == 1
        assert requests[0].include_mcp is mcp
        assert requests[0].include_brainstorm is brainstorm
        payload = json.loads(extract_request_json(requests[0].prompt))
        assert payload["destinations"]["mcp"] is mcp
        assert payload["destinations"]["brainstorm"] is brainstorm


# ── set_fields blocked while dispatching ─────────────────────────────────────


class TestInvariants:
    def test_set_fields_noop_while_dispatching(self, dialog):
        dialog.set_fields(name="A", description="B")
        dialog._on_submit()
        dialog.set_fields(name="HACKED", description="HACKED")
        assert dialog.name_text() == "A"
        assert dialog.description_text() == "B"
        assert dialog.last_request is not None
        assert dialog.last_request.name == "A"
