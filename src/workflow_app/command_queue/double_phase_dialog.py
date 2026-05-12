"""
DoublePhaseArgumentDialog — Modal de argumentos para pipelines com fase dupla.

Renderiza widgets dinamicos a partir do `argument-hint` de um comando.
Suporta 4 tipos de token:
  1. Input simples       — [placeholder] ou texto livre
  2. Radio com summary   — --opt1|--opt2|--opt3
  3. Checkbox            — [--flag] ou --flag
  4. Path .md custom     — [--key <path.md>]

Emite `submitted = Signal(str)` com a linha de comando montada.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class PathMdFieldWidget(QWidget):
    """Campo de path .md: QLineEdit + botao '...' que abre QFileDialog."""

    def __init__(
        self,
        default_md_dir: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._default_md_dir = default_md_dir
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._line = QLineEdit()
        self._line.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #52525B; border-radius: 4px;"
            " padding: 4px 8px; font-size: 12px; font-family: monospace;"
        )
        self._line.setPlaceholderText("caminho/para/arquivo.md")
        layout.addWidget(self._line, stretch=1)

        self._btn = QPushButton("...")
        self._btn.setFixedSize(28, 28)
        self._btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        self._btn.clicked.connect(self._browse)
        layout.addWidget(self._btn)

    def _browse(self) -> None:
        start_dir = self._default_md_dir
        if not start_dir or not Path(start_dir).exists():
            start_dir = str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar tasklist",
            start_dir,
            "Markdown (*.md)",
        )
        if path:
            self._line.setText(path)

    def text(self) -> str:
        return self._line.text().strip()

    def set_text(self, text: str) -> None:
        self._line.setText(text)


class RadioGroupWithSummary(QWidget):
    """Grupo de radio buttons + QLabel que atualiza on-toggled."""

    def __init__(
        self,
        options: list[str],
        summaries: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._summaries = summaries
        self._buttons: list[QRadioButton] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        for opt in self._options:
            rb = QRadioButton(opt)
            rb.setStyleSheet(
                "QRadioButton { color: #D4D4D8; font-size: 12px; spacing: 4px; }"
                "QRadioButton::indicator { width: 14px; height: 14px; }"
            )
            rb.toggled.connect(self._on_toggled)
            self._buttons.append(rb)
            btn_layout.addWidget(rb)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            "color: #A1A1AA; font-size: 11px; padding: 2px 4px;"
        )
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        if self._buttons:
            self._buttons[0].setChecked(True)
            self._update_summary(self._buttons[0].text())

    def _on_toggled(self, checked: bool) -> None:
        if checked:
            sender = self.sender()
            if isinstance(sender, QRadioButton):
                self._update_summary(sender.text())

    def _update_summary(self, opt: str) -> None:
        summary = self._summaries.get(opt, "")
        self._summary_label.setText(summary)
        self._summary_label.setVisible(bool(summary))

    def selected(self) -> str:
        for rb in self._buttons:
            if rb.isChecked():
                return rb.text()
        return ""


class _Token:
    """Representacao interna de um token do argument-hint."""

    def __init__(
        self,
        kind: str,
        label: str,
        options: list[str] | None = None,
        key: str = "",
    ) -> None:
        self.kind = kind  # "input" | "radio" | "checkbox" | "path_md"
        self.label = label
        self.options = options or []
        self.key = key


def _parse_argument_hint(hint: str) -> list[_Token]:
    """Parseia o argument-hint em tokens tipados.

    Regras:
      - Palavras entre colchetes [placeholder] -> input simples.
      - Palavras entre colchetes com --flag -> checkbox.
      - Palavras entre colchetes com <path.md> ou <path> -> path_md.
      - Tokens com pipe --a|--b|--c -> radio (fora de colchetes).
      - Texto livre fora de colchetes sem pipe -> input simples.
    """
    if not hint:
        return []

    tokens: list[_Token] = []
    # Regex que captura: [conteudo] ou palavras/pipes separadas por espaco
    # Usamos um tokenizador que respeita colchetes como unidade
    i = 0
    raw_parts: list[str] = []
    while i < len(hint):
        if hint[i].isspace():
            i += 1
            continue
        if hint[i] == "[":
            j = hint.find("]", i + 1)
            if j == -1:
                j = len(hint)
            raw_parts.append(hint[i : j + 1])
            i = j + 1
        else:
            j = i
            while j < len(hint) and not hint[j].isspace():
                j += 1
            raw_parts.append(hint[i:j])
            i = j

    for part in raw_parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        # Dentro de colchetes
        if part_stripped.startswith("[") and part_stripped.endswith("]"):
            inner = part_stripped[1:-1].strip()
            # Path .md custom: contem <path.md> ou <path>
            if "<path.md>" in inner or "<path>" in inner:
                # Extrai a chave, ex: --tasklist <path.md>
                key = inner.replace("<path.md>", "").replace("<path>", "").strip()
                tokens.append(_Token(kind="path_md", label=inner, key=key))
                continue
            # Checkbox: comeca com --
            if inner.startswith("--"):
                tokens.append(_Token(kind="checkbox", label=inner, key=inner))
                continue
            # Input simples
            tokens.append(_Token(kind="input", label=inner))
            continue

        # Radio com pipe (fora de colchetes)
        if "|" in part_stripped and part_stripped.startswith("--"):
            opts = [opt.strip() for opt in part_stripped.split("|") if opt.strip()]
            tokens.append(_Token(kind="radio", label=part_stripped, options=opts))
            continue

        # Checkbox fora de colchetes
        if part_stripped.startswith("--"):
            tokens.append(_Token(kind="checkbox", label=part_stripped, key=part_stripped))
            continue

        # Input simples (texto livre)
        tokens.append(_Token(kind="input", label=part_stripped))

    return tokens


class DoublePhaseArgumentDialog(QDialog):
    """Modal que renderiza widgets dinamicos a partir do argument-hint.

    Args:
        pipeline_name: Nome do comando (ex: '/daily-loop').
        argument_hint: String do argument-hint (frontmatter do .md).
        default_md_dir: Diretorio padrao para o QFileDialog de path .md.
        radio_summaries: Dict {opcao_radio: texto_resumo}.
        parent: Widget pai.
    """

    submitted = Signal(str)

    def __init__(
        self,
        pipeline_name: str,
        argument_hint: str,
        default_md_dir: str,
        radio_summaries: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline_name = pipeline_name
        self._argument_hint = argument_hint
        self._default_md_dir = default_md_dir
        self._radio_summaries = radio_summaries
        self._tokens = _parse_argument_hint(argument_hint)
        self._widgets: list[QWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Argumentos — {self._pipeline_name}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet("background-color: #18181B;")

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 16, 20, 16)

        # Titulo
        title = QLabel(f"{self._pipeline_name}")
        title.setStyleSheet(
            "color: #FAFAFA; font-size: 14px; font-weight: bold;"
        )
        main_layout.addWidget(title)

        # Subtitulo com hint bruto
        hint_label = QLabel(f"Hint: {self._argument_hint}")
        hint_label.setStyleSheet("color: #71717A; font-size: 10px; font-family: monospace;")
        hint_label.setWordWrap(True)
        main_layout.addWidget(hint_label)

        # Area scrollavel para o formulario
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(0, 0, 0, 0)

        if not self._tokens:
            empty = QLabel("Nenhum argumento necessario.")
            empty.setStyleSheet("color: #A1A1AA; font-size: 12px;")
            form_layout.addWidget(empty)
        else:
            for tok in self._tokens:
                row = self._build_token_row(tok)
                form_layout.addWidget(row)

        form_layout.addStretch()
        scroll.setWidget(form_container)
        main_layout.addWidget(scroll, stretch=1)

        # Botoes
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_confirm = QPushButton("Confirmar")
        btn_confirm.setFixedHeight(32)
        btn_confirm.setStyleSheet(
            "QPushButton { background-color: #166534; color: #FAFAFA;"
            "  border: none; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
        )
        btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_confirm)

        main_layout.addLayout(btn_row)

    def _build_token_row(self, token: _Token) -> QWidget:
        """Constroi uma linha do formulario para um token."""
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if token.kind == "input":
            label = QLabel(token.label)
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            edit = QLineEdit()
            edit.setStyleSheet(
                "background-color: #3F3F46; color: #FAFAFA;"
                " border: 1px solid #52525B; border-radius: 4px;"
                " padding: 4px 8px; font-size: 12px; font-family: monospace;"
            )
            edit.setPlaceholderText(token.label)
            layout.addWidget(edit)
            self._widgets.append(edit)

        elif token.kind == "checkbox":
            chk = QCheckBox(token.label)
            chk.setStyleSheet(
                "QCheckBox { color: #D4D4D8; font-size: 12px; spacing: 6px; }"
                "QCheckBox::indicator { width: 16px; height: 16px; }"
            )
            layout.addWidget(chk)
            self._widgets.append(chk)

        elif token.kind == "radio":
            label = QLabel("Opcao:")
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            rg = RadioGroupWithSummary(token.options, self._radio_summaries)
            layout.addWidget(rg)
            self._widgets.append(rg)

        elif token.kind == "path_md":
            label = QLabel(token.label)
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            pw = PathMdFieldWidget(self._default_md_dir)
            layout.addWidget(pw)
            self._widgets.append(pw)

        return row

    def _on_confirm(self) -> None:
        parts: list[str] = [self._pipeline_name]
        for i, tok in enumerate(self._tokens):
            widget = self._widgets[i]
            if tok.kind == "input":
                assert isinstance(widget, QLineEdit)
                val = widget.text().strip()
                if val:
                    parts.append(val)
            elif tok.kind == "checkbox":
                assert isinstance(widget, QCheckBox)
                if widget.isChecked():
                    parts.append(tok.key)
            elif tok.kind == "radio":
                assert isinstance(widget, RadioGroupWithSummary)
                sel = widget.selected()
                if sel:
                    parts.append(sel)
            elif tok.kind == "path_md":
                assert isinstance(widget, PathMdFieldWidget)
                val = widget.text()
                if val:
                    parts.append(f"{tok.key} {val}")

        command_line = " ".join(parts)
        self.submitted.emit(command_line)
        self.accept()
