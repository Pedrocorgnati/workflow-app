"""
BookLegacyDialog — Modal para capturar os 5 inputs do pipeline /book-legacy.

Diferente dos demais botoes do CommandQueueWidget, o pipeline /book-legacy nao
le project.json (metrics-project-pill). O usuario informa aqui:
  1. path da pasta de imagens do livro escaneado (obrigatorio);
  2. nome do livro (obrigatorio);
  3. formato fisico da pagina (default 14x21cm);
  4. fonte tipografica (default EB Garamond);
  5. glossario versionado a aplicar (default glossario-base.json).

Esses 5 valores compoem o dict book_legacy_inputs consumido pelo builder
_enqueue_book_legacy, que expande a cadeia de subcomandos /book-legacy:* em
itens proprios da fila.

Decisao auq-interview rodada 3: SEM checkbox EPUB e SEM checkbox de revisao
humana forcada. Esses sao anti-padroes — EPUB nao esta no escopo do pipeline e
a revisao humana e CONDICIONAL (gate /book-legacy:review-orthographic decide
sozinho com base no diff guard, nao por toggle do operador).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

# Defaults canonicos (auq-interview rodada 3, source.md Parte 13).
DEFAULT_FORMAT = "14x21cm"
DEFAULT_FONT = "EB Garamond"
DEFAULT_GLOSSARY = "glossario-base.json"

# Opcoes oferecidas pelos combos. O primeiro valor de cada lista e o default.
FORMAT_OPTIONS = ["14x21cm", "16x23cm", "12x18cm", "A5"]
FONT_OPTIONS = ["EB Garamond", "Cardo", "Old Standard TT"]

_INPUT_STYLE = (
    "background-color: #3F3F46; color: #FAFAFA;"
    " border: 1px solid #52525B; border-radius: 4px;"
    " padding: 6px 10px; font-size: 13px; font-family: monospace;"
)


class BookLegacyDialog(QDialog):
    """Modal com 5 campos para os inputs do pipeline /book-legacy."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Book Legacy — Inputs do livro")
        self.setProperty("testid", "dialog-book-legacy")
        self.setModal(True)
        self.setFixedSize(580, 420)
        self._inputs: dict[str, str] = {}
        self._setup_ui()

    @property
    def book_legacy_inputs(self) -> dict[str, str]:
        """Dict book_legacy_inputs com os 5 valores normalizados do modal.

        Chaves: images_path, book_name, page_format, font, glossary.
        So fica populado apos o usuario confirmar (accept()).
        """
        return dict(self._inputs)

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #18181B;")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Pipeline /book-legacy — restauracao de livro escaneado")
        title.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Informe os dados do livro. Confirmar enfileira a cadeia completa "
            "de subcomandos /book-legacy:* (preparo + iteration + finalizacao)."
        )
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Campo 1 — path da pasta de imagens (obrigatorio).
        layout.addWidget(self._field_label("Pasta de imagens do livro escaneado *"))
        self._images_input = QLineEdit()
        self._images_input.setProperty("testid", "book-legacy-images-path-input")
        self._images_input.setPlaceholderText(
            "output/workspace/books/meu-livro/imagens"
        )
        self._images_input.setStyleSheet(_INPUT_STYLE)
        self._images_input.setFixedHeight(36)
        self._images_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._images_input)

        # Campo 2 — nome do livro (obrigatorio).
        layout.addWidget(self._field_label("Nome do livro *"))
        self._name_input = QLineEdit()
        self._name_input.setProperty("testid", "book-legacy-book-name-input")
        self._name_input.setPlaceholderText("Os Lusiadas")
        self._name_input.setStyleSheet(_INPUT_STYLE)
        self._name_input.setFixedHeight(36)
        self._name_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._name_input)

        # Campo 3 — formato (default 14x21cm).
        layout.addWidget(self._field_label("Formato da pagina"))
        self._format_combo = QComboBox()
        self._format_combo.setProperty("testid", "book-legacy-format-combo")
        self._format_combo.addItems(FORMAT_OPTIONS)
        self._format_combo.setCurrentText(DEFAULT_FORMAT)
        self._format_combo.setStyleSheet(_INPUT_STYLE)
        self._format_combo.setFixedHeight(36)
        layout.addWidget(self._format_combo)

        # Campo 4 — fonte (default EB Garamond).
        layout.addWidget(self._field_label("Fonte tipografica"))
        self._font_combo = QComboBox()
        self._font_combo.setProperty("testid", "book-legacy-font-combo")
        self._font_combo.addItems(FONT_OPTIONS)
        self._font_combo.setCurrentText(DEFAULT_FONT)
        self._font_combo.setStyleSheet(_INPUT_STYLE)
        self._font_combo.setFixedHeight(36)
        layout.addWidget(self._font_combo)

        # Campo 5 — glossario (default glossario-base.json).
        layout.addWidget(self._field_label("Glossario versionado"))
        self._glossary_input = QLineEdit()
        self._glossary_input.setProperty("testid", "book-legacy-glossary-input")
        self._glossary_input.setText(DEFAULT_GLOSSARY)
        self._glossary_input.setPlaceholderText(DEFAULT_GLOSSARY)
        self._glossary_input.setStyleSheet(_INPUT_STYLE)
        self._glossary_input.setFixedHeight(36)
        layout.addWidget(self._glossary_input)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #F87171; font-size: 10px;")
        self._error_label.setFixedHeight(14)
        layout.addWidget(self._error_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setProperty("testid", "book-legacy-cancel")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self._btn_confirm = QPushButton("Enfileirar")
        self._btn_confirm.setProperty("testid", "book-legacy-submit")
        self._btn_confirm.setFixedHeight(32)
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.setStyleSheet(
            "QPushButton { background-color: #166534; color: #FAFAFA;"
            "  border: none; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #52525B; }"
        )
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._btn_confirm)

        layout.addLayout(btn_row)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        """Label de campo padronizado (asterisco indica obrigatorio)."""
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
        return lbl

    # ── Validacao ── #

    def _validate(self) -> tuple[bool, str]:
        """Retorna (is_valid, error_msg).

        Obrigatorios: pasta de imagens e nome do livro. O path da pasta nao
        pode ter basename traversal-equivalente (`.`/`..`).
        """
        images = self._images_input.text().strip().rstrip("/")
        name = self._name_input.text().strip()
        if not images:
            return (False, "")
        if not name:
            return (False, "")
        try:
            p = Path(images).expanduser()
        except (OSError, RuntimeError):
            return (False, "Path da pasta de imagens invalido.")
        basename = p.name
        if not basename or basename in {".", ".."}:
            return (False, "Basename invalido na pasta de imagens.")
        return (True, "")

    def _on_text_changed(self, _text: str = "") -> None:
        is_valid, err = self._validate()
        self._btn_confirm.setEnabled(is_valid)
        self._error_label.setText(err)

    def _on_confirm(self) -> None:
        if not self._btn_confirm.isEnabled():
            return
        is_valid, _err = self._validate()
        if not is_valid:
            return
        raw_images = self._images_input.text().strip().rstrip("/")
        self._inputs = {
            "images_path": str(Path(raw_images).expanduser()),
            "book_name": self._name_input.text().strip(),
            "page_format": self._format_combo.currentText().strip() or DEFAULT_FORMAT,
            "font": self._font_combo.currentText().strip() or DEFAULT_FONT,
            "glossary": self._glossary_input.text().strip() or DEFAULT_GLOSSARY,
        }
        self.accept()
