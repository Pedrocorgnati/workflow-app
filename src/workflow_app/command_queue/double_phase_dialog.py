"""
DoublePhaseArgumentDialog - Modal de argumentos para pipelines com fase dupla.

Renderiza widgets dinamicos a partir do `argument-hint` de um comando
(legado) ou a partir de `flags_boolean` + `flags_with_value` (novo formato
estruturado a partir do CommandSpec).

Suporta 6 tipos de token no modo legado:
  1. Input simples       - [placeholder] curto sem `<...>`
  2. Radio com summary   - --opt1|--opt2|--opt3 (fora de colchetes)
  3. Checkbox            - [--flag] ou --flag
  4. Path .md custom     - [--key <path.md>]
  5. Enum flag (mutex)   - [--simple|--deep|--heavy] (com QButtonGroup exclusivo)
  6. Freetext auto-grow  - "<duvida>", <descricao> (QTextEdit com clamp 32-240px)

Modo estruturado (novo):
  - Input principal multiline (QPlainTextEdit) para path.md ou prompt.
  - Row unico de QCheckBox (QHBoxLayout, setSpacing(5)) para todas as flags.
  - Inputs condicionais (QLineEdit) para flags_with_value via setVisible.
  - Sizing dinamico via adjustSize() + setMinimumSize(self.sizeHint()).

Emite `submitted = Signal(str)` com a linha de comando montada.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import FlagSpec

# Auto-grow clamps para tokens freetext (AC-2.3).
FREETEXT_MIN_HEIGHT = 32
FREETEXT_MAX_HEIGHT = 240

# Slug canonico para `--name`: kebab-case minusculo, 1-50 chars, comeca com [a-z0-9].
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")

SelectedMdPathGetter = Callable[[], str | None]


def _selected_brainstorm_md_path(
    getter: SelectedMdPathGetter | None,
) -> str:
    if getter is None:
        return ""
    try:
        return (getter() or "").strip()
    except Exception:
        return ""


def _emit_missing_brainstorm_md_toast() -> None:
    try:
        from workflow_app.signal_bus import signal_bus

        signal_bus.toast_requested.emit(
            "Nenhum .md selecionado em brainstorm-md-picker-row.", "warning"
        )
    except Exception:
        pass


def _find_repo_root() -> Path:
    """Resolve a raiz do SystemForge para ancorar atalhos locais."""
    starts = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    for start in starts:
        cur = start
        while cur != cur.parent:
            if (cur / "brainstorm").is_dir():
                return cur
            if (cur / "ai-forge" / "workflow-app").is_dir():
                return cur
            cur = cur.parent
    return Path.cwd()


def _markdown_picker_start_dir(default_md_dir: str = "") -> str:
    """Brainstorm e apenas atalho inicial; o dialog permite navegar livremente."""
    repo_root = _find_repo_root()
    # `brainstorm` foi realocado para `blacksmith/brainstorm` na reorganizacao
    # do repo; mantemos o top-level legado por compat (mesmo padrao de
    # PromptsConfigDialog._prompt_md_start_dir em main_window.py).
    for brainstorm in (repo_root / "brainstorm", repo_root / "blacksmith" / "brainstorm"):
        if brainstorm.is_dir():
            return str(brainstorm)

    from workflow_app.config.app_state import app_state

    base_dir = Path.cwd()
    if app_state.has_config and app_state.config is not None:
        base_dir = app_state.config.project_dir

    candidate = Path(default_md_dir) if default_md_dir else None
    if candidate is not None and not candidate.is_absolute():
        candidate = base_dir / candidate
    if candidate is not None and candidate.exists():
        return str(candidate)
    return str(base_dir if base_dir.exists() else Path.cwd())


def _browse_markdown_file(parent: QWidget, default_md_dir: str = "") -> str:
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "Selecionar arquivo .md",
        _markdown_picker_start_dir(default_md_dir),
        "Markdown (*.md);;All Files (*)",
    )
    return path or ""


def _flag_spec_is_path_md(flag_spec: FlagSpec) -> bool:
    placeholder = (flag_spec.placeholder or "").lower()
    return ".md" in placeholder or "<path.md>" in placeholder


class PathMdFieldWidget(QWidget):
    """Campo de path .md: QLineEdit + botao de lupa que abre QFileDialog."""

    def __init__(
        self,
        default_md_dir: str,
        selected_md_path_getter: SelectedMdPathGetter | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._default_md_dir = default_md_dir
        self._selected_md_path_getter = selected_md_path_getter
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
        self._line.setProperty("testid", "double-phase-path-md-input")
        layout.addWidget(self._line, stretch=1)

        self._btn = QPushButton("🔍")
        self._btn.setProperty("testid", "double-phase-path-md-browse")
        self._btn.setToolTip("Selecionar arquivo .md")
        self._btn.setFixedSize(28, 28)
        self._btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        self._btn.clicked.connect(self._browse)
        layout.addWidget(self._btn)

        if self._selected_md_path_getter is not None:
            self._brainstorm_btn = QPushButton("🧠")
            self._brainstorm_btn.setProperty(
                "testid", "double-phase-path-md-brainstorm"
            )
            self._brainstorm_btn.setToolTip(
                "Usar .md selecionado em brainstorm-md-picker-row"
            )
            self._brainstorm_btn.setFixedSize(28, 28)
            self._brainstorm_btn.setStyleSheet(
                "QPushButton { background-color: #3F3F46; color: #FBBF24;"
                "  border: 1px solid #52525B; border-radius: 4px;"
                "  font-size: 13px; font-weight: 700; }"
                "QPushButton:hover { background-color: #52525B; color: #FDE68A; }"
            )
            self._brainstorm_btn.clicked.connect(self._paste_brainstorm_md)
            layout.addWidget(self._brainstorm_btn)

    def _browse(self) -> None:
        path = _browse_markdown_file(self, self._default_md_dir)
        if path:
            self._line.setText(path)

    def _paste_brainstorm_md(self) -> None:
        path = _selected_brainstorm_md_path(self._selected_md_path_getter)
        if not path:
            _emit_missing_brainstorm_md_toast()
            return
        self._line.setText(path)
        self._line.setFocus()

    def text(self) -> str:
        return self._line.text().strip()

    def set_text(self, text: str) -> None:
        self._line.setText(text)

    @property
    def line_edit(self) -> QLineEdit:
        return self._line


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

        # QButtonGroup exclusivo garante mutex mesmo se os radios forem
        # reparented para layouts diferentes (AC-2.1, AC-2.2).
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        for idx, opt in enumerate(self._options):
            rb = QRadioButton(opt)
            rb.setStyleSheet(
                "QRadioButton { color: #D4D4D8; font-size: 12px; spacing: 4px; }"
                "QRadioButton::indicator { width: 14px; height: 14px; }"
            )
            rb.toggled.connect(self._on_toggled)
            self._buttons.append(rb)
            self._button_group.addButton(rb, idx)
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

    def button_group(self) -> QButtonGroup:
        """Acesso ao QButtonGroup interno (uso em testes de mutex)."""
        return self._button_group


class AutoGrowTextEdit(QTextEdit):
    """QTextEdit com altura dinamica clampada entre MIN e MAX (AC-2.3).

    Conecta `document().contentsChanged` para recalcular a altura conforme
    o conteudo cresce. Limites em pixels:
      - MIN_HEIGHT = 32 (1 linha + padding)
      - MAX_HEIGHT = 240 (~10 linhas; passa para scroll vertical depois)
    """

    MIN_HEIGHT = FREETEXT_MIN_HEIGHT
    MAX_HEIGHT = FREETEXT_MAX_HEIGHT

    def __init__(
        self,
        placeholder: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DoublePhaseFreetext")
        self.setPlaceholderText(placeholder)
        self.setAcceptRichText(False)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QTextEdit#DoublePhaseFreetext {"
            " background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #52525B; border-radius: 4px;"
            " padding: 4px 8px; font-size: 12px; font-family: monospace; }"
            "QTextEdit#DoublePhaseFreetext:focus {"
            " border: 1px solid #FBBF24; }"
        )
        self.setFixedHeight(self.MIN_HEIGHT)
        # Recalcula no proximo loop de eventos: document().size() so eh
        # confiavel apos layout do widget.
        self.document().contentsChanged.connect(self._on_contents_changed)

    def _on_contents_changed(self) -> None:
        doc_height = self.document().size().height()
        # Margens do frame (border + padding) somam ~8px verticalmente.
        target = int(doc_height) + 8
        clamped = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, target))
        if clamped != self.height():
            self.setFixedHeight(clamped)


class _Token:
    """Representacao interna de um token do argument-hint."""

    def __init__(
        self,
        kind: str,
        label: str,
        options: list[str] | None = None,
        key: str = "",
    ) -> None:
        # "input" | "radio" | "checkbox" | "checkbox_with_value" |
        # "checkbox_with_path_md" | "path_md" | "enum_flag" | "freetext"
        self.kind = kind
        self.label = label
        self.options = options or []
        self.key = key


# Token freetext: identifica `<word>` (com ou sem aspas envolventes).
# Exemplos cobertos: `<duvida>`, `"<duvida>"`, `<descricao>`.
_FREETEXT_RE = re.compile(r'^"?\s*<[A-Za-z_][A-Za-z0-9_-]*>\s*"?$')

# Token checkbox_with_value: `[--flag <placeholder>]` com placeholder != <path>/<path.md>.
# Exemplo coberto: `[--name <slug>]` -> grupo 1="--name", grupo 2="slug".
_CHECKBOX_WITH_VALUE_RE = re.compile(r"^(--[\w-]+)\s+<([A-Za-z_][A-Za-z0-9_-]*)>$")


def _parse_argument_hint(hint: str) -> list[_Token]:
    """Parseia o argument-hint em tokens tipados.

    Regras (ordem importa - colchetes sao avaliados primeiro):
      - [conteudo com `|` e `--`] -> enum_flag (radio mutex em QButtonGroup).
      - [--flag <path.md>] / [--flag <path>] -> path_md.
      - [--flag] -> checkbox.
      - [placeholder simples] -> input simples.
      - --a|--b|--c (fora de colchetes) -> radio.
      - --flag (fora de colchetes) -> checkbox.
      - "<word>" / <word> -> freetext (auto-grow QTextEdit).
      - Qualquer outro texto livre -> input simples.
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
            # Enum flag: [--a|--b|--c] (mutex). Avaliado ANTES de checkbox
            # para corrigir o bug do queue-btn-study (AC-2.1).
            if "|" in inner and inner.startswith("--"):
                opts = [opt.strip() for opt in inner.split("|") if opt.strip()]
                tokens.append(
                    _Token(kind="enum_flag", label=inner, options=opts)
                )
                continue
            # Checkbox + path picker: [--flag <path.md>] / [--flag <path>] com -- prefix.
            # Avaliado ANTES de path_md para que tokens com -- prefix sejam opt-in
            # via checkbox; tokens sem -- continuam caindo em path_md (retrocompat).
            if inner.startswith("--") and (
                "<path.md>" in inner or "<path>" in inner
            ):
                flag_name = inner.split()[0]
                tokens.append(
                    _Token(
                        kind="checkbox_with_path_md",
                        label=inner,
                        key=flag_name,
                    )
                )
                continue
            # Path .md custom: contem <path.md> ou <path>
            if "<path.md>" in inner or "<path>" in inner:
                # Extrai a chave, ex: --tasklist <path.md>
                key = inner.replace("<path.md>", "").replace("<path>", "").strip()
                tokens.append(_Token(kind="path_md", label=inner, key=key))
                continue
            # Checkbox com valor: [--flag <placeholder>] com placeholder != <path>/<path.md>
            m_cbv = _CHECKBOX_WITH_VALUE_RE.match(inner)
            if m_cbv and inner.startswith("--"):
                flag_name = m_cbv.group(1)
                placeholder = m_cbv.group(2)
                tokens.append(
                    _Token(
                        kind="checkbox_with_value",
                        label=inner,
                        key=flag_name,
                        options=[placeholder],
                    )
                )
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

        # Freetext: "<word>" ou <word> (texto livre prosaico, ex: "<duvida>").
        if _FREETEXT_RE.match(part_stripped):
            tokens.append(_Token(kind="freetext", label=part_stripped))
            continue

        # Input simples (texto livre curto)
        tokens.append(_Token(kind="input", label=part_stripped))

    return tokens


class DoublePhaseArgumentDialog(QDialog):
    """Modal que renderiza widgets dinamicos a partir do argument-hint
    (legado) ou de flags_boolean + flags_with_value (estruturado).

    Args:
        pipeline_name: Nome do comando (ex: '/daily-loop').
        argument_hint: String do argument-hint (frontmatter do .md).
        default_md_dir: Diretorio padrao para o QFileDialog de path .md.
        radio_summaries: Dict {opcao_radio: texto_resumo}.
        flags_boolean: Lista de flags sem valor (novo modo estruturado).
        flags_with_value: Lista de FlagSpec com valor (novo modo estruturado).
        fixed_flag: Flag injetada automaticamente sem checkbox (ex: 'cmd-single').
            Quando definida, o modal exibe apenas o input principal e monta
            '{pipeline_name} --{fixed_flag} {main_text}' no confirm.
        parent: Widget pai.
    """

    submitted = Signal(str)

    def __init__(
        self,
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
        selected_md_path_getter: SelectedMdPathGetter | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline_name = pipeline_name
        self._argument_hint = argument_hint
        self._default_md_dir = default_md_dir
        self._radio_summaries = radio_summaries or {}
        self._flags_boolean = flags_boolean or []
        self._flags_with_value = flags_with_value or []
        self._fixed_flag = fixed_flag
        # Radio de modo opcional, renderizado abaixo do input principal no
        # modo estruturado (ex: cmd-single -> "kimi analyse" | "kimi certain").
        # `mode_radio_flags` mapeia label -> flag a anexar no comando final
        # (string vazia = nenhum flag extra; ex: {"kimi certain": "--certain"}).
        self._mode_radio_options = list(mode_radio or [])
        self._mode_radio_flags = dict(mode_radio_flags or {})
        self._mode_radio_summaries = dict(mode_radio_summaries or {})
        self._mode_radio_widget: RadioGroupWithSummary | None = None
        self._selected_md_path_getter = selected_md_path_getter
        self._structured_mode = bool(self._flags_boolean or self._flags_with_value or self._fixed_flag)
        self._tokens: list[_Token] = []
        self._widgets: list[QWidget] = []
        self._error_labels: dict[int, QLabel] = {}
        self._flag_error_labels: dict[str, QLabel] = {}
        self._btn_confirm: QPushButton | None = None
        if not self._structured_mode:
            self._tokens = _parse_argument_hint(argument_hint)
        self._setup_ui()
        # Sincroniza estado inicial do botao Confirmar (sem checkboxes marcados,
        # nao gera erros e botao fica habilitado - preserva fluxo simples).
        self._on_validate_changed()

    def _setup_ui(self) -> None:
        self.setObjectName("DoublePhaseArgumentDialog")
        self.setWindowTitle(f"Argumentos - {self._pipeline_name}")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog#DoublePhaseArgumentDialog { background-color: #18181B; }"
        )

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 16, 20, 16)

        if self._structured_mode:
            self._setup_ui_structured(main_layout)
        else:
            self._setup_ui_legacy(main_layout)

        self.adjustSize()
        self.setMinimumSize(self.sizeHint())
        self.setMinimumHeight(self.sizeHint().height() + 100)
        self._setup_tab_order()

    def _setup_ui_legacy(self, main_layout: QVBoxLayout) -> None:
        """Layout legado baseado em argument_hint / tokens."""
        # Subtitulo com hint bruto
        hint_label = QLabel(f"Hint: {self._argument_hint}")
        hint_label.setStyleSheet(
            "color: #71717A; font-size: 10px; font-family: monospace;"
        )
        hint_label.setWordWrap(True)
        main_layout.addWidget(hint_label)

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
            for i, tok in enumerate(self._tokens):
                row = self._build_token_row(tok, i)
                form_layout.addWidget(row)

        form_layout.addStretch()
        scroll.setWidget(form_container)
        main_layout.addWidget(scroll, stretch=1)
        self._build_buttons(main_layout)

    def _setup_ui_structured(self, main_layout: QVBoxLayout) -> None:
        """Layout estruturado: input multiline + row de checkboxes + inputs condicionais."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(0, 0, 0, 0)

        # Bloco superior: input principal multiline
        if self._fixed_flag:
            main_label = QLabel(f"path.md  (--{self._fixed_flag})")
            placeholder = "caminho/para/arquivo.md"
        else:
            main_label = QLabel("path.md ou prompt")
            placeholder = "caminho/para/arquivo.md ou descricao da task"
        main_label.setStyleSheet(
            "color: #D4D4D8; font-size: 11px; font-weight: 600;"
        )
        form_layout.addWidget(main_label)

        self._main_input = QPlainTextEdit()
        self._main_input.setPlaceholderText(placeholder)
        self._main_input.setStyleSheet(
            "QPlainTextEdit { background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #52525B; border-radius: 4px;"
            " padding: 4px 8px; font-size: 12px; font-family: monospace; }"
            "QPlainTextEdit:focus { border: 1px solid #FBBF24; }"
        )
        font_metrics = self._main_input.fontMetrics()
        line_height = font_metrics.lineSpacing()
        self._main_input.setFixedHeight(line_height * 4 + 8)

        main_input_row = QWidget()
        main_input_layout = QHBoxLayout(main_input_row)
        main_input_layout.setContentsMargins(0, 0, 0, 0)
        main_input_layout.setSpacing(6)
        main_input_layout.addWidget(self._main_input, stretch=1)

        self._main_md_btn = QPushButton("🔍")
        self._main_md_btn.setProperty("testid", "double-phase-main-md-browse")
        self._main_md_btn.setToolTip("Selecionar arquivo .md")
        self._main_md_btn.setFixedSize(32, 32)
        self._main_md_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        self._main_md_btn.clicked.connect(self._browse_main_markdown)
        main_input_layout.addWidget(
            self._main_md_btn,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        if self._selected_md_path_getter is not None:
            self._main_brainstorm_md_btn = QPushButton("🧠")
            self._main_brainstorm_md_btn.setProperty(
                "testid", "double-phase-main-md-brainstorm"
            )
            self._main_brainstorm_md_btn.setToolTip(
                "Usar .md selecionado em brainstorm-md-picker-row"
            )
            self._main_brainstorm_md_btn.setFixedSize(32, 32)
            self._main_brainstorm_md_btn.setStyleSheet(
                "QPushButton { background-color: #3F3F46; color: #FBBF24;"
                "  border: 1px solid #52525B; border-radius: 4px;"
                "  font-size: 15px; font-weight: 700; }"
                "QPushButton:hover { background-color: #52525B; color: #FDE68A; }"
            )
            self._main_brainstorm_md_btn.clicked.connect(
                self._paste_main_brainstorm_markdown
            )
            main_input_layout.addWidget(
                self._main_brainstorm_md_btn,
                alignment=Qt.AlignmentFlag.AlignTop,
            )
        form_layout.addWidget(main_input_row)

        # Radio de modo (opcional), imediatamente abaixo do input principal.
        # Usado pelo cmd-single para escolher "kimi analyse" vs "kimi certain".
        if self._mode_radio_options:
            mode_label = QLabel("Modo:")
            mode_label.setStyleSheet(
                "color: #D4D4D8; font-size: 11px; font-weight: 600;"
            )
            form_layout.addWidget(mode_label)
            self._mode_radio_widget = RadioGroupWithSummary(
                self._mode_radio_options, self._mode_radio_summaries
            )
            self._mode_radio_widget.setProperty(
                "testid", "double-phase-mode-radio"
            )
            form_layout.addWidget(self._mode_radio_widget)

        # Bloco do meio: row unico de checkboxes (omitido quando fixed_flag esta definido)
        all_flags = self._flags_boolean + [f.name for f in self._flags_with_value]
        if all_flags and not self._fixed_flag:
            flags_row = QWidget()
            flags_layout = QHBoxLayout(flags_row)
            flags_layout.setContentsMargins(0, 0, 0, 0)
            flags_layout.setSpacing(5)

            self._flag_checkboxes: dict[str, QCheckBox] = {}
            for flag in all_flags:
                chk = QCheckBox(f"--{flag}")
                chk.setStyleSheet(
                    "QCheckBox { color: #D4D4D8; font-size: 12px; spacing: 6px; }"
                    "QCheckBox::indicator { width: 16px; height: 16px; }"
                )
                flags_layout.addWidget(chk)
                self._flag_checkboxes[flag] = chk

            flags_layout.addStretch()
            form_layout.addWidget(flags_row)

            # Bloco condicional: inputs para flags_with_value
            self._flag_inputs: dict[str, tuple[QWidget, QWidget]] = {}
            for flag_spec in self._flags_with_value:
                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.setSpacing(6)

                flag_label = QLabel(f"--{flag_spec.name}")
                flag_label.setStyleSheet(
                    "color: #A1A1AA; font-size: 11px; font-weight: 600;"
                )
                container_layout.addWidget(flag_label)

                if _flag_spec_is_path_md(flag_spec):
                    edit = PathMdFieldWidget(
                        self._default_md_dir,
                        selected_md_path_getter=self._selected_md_path_getter,
                    )
                    edit.line_edit.setPlaceholderText(
                        flag_spec.placeholder or f"valor para --{flag_spec.name}"
                    )
                else:
                    edit = QLineEdit()
                    edit.setPlaceholderText(flag_spec.placeholder or f"valor para --{flag_spec.name}")
                    edit.setStyleSheet(
                        "background-color: #3F3F46; color: #FAFAFA;"
                        " border: 1px solid #52525B; border-radius: 4px;"
                        " padding: 4px 8px; font-size: 12px; font-family: monospace;"
                    )
                container_layout.addWidget(edit, stretch=1)

                container.setVisible(False)
                form_layout.addWidget(container)
                self._flag_inputs[flag_spec.name] = (container, edit)

                # Conectar checkbox para mostrar/ocultar input
                chk = self._flag_checkboxes.get(flag_spec.name)
                if chk is not None:
                    chk.toggled.connect(container.setVisible)

                # Lane de validacao (task-022): label de erro inline para
                # flags com regras (--name kebab-case, --loop path .md).
                if flag_spec.name in ("name", "loop"):
                    err = QLabel("")
                    err.setStyleSheet(
                        "color: #DC2626; font-size: 11px; padding: 2px 0 0 0;"
                    )
                    err.setVisible(False)
                    form_layout.addWidget(err)
                    self._flag_error_labels[flag_spec.name] = err
                    if isinstance(edit, PathMdFieldWidget):
                        edit.line_edit.textChanged.connect(self._on_validate_changed)
                    else:
                        edit.textChanged.connect(self._on_validate_changed)
                    if chk is not None:
                        chk.toggled.connect(lambda _c: self._on_validate_changed())

        form_layout.addStretch()
        scroll.setWidget(form_container)
        main_layout.addWidget(scroll, stretch=1)
        self._build_buttons(main_layout)

    def _browse_main_markdown(self) -> None:
        path = _browse_markdown_file(self, self._default_md_dir)
        if path:
            self._main_input.setPlainText(path)

    def _paste_main_brainstorm_markdown(self) -> None:
        path = _selected_brainstorm_md_path(self._selected_md_path_getter)
        if not path:
            _emit_missing_brainstorm_md_toast()
            return
        self._main_input.setPlainText(path)
        self._main_input.setFocus()

    @staticmethod
    def _input_widget_text(widget: QWidget) -> str:
        if isinstance(widget, PathMdFieldWidget):
            return widget.text()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return ""

    @staticmethod
    def _quote_if_needed(value: str) -> str:
        return f'"{value}"' if any(c in value for c in (" ", "\t")) else value

    def _build_buttons(self, main_layout: QVBoxLayout) -> None:
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
        self._btn_confirm = btn_confirm
        btn_row.addWidget(btn_confirm)

        main_layout.addLayout(btn_row)

    def _setup_tab_order(self) -> None:
        """Configura tab order coerente entre widgets do dialog."""
        from PySide6.QtWidgets import QWidget
        widgets: list[QWidget] = []

        if self._structured_mode and hasattr(self, "_main_input"):
            widgets.append(self._main_input)
            for flag in self._flags_boolean:
                chk = self._flag_checkboxes.get(flag)
                if chk is not None:
                    widgets.append(chk)
            for flag_spec in self._flags_with_value:
                chk = self._flag_checkboxes.get(flag_spec.name)
                if chk is not None:
                    widgets.append(chk)
                container, edit = self._flag_inputs.get(flag_spec.name, (None, None))
                if container is not None and container.isVisible():
                    if isinstance(edit, PathMdFieldWidget):
                        widgets.append(edit.line_edit)
                    else:
                        widgets.append(edit)
        else:
            # Modo legacy: _widgets contem QWidget OU tuple (chk, edit/pw) para
            # checkbox_with_value e checkbox_with_path_md. Desempacotar tuplas
            # para preservar ordem chk -> edit; quando o sub-widget e um
            # PathMdFieldWidget (container), usar o line_edit interno como
            # destino do tab focus.
            for w in self._widgets:
                if isinstance(w, tuple):
                    for sub in w:
                        if isinstance(sub, PathMdFieldWidget):
                            widgets.append(sub.line_edit)
                        else:
                            widgets.append(sub)
                else:
                    widgets.append(w)

        if len(widgets) < 2:
            return

        for i in range(len(widgets) - 1):
            self.setTabOrder(widgets[i], widgets[i + 1])

    def _build_token_row(self, token: _Token, index: int = 0) -> QWidget:
        """Constroi uma linha do formulario para um token.

        `index` e a posicao do token em `self._tokens` (usado para indexar
        `_error_labels` quando o kind admite validacao inline).
        """
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if token.kind == "input":
            label = QLabel(token.label)
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            if ".md" in token.label.lower():
                edit = PathMdFieldWidget(
                    self._default_md_dir,
                    selected_md_path_getter=self._selected_md_path_getter,
                )
                edit.line_edit.setPlaceholderText(token.label)
            else:
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

        elif token.kind == "checkbox_with_value":
            # Checkbox + QLineEdit adjacente; input oculto ate o checkbox ser marcado.
            chk = QCheckBox(token.label)
            chk.setStyleSheet(
                "QCheckBox { color: #D4D4D8; font-size: 12px; spacing: 6px; }"
                "QCheckBox::indicator { width: 16px; height: 16px; }"
            )
            layout.addWidget(chk)

            edit = QLineEdit()
            placeholder = token.options[0] if token.options else "valor"
            edit.setPlaceholderText(f"<{placeholder}>")
            edit.setStyleSheet(
                "background-color: #3F3F46; color: #FAFAFA;"
                " border: 1px solid #52525B; border-radius: 4px;"
                " padding: 4px 8px; font-size: 12px; font-family: monospace;"
            )
            edit.setVisible(False)
            layout.addWidget(edit)

            def _on_toggle(checked: bool, e: QLineEdit = edit) -> None:
                e.setVisible(checked)
                if checked:
                    e.setFocus()

            chk.toggled.connect(_on_toggle)
            self._widgets.append((chk, edit))

            # Lane de validacao (task-022): label de erro inline para --name.
            err = QLabel("")
            err.setStyleSheet(
                "color: #DC2626; font-size: 11px; padding: 2px 0 0 0;"
            )
            err.setVisible(False)
            layout.addWidget(err)
            self._error_labels[index] = err
            edit.textChanged.connect(self._on_validate_changed)
            chk.toggled.connect(lambda _c: self._on_validate_changed())

        elif token.kind == "checkbox_with_path_md":
            # Checkbox + PathMdFieldWidget adjacente; picker oculto ate marcar.
            chk = QCheckBox(token.label)
            chk.setStyleSheet(
                "QCheckBox { color: #D4D4D8; font-size: 12px; spacing: 6px; }"
                "QCheckBox::indicator { width: 16px; height: 16px; }"
            )
            layout.addWidget(chk)

            pw = PathMdFieldWidget(
                self._default_md_dir,
                selected_md_path_getter=self._selected_md_path_getter,
            )
            pw.setVisible(False)
            layout.addWidget(pw)

            def _on_toggle_path(checked: bool, p: PathMdFieldWidget = pw) -> None:
                p.setVisible(checked)
                if checked:
                    p.line_edit.setFocus()

            chk.toggled.connect(_on_toggle_path)
            self._widgets.append((chk, pw))

            # Lane de validacao (task-022): label de erro inline para --loop.
            err = QLabel("")
            err.setStyleSheet(
                "color: #DC2626; font-size: 11px; padding: 2px 0 0 0;"
            )
            err.setVisible(False)
            layout.addWidget(err)
            self._error_labels[index] = err
            pw.line_edit.textChanged.connect(self._on_validate_changed)
            chk.toggled.connect(lambda _c: self._on_validate_changed())

        elif token.kind == "radio":
            label = QLabel("Opcao:")
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            rg = RadioGroupWithSummary(token.options, self._radio_summaries)
            layout.addWidget(rg)
            self._widgets.append(rg)

        elif token.kind == "enum_flag":
            label = QLabel("Modo (escolha um):")
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            rg = RadioGroupWithSummary(token.options, self._radio_summaries)
            rg.setObjectName("DoublePhaseEnumFlag")
            layout.addWidget(rg)
            self._widgets.append(rg)

        elif token.kind == "freetext":
            label = QLabel(token.label)
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            te = AutoGrowTextEdit(placeholder=token.label)
            layout.addWidget(te)
            self._widgets.append(te)

        elif token.kind == "path_md":
            label = QLabel(token.label)
            label.setStyleSheet("color: #D4D4D8; font-size: 11px; font-weight: 600;")
            layout.addWidget(label)

            pw = PathMdFieldWidget(
                self._default_md_dir,
                selected_md_path_getter=self._selected_md_path_getter,
            )
            layout.addWidget(pw)
            self._widgets.append(pw)

        return row

    def _validate_tokens(self) -> list[tuple[int, str]]:
        """Retorna lista (token_index, error_message) para tokens invalidos.

        Validacao limitada a (a) `checkbox_with_value` com key `--name`
        (slug regex SLUG_RE quando marcado) e (b) `checkbox_with_path_md`
        com key `--loop` (path .md obrigatorio quando marcado). Demais
        tokens nao sao validados (preserva comportamento existente).
        """
        errors: list[tuple[int, str]] = []
        for i, tok in enumerate(self._tokens):
            if i >= len(self._widgets):
                continue
            widget = self._widgets[i]
            if tok.kind == "checkbox_with_value" and tok.key == "--name":
                if not (isinstance(widget, tuple) and len(widget) == 2):
                    continue
                chk, edit = widget
                if isinstance(chk, QCheckBox) and chk.isChecked():
                    val = edit.text().strip() if isinstance(edit, QLineEdit) else ""
                    if not val or not SLUG_RE.match(val):
                        errors.append(
                            (i, "slug exigido: kebab-case minusculo, 1-50 chars")
                        )
            elif tok.kind == "checkbox_with_path_md" and tok.key == "--loop":
                if not (isinstance(widget, tuple) and len(widget) == 2):
                    continue
                chk, pw = widget
                if isinstance(chk, QCheckBox) and chk.isChecked():
                    val = pw.text().strip() if isinstance(pw, PathMdFieldWidget) else ""
                    if not val or not val.endswith(".md"):
                        errors.append((i, "path .md exigido"))
        return errors

    def _validate_structured_flags(self) -> list[tuple[str, str]]:
        """Versao do `_validate_tokens` para o ramo `structured_mode`.

        Valida `--name` (SLUG_RE) e `--loop` (suffix .md) entre
        `_flags_with_value` quando o checkbox correspondente esta marcado.
        Demais flags ignoradas.
        """
        errors: list[tuple[str, str]] = []
        if not self._structured_mode:
            return errors
        for flag_spec in self._flags_with_value:
            chk = self._flag_checkboxes.get(flag_spec.name)
            if chk is None or not chk.isChecked():
                continue
            pair = self._flag_inputs.get(flag_spec.name)
            if pair is None:
                continue
            _container, edit = pair
            if edit is None:
                continue
            val = self._input_widget_text(edit)
            if flag_spec.name == "name":
                if not val or not SLUG_RE.match(val):
                    errors.append(
                        (flag_spec.name, "slug exigido: kebab-case minusculo, 1-50 chars")
                    )
            elif flag_spec.name == "loop":
                if not val or not val.endswith(".md"):
                    errors.append((flag_spec.name, "path .md exigido"))
        return errors

    def _on_validate_changed(self) -> None:
        """Recomputa erros e atualiza labels + estado do botao Confirmar.

        Disparado por `chk.toggled` e `edit.textChanged` em tokens
        validados; tambem invocado uma vez no final do `__init__` para
        sincronizar estado inicial.
        """
        for lbl in self._error_labels.values():
            lbl.setText("")
            lbl.setVisible(False)
        for lbl in self._flag_error_labels.values():
            lbl.setText("")
            lbl.setVisible(False)

        token_errors = (
            self._validate_tokens() if not self._structured_mode else []
        )
        flag_errors = (
            self._validate_structured_flags() if self._structured_mode else []
        )

        for idx, msg in token_errors:
            lbl = self._error_labels.get(idx)
            if lbl is not None:
                lbl.setText(msg)
                lbl.setVisible(True)

        for flag_name, msg in flag_errors:
            lbl = self._flag_error_labels.get(flag_name)
            if lbl is not None:
                lbl.setText(msg)
                lbl.setVisible(True)

        if self._btn_confirm is not None:
            self._btn_confirm.setEnabled(
                len(token_errors) + len(flag_errors) == 0
            )

    def _on_confirm(self) -> None:
        # Defesa em profundidade (task-022): mesmo com botao habilitado por
        # race condition, revalida antes de emitir o submit signal.
        token_errors = (
            self._validate_tokens() if not self._structured_mode else []
        )
        flag_errors = (
            self._validate_structured_flags() if self._structured_mode else []
        )
        if token_errors or flag_errors:
            # Reaplica labels (refresca UI) e bloqueia submit.
            self._on_validate_changed()
            return

        parts: list[str] = [self._pipeline_name]

        if self._structured_mode:
            main_text = self._main_input.toPlainText().strip()

            if self._fixed_flag:
                # Modo fixed_flag: injeta --{flag} {main_text} diretamente, sem checkbox.
                if main_text:
                    needs_quote = any(c in main_text for c in (" ", "\t", "\n"))
                    val = f'"{main_text}"' if needs_quote else main_text
                    parts.append(f"--{self._fixed_flag} {val}")
            else:
                # Input principal
                if main_text:
                    needs_quote = any(c in main_text for c in (" ", "\t", "\n"))
                    parts.append(f'"{main_text}"' if needs_quote else main_text)

                # Flags boolean
                for flag in self._flags_boolean:
                    chk = self._flag_checkboxes.get(flag)
                    if chk is not None and chk.isChecked():
                        parts.append(f"--{flag}")

                # Flags with value
                for flag_spec in self._flags_with_value:
                    chk = self._flag_checkboxes.get(flag_spec.name)
                    if chk is not None and chk.isChecked():
                        container, edit = self._flag_inputs[flag_spec.name]
                        val = self._input_widget_text(edit)
                        if val:
                            parts.append(f"--{flag_spec.name} {self._quote_if_needed(val)}")

            # Flag do radio de modo (ex: --certain para "kimi certain").
            # Aplica tanto no ramo fixed_flag quanto no estruturado generico.
            if self._mode_radio_widget is not None:
                sel = self._mode_radio_widget.selected()
                mode_flag = self._mode_radio_flags.get(sel, "").strip()
                if mode_flag:
                    parts.append(mode_flag)

        else:
            for i, tok in enumerate(self._tokens):
                widget = self._widgets[i]
                if tok.kind == "input":
                    assert isinstance(widget, (QLineEdit, PathMdFieldWidget))
                    val = self._input_widget_text(widget)
                    if val:
                        parts.append(self._quote_if_needed(val))
                elif tok.kind == "checkbox":
                    assert isinstance(widget, QCheckBox)
                    if widget.isChecked():
                        key = tok.key
                        # Nunca emitir placeholders literais (<slug>, <path>, etc.)
                        # no comando final. Se o checkbox contem placeholder,
                        # emite apenas o nome do flag sem o placeholder.
                        if "<" in key and ">" in key:
                            key = re.sub(r"<[^>]+>", "", key).strip()
                        if key:
                            parts.append(key)
                elif tok.kind == "checkbox_with_value":
                    assert isinstance(widget, tuple) and len(widget) == 2
                    chk, edit = widget
                    assert isinstance(chk, QCheckBox)
                    assert isinstance(edit, QLineEdit)
                    if chk.isChecked():
                        val = edit.text().strip()
                        if val:
                            if any(c in val for c in (" ", "\t")):
                                val = f'"{val}"'
                            parts.append(f"{tok.key} {val}")
                        else:
                            # Graceful: emite --flag sem valor quando input vazio.
                            parts.append(tok.key)
                elif tok.kind == "checkbox_with_path_md":
                    assert isinstance(widget, tuple) and len(widget) == 2
                    chk, pw = widget
                    assert isinstance(chk, QCheckBox)
                    assert isinstance(pw, PathMdFieldWidget)
                    if chk.isChecked():
                        val = pw.text().strip()
                        if val:
                            if any(c in val for c in (" ", "\t")):
                                val = f'"{val}"'
                            parts.append(f"{tok.key} {val}")
                        else:
                            # Graceful: emite --flag sem valor quando picker vazio.
                            parts.append(tok.key)
                elif tok.kind == "radio":
                    assert isinstance(widget, RadioGroupWithSummary)
                    sel = widget.selected()
                    if sel:
                        parts.append(sel)
                elif tok.kind == "enum_flag":
                    assert isinstance(widget, RadioGroupWithSummary)
                    sel = widget.selected()
                    if sel:
                        parts.append(sel)
                elif tok.kind == "freetext":
                    assert isinstance(widget, AutoGrowTextEdit)
                    val = widget.toPlainText().strip()
                    if val:
                        needs_quote = any(c in val for c in (" ", "\t", "\n"))
                        parts.append(f'"{val}"' if needs_quote else val)
                elif tok.kind == "path_md":
                    assert isinstance(widget, PathMdFieldWidget)
                    val = widget.text()
                    if val:
                        parts.append(f"{tok.key} {val}")

        command_line = " ".join(parts)
        self.submitted.emit(command_line)
        self.accept()
