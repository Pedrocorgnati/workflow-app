"""
DoublePhaseButton — Botão com comportamento de fase dupla.

- Com attachment no pill: executa generate_from_attachment() (fluxo atual).
- Sem attachment: abre DoublePhaseArgumentDialog para coletar argumentos.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QPushButton

from workflow_app.command_queue.double_phase_dialog import DoublePhaseArgumentDialog
from workflow_app.domain import FlagSpec


class DoublePhaseButton(QPushButton):
    """Botão que decide entre fluxo com anexo (pill) e modal de argumentos.

    Args:
        label: Texto do botão.
        pipeline_name: Nome do comando (ex: '/daily-loop').
        argument_hint: String do argument-hint (frontmatter do .md).
        default_md_dir: Diretório padrão para QFileDialog de path .md.
        radio_summaries: Dict {opcao_radio: texto_resumo}.
        flags_boolean: Lista de flags sem valor (novo modo estruturado).
        flags_with_value: Lista de FlagSpec com valor (novo modo estruturado).
        pill: Objeto com métodos ``has_attachment()`` e ``generate_from_attachment()``.
        on_command_ready: Callback chamado com a linha de comando montada.
        parent: Widget pai.
    """

    def __init__(
        self,
        label: str,
        pipeline_name: str,
        argument_hint: str = "",
        default_md_dir: str = "",
        radio_summaries: dict[str, str] | None = None,
        flags_boolean: list[str] | None = None,
        flags_with_value: list[FlagSpec] | None = None,
        fixed_flag: str | None = None,
        mode_radio: list[str] | None = None,
        mode_radio_flags: dict[str, str] | None = None,
        mode_radio_summaries: dict[str, str] | None = None,
        pill: object | None = None,
        on_command_ready: Callable[[str], None] | None = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(label, parent)
        self._pipeline_name = pipeline_name
        self._argument_hint = argument_hint
        self._default_md_dir = default_md_dir
        self._radio_summaries = dict(radio_summaries or {})
        self._flags_boolean = flags_boolean or []
        self._flags_with_value = flags_with_value or []
        self._fixed_flag = fixed_flag
        self._mode_radio = list(mode_radio or [])
        self._mode_radio_flags = dict(mode_radio_flags or {})
        self._mode_radio_summaries = dict(mode_radio_summaries or {})
        self._pill = pill
        self._on_command_ready = on_command_ready
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self) -> None:
        if self._pill is not None and self._pill.has_attachment():
            self._pill.generate_from_attachment()
            return
        dialog = DoublePhaseArgumentDialog(
            pipeline_name=self._pipeline_name,
            argument_hint=self._argument_hint,
            default_md_dir=self._default_md_dir,
            radio_summaries=self._radio_summaries,
            flags_boolean=self._flags_boolean,
            flags_with_value=self._flags_with_value,
            fixed_flag=self._fixed_flag,
            mode_radio=self._mode_radio,
            mode_radio_flags=self._mode_radio_flags,
            mode_radio_summaries=self._mode_radio_summaries,
            parent=self,
        )
        if self._on_command_ready is not None:
            dialog.submitted.connect(self._on_command_ready)
        dialog.exec()

    def set_radio_summaries(self, summaries: dict[str, str]) -> None:
        self._radio_summaries = dict(summaries)

    def set_default_md_dir(self, path: str) -> None:
        self._default_md_dir = path
