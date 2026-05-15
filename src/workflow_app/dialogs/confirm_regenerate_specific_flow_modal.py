"""
ConfirmRegenerateSpecificFlowModal — destructive confirmation for /build-module-pipeline --regenerate.

Triggered by `_on_dcp_build_pipeline_clicked` when the target module already
has a SPECIFIC-FLOW.json on disk and the canonical command would run with
`--regenerate`. Surfaces file metadata (mtime, command count) so the user can
spot manual edits about to be overwritten before the pipeline is enqueued.

The modal does NOT block the CLI — it only blocks enqueueing. The CLI itself
still writes a `.bak-{ISO_UTC}` next to the file before overwriting (see
`/build-module-pipeline` step 14).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


class ConfirmRegenerateSpecificFlowModal(QDialog):
    """Modal destructive confirmation for SPECIFIC-FLOW.json regeneration."""

    def __init__(
        self,
        flow_path: Path,
        command_count: int | None,
        cm_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DCP — Regenerar SPECIFIC-FLOW")
        self.setProperty("testid", "dialog-confirm-regenerate")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._setup_ui(flow_path, command_count, cm_id)

    def _setup_ui(
        self, flow_path: Path, command_count: int | None, cm_id: str
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        try:
            mtime = datetime.fromtimestamp(
                flow_path.stat().st_mtime, tz=timezone.utc
            ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            mtime = "?"

        count_str = (
            f"{command_count} comandos" if command_count is not None else "? comandos"
        )

        warning = QLabel(
            f"Modulo: <b>{cm_id}</b><br>"
            f"Arquivo: <code>{flow_path.name}</code> ({count_str}, mtime {mtime})<br><br>"
            "Esta acao vai colar <code>/build-module-pipeline --regenerate</code> no "
            "terminal, que <b>sobrescreve</b> o SPECIFIC-FLOW.json a partir do "
            "MODULE-META.json + canonical loop.<br><br>"
            "Se voce editou o SPECIFIC-FLOW.json manualmente "
            "(removeu comandos errados, ajustou ordem etc), <b>essa edicao sera perdida</b>. "
            "O CLI grava um backup <code>.bak-{ISO_UTC}</code> antes, mas a fila "
            "do app passara a refletir o novo arquivo gerado.<br><br>"
            "Para corrigir o pipeline de forma permanente, prefira editar "
            "<code>MODULE-META.json</code> (presence/deploy/qa/tdd) e regenerar."
        )
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.RichText)
        warning.setStyleSheet("color: #F4F4F5; font-size: 13px;")
        layout.addWidget(warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        yes_btn = buttons.button(QDialogButtonBox.StandardButton.Yes)
        yes_btn.setText("Regenerar (sobrescreve)")
        yes_btn.setProperty("testid", "confirm-regenerate-btn-confirm")
        yes_btn.setStyleSheet(
            "QPushButton { background-color: #7F1D1D; color: #FCA5A5;"
            "  border: 1px solid #991B1B; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #991B1B; }"
        )
        no_btn = buttons.button(QDialogButtonBox.StandardButton.No)
        no_btn.setText("Cancelar")
        no_btn.setProperty("testid", "confirm-regenerate-btn-cancel")
        no_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        no_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
