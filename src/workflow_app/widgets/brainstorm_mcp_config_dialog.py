"""Dialog de configuracao dos seeds `blacksmith/brainstorm-mcp/seeds/NN-*.md`.

Materializa T4 do loop 05-21-implantation-tasklist-aba-brainstorm (gear
`brainstorm-mcp-config-gear`). Read+Update apenas (sem Create/Delete).
8 campos editaveis por seed: label, type, prompt, agent_name, agent_path,
action, target_path (bool), target_terminal.

Persistencia per-seed:
- yaml frontmatter preservado opacamente (sort_keys=False, chaves
  desconhecidas mantidas);
- body markdown preservado integralmente, exceto bloco `## Prompt canonico`;
- atomic write (tmpfile + fsync + os.replace + fsync do diretorio);
- file lock cooperativo `flock(LOCK_EX|LOCK_NB)` durante save.

Validacao bloqueante (Save desabilitado e label vermelho com motivo):
- label vazio;
- type fora de VALID_BUTTON_TYPES;
- action fora de VALID_ACTIONS_PTBR (7 literais T5);
- agent_path fora do repo_root OU inexistente quando != "TODO";
- (target_path, target_terminal) fora da tabela ACTION_COHERENCE;
- qualquer campo excedendo MAX_FIELD_LEN.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# Contrato canonico de identidade dos seeds do brainstorm MCP
from workflow_app.brainstorm_seed_contract import (
    CANONICAL_SEED_FILENAMES,
    extract_action_literal,
    replace_action_literal,
    resolve_seed_dir,
    seed_prefix,
    validate_action_literal,
    validate_persona_action,
)

# Catalogos reutilizados do widget MCPPromptButton.
from workflow_app.widgets.mcp_prompt_button import (
    SEED_TARGET_TERMINAL_RUNTIME_SENTINEL,
    VALID_ACTIONS_PTBR,
    VALID_BUTTON_TYPES,
    VALID_TERMINALS,
)


class SeedError(Exception):
    """Falha de parsing/escrita de seed `.md`."""


# Limites per-campo (anti YAML bomb + casa com gate st_size>64KB do loader T2).
MAX_FIELD_LEN: dict[str, int] = {
    "label": 80,
    "agent_name": 120,
    "agent_path": 260,
    "prompt": 32768,
}

# Tabela canonica de coerencia (action -> {target_path}, {target_terminal}).
ACTION_COHERENCE: dict[str, dict[str, set]] = {
    "Criar arquivo":    {"target_path": {False}, "target_terminal": {"terminal-interactive-output"}},
    "Otimizar":         {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Revisar":          {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Criar tasks":      {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Revisar tasks":    {"target_path": {True},  "target_terminal": {"terminal-interactive-output"}},
    "Executar":         {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Revisar execucao": {"target_path": {True},  "target_terminal": {"terminal-interactive-output"}},
    "Loop prepare":     {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Analisar complexidade": {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    # As 3 especializadas de C6. Todas nascem com target_path=True e os TRES
    # terminais porque os seeds 07/19/22 ja rodam com `depende-do-radio`, e o
    # sentinel so e coerente quando a action aceita os tres (regra logo abaixo).
    "Questionar":       {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Delegar":          {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
    "Atualizar scaffolds e blueprints": {"target_path": {True},  "target_terminal": {"terminal-interactive-output", "terminal-workspace-output", "terminal-codex-output"}},
}

CURRENT_SCHEMA_VERSION = 1
# Cardinalidade importada do contrato canonico: CANONICAL_SEED_COUNT

_FRONTMATTER_RX = re.compile(r"^---\n(.*?)\n---\n?(.*)\Z", re.S)

# Prefixo historico "Seed - Botao N - " que o `title` carrega. O label efetivo
# do botao da grade nunca o exibe (paridade com main_window._load_brainstorm_seeds).
_LABEL_PREFIX_RX = re.compile(r"^Seed\s*-\s*Botao\s*\d+\s*-\s*")


def effective_label(meta: dict[str, Any]) -> str:
    """Label que o botao da grade realmente exibe, para um dado seed `meta`.

    Precedencia IDENTICA ao loader em `main_window._load_brainstorm_seeds`:
    campo `label` explicito (nao-vazio) vence; senao deriva do `title`
    removendo o prefixo "Seed - Botao N - "; fallback final = `slug`. O
    prefixo tambem e removido de labels legados que guardaram o title inteiro,
    para que o gear nunca mostre "Seed - Botao N - ..." no campo Label.
    """
    explicit = _LABEL_PREFIX_RX.sub("", str(meta.get("label") or "").strip()).strip()
    if explicit:
        return explicit
    stripped = _LABEL_PREFIX_RX.sub("", str(meta.get("title") or "").strip()).strip()
    return stripped or str(meta.get("slug") or "").strip()


def _sanitize(value: str, key: str) -> str:
    """Remove BOM/null + strip + cap por MAX_FIELD_LEN."""
    s = value.replace("﻿", "").replace("\x00", "").strip()
    cap = MAX_FIELD_LEN.get(key, 1024)
    if len(s) > cap:
        raise ValueError(f"Campo '{key}' excede {cap} chars (tem {len(s)})")
    return s


def load_seed(path: Path) -> tuple[dict[str, Any], str]:
    """Le `path`, retorna `(meta_dict, body_str)`.

    Tolera BOM utf-8. Falha em frontmatter ausente, root nao-mapping ou
    yaml malformado.
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SeedError(f"{path.name}: erro de leitura: {exc}") from exc
    m = _FRONTMATTER_RX.match(raw)
    if not m:
        raise SeedError(f"{path.name}: frontmatter ausente")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"{path.name}: yaml malformado: {exc}") from exc
    if not isinstance(meta, dict):
        raise SeedError(f"{path.name}: root frontmatter nao e mapping")
    return meta, m.group(2)


def _parse_seed_text(path: Path, text: str) -> tuple[dict[str, Any], str]:
    """Mesmo parse de `load_seed`, mas sobre texto ja lido.

    Existe para o prepare transacional poder guardar os bytes originais e
    parsear a MESMA copia, sem uma segunda leitura que poderia divergir.
    """
    m = _FRONTMATTER_RX.match(text)
    if not m:
        raise SeedError(f"{path.name}: frontmatter ausente ou malformado")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"{path.name}: yaml malformado: {exc}") from exc
    if not isinstance(meta, dict):
        raise SeedError(f"{path.name}: root frontmatter nao e mapping")
    return meta, m.group(2)


def render_seed(path: Path, patch: dict[str, Any], prompt_body: str) -> tuple[str, str]:
    """Prepara o conteudo novo de um seed SEM escrever nada.

    Devolve `(texto_original, texto_novo)`. Toda recusa possivel (frontmatter
    ausente, yaml malformado, bloco `## Prompt canonico` ausente) acontece
    aqui, ANTES de qualquer escrita -- e o que torna o save multi-arquivo
    abortavel com zero efeito colateral.
    """
    original = path.read_text(encoding="utf-8")
    meta, body = _parse_seed_text(path, original)
    meta.update(patch)
    try:
        new_body = replace_action_literal(body, prompt_body)
    except ValueError as exc:
        raise SeedError(f"{path.name}: {exc}") from exc
    meta_dump = yaml.safe_dump(meta, sort_keys=False, allow_unicode=False).strip()
    return original, f"---\n{meta_dump}\n---\n{new_body}"


def _atomic_write(path: Path, out: str) -> None:
    """Atomic write robusto: tmpfile -> fsync -> os.replace -> fsync diretorio."""
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
    )
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass  # fsync de diretorio nao suportado em alguns FS (tmpfs etc).
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def save_seed(path: Path, patch: dict[str, Any], prompt_body: str) -> None:
    """Aplica `patch` ao frontmatter e substitui o bloco `## Prompt canonico`.

    Atomic write robusto: tmpfile -> fsync -> os.replace -> fsync diretorio.
    File lock cooperativo `flock(LOCK_EX|LOCK_NB)` adquirido durante a operacao.
    Linux: usa fcntl; Windows: pula lock com WARN (app primario e Linux).

    Para gravar VARIOS seeds de uma vez use `save_seeds_transactional`: um
    laco de `save_seed` deixa o disco com um subconjunto aplicado se o
    K-esimo arquivo falhar.
    """
    lock_fd = _acquire_lock(path, exclusive=True)
    try:
        _, out = render_seed(path, patch, prompt_body)
        _atomic_write(path, out)
    finally:
        _release_lock(lock_fd)


def save_seeds_transactional(
    items: Sequence[tuple[Path, dict[str, Any], str]],
) -> None:
    """Grava N seeds com tudo-ou-nada OBSERVAVEL.

    FASE 1 (prepare): todo seed e travado, lido, validado e renderizado em
    memoria. Qualquer recusa aqui aborta com ZERO escrita em disco.
    FASE 2 (commit): as escritas atomicas correm em sequencia. Se a K-esima
    falhar, as K-1 ja gravadas sao devolvidas ao byte original antes de a
    excecao subir.

    Nao e transacao de verdade -- o SO nao oferece rename de N arquivos em
    bloco. E compensacao. Se a propria restauracao falhar, a excecao original
    sobe encadeada dentro de um `SeedError` que NOMEIA os arquivos que ficaram
    divergentes, porque nesse caso o operador precisa do tarball de baseline.
    """
    locks: list[int | None] = []
    prepared: list[tuple[Path, str, str]] = []
    try:
        for path, patch, prompt_body in items:
            locks.append(_acquire_lock(path, exclusive=True))
            original, out = render_seed(path, patch, prompt_body)
            prepared.append((path, original, out))

        written: list[tuple[Path, str]] = []
        try:
            for path, original, out in prepared:
                _atomic_write(path, out)
                written.append((path, original))
        except (OSError, SeedError) as exc:
            divergentes: list[str] = []
            for path, original in reversed(written):
                try:
                    _atomic_write(path, original)
                except OSError:
                    divergentes.append(path.name)
            if divergentes:
                raise SeedError(
                    "save falhou e a restauracao tambem: seeds divergentes em "
                    f"disco: {', '.join(sorted(divergentes))}. Restaurar do "
                    "tarball de baseline antes de salvar de novo."
                ) from exc
            raise
    finally:
        for fd in locks:
            _release_lock(fd)


def _acquire_lock(path: Path, exclusive: bool) -> int | None:
    """Adquire flock cooperativo nao-bloqueante. Retorna fd ou None (Windows)."""
    if sys.platform.startswith("win"):
        return None  # Windows: skip lock com WARN silencioso.
    import fcntl
    fd = os.open(str(path), os.O_RDONLY)
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        os.close(fd)
        raise SeedError(f"{path.name}: seed em uso (lock indisponivel): {exc}") from exc
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class BrainstormMcpConfigDialog(QDialog):
    """Modal application-wide para editar os seeds brainstorm-mcp."""

    saved = Signal()  # Emitido apos save bem-sucedido (rebuild da grade).

    def __init__(
        self,
        parent: QWidget | None,
        repo_root: Path,
        seeds_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("testid", "brainstorm-mcp-config-dialog")
        self.setWindowTitle("Configurar seeds brainstorm-mcp")
        self.setMinimumSize(900, 560)

        self.repo_root: Path = repo_root.resolve()
        # O default vem do CONTRATO, nunca de literal local. Este ramo
        # carregava "blacksmith/brainstorm-mcp" escrito a mao; quando os 24
        # seeds desceram para `seeds/` (C3 Task 08) o literal ficou apontando
        # para o diretorio PAI. A grade ja usava `resolve_seed_dir` e por isso
        # continuou achando os seeds -- a engrenagem, nao: abria com
        # "encontrados 0" e o save desabilitado. A suite nao viu nada porque
        # todo teste injetava `seeds_dir`, exercitando o parametro e jamais o
        # wiring de producao, que passa `repo_root` e mais nada.
        self.seeds_dir: Path = (
            seeds_dir.resolve() if seeds_dir else resolve_seed_dir(self.repo_root)
        )

        # Estado per-seed: lista paralela aos itens da lista lateral.
        self._seed_paths: list[Path] = []
        self._seed_meta: list[dict[str, Any]] = []
        self._seed_prompt: list[str] = []
        self._current_index: int = -1
        self._dirty: bool = False
        #: `button_type` lido do disco quando ele NAO pertence a
        #: `VALID_BUTTON_TYPES`. O combo e fechado e nao consegue exibi-lo; o
        #: valor sobrevive aqui para o erro citar o que esta em disco em vez de
        #: `''`, e para `_capture_form_into` nao apaga-lo da memoria.
        self._type_invalido: str = ""

        self._build_ui()
        self._load_seeds()

    # ---- UI build ----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # ---- Coluna esquerda: lista dos seeds ----
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)
        # Contagem preenchida por `_load_seeds`: cravar `CANONICAL_SEED_COUNT`
        # no rotulo faria a UI mentir assim que a cardinalidade aberta rendesse
        # um numero diferente do registro canonico.
        list_title = QLabel("Seeds")
        self._list_title = list_title
        list_title.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        list_layout.addWidget(list_title)
        self._list_widget = QListWidget()
        self._list_widget.setProperty("testid", "brainstorm-mcp-config-list")
        self._list_widget.currentRowChanged.connect(self._on_row_changed)
        list_layout.addWidget(self._list_widget, stretch=1)
        splitter.addWidget(list_panel)

        # ---- Coluna direita: formulario dos 8 campos ----
        form_panel = QWidget()
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)

        self._slug_label = QLabel("slug: -")
        self._slug_label.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        form_layout.addWidget(self._slug_label)

        self._label_edit = self._mk_lineedit("brainstorm-mcp-config-label")
        form_layout.addLayout(self._row("Label", self._label_edit))

        self._type_combo = QComboBox()
        self._type_combo.setProperty("testid", "brainstorm-mcp-config-type")
        for t in sorted(VALID_BUTTON_TYPES):
            self._type_combo.addItem(t)
        self._type_combo.currentTextChanged.connect(self._mark_dirty)
        form_layout.addLayout(self._row("Type", self._type_combo))

        self._agent_name_edit = self._mk_lineedit("brainstorm-mcp-config-agent-name")
        form_layout.addLayout(self._row("Agent name", self._agent_name_edit))

        self._agent_path_edit = self._mk_lineedit("brainstorm-mcp-config-agent-path")
        form_layout.addLayout(self._row("Agent path", self._agent_path_edit))

        self._action_combo = QComboBox()
        self._action_combo.setProperty("testid", "brainstorm-mcp-config-action")
        # Task 29: EDITAVEL. Os itens continuam sendo o catalogo conhecido (e
        # o caminho de 100% dos seeds de hoje), mas deixaram de ser o limite:
        # digitar uma action nova aqui e o que substitui editar Python em dois
        # repositorios. Quem julga o texto digitado e o par persona-action e,
        # na montagem do prompt, a exigencia do bloco `## Prompt canonico`.
        self._action_combo.setEditable(True)
        for a in sorted(VALID_ACTIONS_PTBR):
            self._action_combo.addItem(a)
        self._action_combo.currentTextChanged.connect(self._mark_dirty)
        form_layout.addLayout(self._row("Action", self._action_combo))

        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(8)
        target_row.addWidget(QLabel("target_path:"))
        self._target_path_chk = QCheckBox()
        self._target_path_chk.setProperty(
            "testid", "brainstorm-mcp-config-target-path",
        )
        self._target_path_chk.toggled.connect(self._mark_dirty)
        target_row.addWidget(self._target_path_chk)
        target_row.addSpacing(12)
        target_row.addWidget(QLabel("target_terminal:"))
        self._target_terminal_combo = QComboBox()
        self._target_terminal_combo.setProperty(
            "testid", "brainstorm-mcp-config-target-terminal",
        )
        # O sentinel entra como item de primeira classe (e primeiro da lista):
        # ele e o valor de 20 dos 24 seeds e significa "quem escolhe e o radio
        # T1/T2/T3 em runtime". Sem ele no combo, abrir e salvar um seed pela
        # engrenagem trocava silenciosamente o sentinel por um terminal fixo.
        self._target_terminal_combo.addItem(SEED_TARGET_TERMINAL_RUNTIME_SENTINEL)
        for t in sorted(VALID_TERMINALS):
            self._target_terminal_combo.addItem(t)
        self._target_terminal_combo.currentTextChanged.connect(self._mark_dirty)
        target_row.addWidget(self._target_terminal_combo, stretch=1)
        form_layout.addLayout(target_row)

        form_layout.addWidget(QLabel("Prompt canonico:"))
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setProperty("testid", "brainstorm-mcp-config-prompt")
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._prompt_edit.setFont(mono)
        self._prompt_edit.textChanged.connect(self._mark_dirty)
        form_layout.addWidget(self._prompt_edit, stretch=1)

        self._error_label = QLabel("")
        self._error_label.setProperty("testid", "brainstorm-mcp-config-error")
        self._error_label.setStyleSheet(
            "color: #F87171; font-size: 11px; background: transparent;",
        )
        self._error_label.setWordWrap(True)
        form_layout.addWidget(self._error_label)

        splitter.addWidget(form_panel)
        splitter.setSizes([220, 680])

        # ---- Botoes Save/Cancel ----
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        self._save_btn.setProperty("testid", "brainstorm-mcp-config-save")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setProperty("testid", "brainstorm-mcp-config-cancel")
        btn_box.accepted.connect(self._on_save_clicked)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    def _row(self, title: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        lbl = QLabel(f"{title}:")
        lbl.setMinimumWidth(96)
        row.addWidget(lbl)
        row.addWidget(widget, stretch=1)
        return row

    def _mk_lineedit(self, testid: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setProperty("testid", testid)
        edit.textChanged.connect(self._mark_dirty)
        return edit

    # ---- Data load ---------------------------------------------------------

    def _load_seeds(self) -> None:
        if not self.seeds_dir.is_dir():
            self._error_label.setText(
                f"Diretorio inexistente: {self.seeds_dir}",
            )
            self._save_btn.setEnabled(False)
            return

        # Task 29: cardinalidade ABERTA, igual a do loader da grade. O gear
        # exigia exatamente `CANONICAL_SEED_COUNT` arquivos com prefixos
        # `01..24` exatos -- entao acrescentar um seed 25 fechava a
        # engrenagem inteira ("encontrados 25") em vez de exibir o seed novo.
        # A regra de forma (`NN-<slug>.md`, com a precedencia output-antes-de-
        # seed) vem do contrato, nao de uma regex local.
        descobertos: dict[Path, int] = {}
        for q in sorted(self.seeds_dir.glob("*.md")):
            n = seed_prefix(q.name)
            if n is not None:
                descobertos[q] = n
        if not descobertos:
            self._error_label.setText(
                f"Nenhum seed NN-<slug>.md em {self.seeds_dir}",
            )
            self._save_btn.setEnabled(False)
            return

        numeros = set(descobertos.values())
        faltando = [i for i in range(1, max(numeros) + 1) if i not in numeros]
        if faltando:
            # Buraco na sequencia bloqueia a EDICAO de proposito: o gear grava
            # de volta o que carregou, e carregar uma sequencia furada e o
            # sintoma de que um seed sumiu do disco. Abrir assim seria
            # convidar o operador a salvar por cima de um estado ja quebrado.
            self._error_label.setText(
                "Sequencia 01..N com buraco; prefixos faltando: "
                + ", ".join(f"{i:02d}" for i in faltando),
            )
            self._save_btn.setEnabled(False)
            return

        paths = sorted(descobertos, key=lambda q: descobertos[q])

        # A tupla canonica sobrevive como REGISTRO DE IDENTIDADE. Ausencia
        # dela nao trava o gear (os outros seeds continuam editaveis, e a
        # grade ja reporta o sumico), mas tem de aparecer.
        presentes = {q.name for q in paths}
        sumidos = [n for n in CANONICAL_SEED_FILENAMES if n not in presentes]
        if sumidos:
            self._error_label.setText(
                "Aviso: seed canonico ausente: " + ", ".join(sumidos),
            )

        self._seed_paths = []
        self._seed_meta = []
        self._seed_prompt = []
        for p in paths:
            try:
                meta, body = load_seed(p)
            except SeedError as exc:
                self._error_label.setText(str(exc))
                self._save_btn.setEnabled(False)
                return
            schema_v = meta.get("schema_version", CURRENT_SCHEMA_VERSION)
            if schema_v != CURRENT_SCHEMA_VERSION:
                self._error_label.setText(
                    f"{p.name} schema_version={schema_v!r} incompativel "
                    f"(esperado {CURRENT_SCHEMA_VERSION})",
                )
                self._save_btn.setEnabled(False)
                return
            self._seed_paths.append(p)
            self._seed_meta.append(dict(meta))
            try:
                literal = extract_action_literal(body)
            except ValueError as exc:
                self._error_label.setText(f"{p.name}: {exc}")
                self._save_btn.setEnabled(False)
                return
            if literal is None:
                self._error_label.setText(
                    f"{p.name}: bloco `## Prompt canonico` ausente",
                )
                self._save_btn.setEnabled(False)
                return
            self._seed_prompt.append(literal)

            slug = str(meta.get("slug") or p.stem)
            label = effective_label(meta) or slug
            item = QListWidgetItem(f"{p.name}  -  {label}")
            item.setData(Qt.ItemDataRole.UserRole, slug)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"brainstorm-mcp-config-row-{slug}")
            self._list_widget.addItem(item)

        self._list_title.setText(f"Seeds ({len(self._seed_paths)})")
        self._list_widget.setCurrentRow(0)

    # ---- Row swap ----------------------------------------------------------

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._seed_paths):
            return
        # Persistir edits do row anterior em memoria.
        if self._current_index >= 0:
            self._capture_form_into(self._current_index)
        self._current_index = row
        self._render_form_from(row)
        self._dirty = False  # carregar nao conta como dirty.
        self._validate()

    def _render_form_from(self, idx: int) -> None:
        meta = self._seed_meta[idx]
        prompt = self._seed_prompt[idx]
        self._slug_label.setText(f"slug: {meta.get('slug', '-')}")
        # Bloqueia signals durante repopulacao para nao marcar dirty.
        for w in (
            self._label_edit, self._type_combo, self._agent_name_edit,
            self._agent_path_edit, self._action_combo,
            self._target_path_chk, self._target_terminal_combo,
            self._prompt_edit,
        ):
            w.blockSignals(True)

        self._label_edit.setText(effective_label(meta))
        # `or "Claude"` aqui anulava todo o mecanismo abaixo para os valores
        # FALSY: `button_type:` vazio, `null`, `false` ou `0` no disco viravam
        # "Claude" ANTES do teste de pertinencia, o combo exibia um type valido
        # que nao existe em disco, `_capture_form_into` gravava "Claude" por
        # cima e `_validate_record` -- que le o meta cru e reprovaria -- passava
        # a aprovar. O defeito de disco era reparado em silencio para um palpite.
        # Preserva o valor cru; so `None`/ausente vira `""` (nao ha type
        # declarado, e `str(None)` == `"None"` mentiria dizendo que ha).
        bruto = meta.get("button_type")
        button_type = "" if bruto is None else str(bruto)
        # Mesmo defeito de `action` e `target_terminal` (comentados abaixo),
        # com uma diferenca: este combo e FECHADO, entao nao da para cravar um
        # valor invalido dentro dele -- `setCurrentText` seria no-op e deixaria
        # exibido o `button_type` da linha ANTERIOR, que `_capture_form_into`
        # gravaria por cima desta seed. Como o residuo anterior e um valor
        # VALIDO, a validacao aprovaria e o disco seria corrompido em silencio.
        # Indice -1 esvazia a selecao: o form nao mente sobre o disco e o save
        # fica barrado por `_validate_record` ate alguem escolher um type.
        if button_type in VALID_BUTTON_TYPES:
            self._type_invalido = ""
            self._type_combo.setCurrentIndex(self._type_combo.findText(button_type))
        else:
            self._type_invalido = button_type
            self._type_combo.setCurrentIndex(-1)
        self._agent_name_edit.setText(str(meta.get("agent_name") or ""))
        self._agent_path_edit.setText(str(meta.get("agent_path") or ""))
        action = str(meta.get("action") or "")
        # Sempre cravar, nunca condicionar a pertinencia: com o combo aberto,
        # `if action in VALID_ACTIONS_PTBR` deixaria o widget exibindo a action
        # do seed ANTERIOR sempre que a atual fosse nova -- e `_capture_form_into`
        # gravaria esse residuo por cima do seed atual (mesmo defeito ja
        # documentado logo abaixo, em `target_terminal`).
        self._action_combo.setCurrentText(action)
        self._target_path_chk.setChecked(bool(meta.get("target_path") or False))
        tt = str(meta.get("target_terminal") or "terminal-interactive-output")
        # Sempre cravar um valor: o `if` sozinho deixava o combo com o valor do
        # seed anterior quando `tt` era desconhecido, e `_capture_form_into`
        # gravava esse residuo no seed atual.
        if tt not in VALID_TERMINALS and tt != SEED_TARGET_TERMINAL_RUNTIME_SENTINEL:
            tt = "terminal-interactive-output"
        self._target_terminal_combo.setCurrentText(tt)
        self._prompt_edit.setPlainText(prompt)

        for w in (
            self._label_edit, self._type_combo, self._agent_name_edit,
            self._agent_path_edit, self._action_combo,
            self._target_path_chk, self._target_terminal_combo,
            self._prompt_edit,
        ):
            w.blockSignals(False)

    def _capture_form_into(self, idx: int) -> None:
        """Copia valores atuais do form para `self._seed_meta[idx]` e `_seed_prompt[idx]`."""
        meta = self._seed_meta[idx]
        meta["label"] = self._label_edit.text()
        # Indice -1 = o valor do disco nao esta na lista (ver
        # `_render_form_from`). Capturar `currentText()` (`''`) apagaria da
        # memoria o valor invalido que o operador precisa ver para corrigir, e
        # trocaria um erro nomeado por um erro anonimo. Preserva.
        if self._type_combo.currentIndex() >= 0:
            meta["button_type"] = self._type_combo.currentText()
        meta["agent_name"] = self._agent_name_edit.text()
        meta["agent_path"] = self._agent_path_edit.text()
        meta["action"] = self._action_combo.currentText()
        meta["target_path"] = bool(self._target_path_chk.isChecked())
        meta["target_terminal"] = self._target_terminal_combo.currentText()
        meta.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
        self._seed_prompt[idx] = self._prompt_edit.toPlainText()

    # ---- Validation --------------------------------------------------------

    def _mark_dirty(self, *_args: Any) -> None:
        self._dirty = True
        self._validate()

    def _validate(self) -> bool:
        """Valida o row VISIVEL. Atualiza error label + save enabled.

        Delega ao mesmo `_validate_record` que o submit roda sobre os 24, para
        que as duas portas cobrem exatamente as mesmas regras. Duplicar a
        lista de regras aqui foi como o buraco do submit nasceu.
        """
        try:
            self._validate_record(
                {
                    "label": self._label_edit.text(),
                    "button_type": (
                        self._type_combo.currentText()
                        if self._type_combo.currentIndex() >= 0
                        else self._type_invalido
                    ),
                    "agent_name": self._agent_name_edit.text(),
                    "agent_path": self._agent_path_edit.text(),
                    "action": self._action_combo.currentText(),
                    "target_path": bool(self._target_path_chk.isChecked()),
                    "target_terminal": self._target_terminal_combo.currentText(),
                },
                self._prompt_edit.toPlainText(),
            )
        except ValueError as exc:
            self._error_label.setText(str(exc))
            self._save_btn.setEnabled(False)
            return False

        self._error_label.setText("")
        self._save_btn.setEnabled(True)
        return True

    def _validate_record(self, meta: dict[str, Any], prompt_text: str) -> None:
        """Julga UM registro de seed. Sem widget, sem efeito colateral.

        Levanta `ValueError` com a razao. Serve tanto ao row visivel quanto a
        varredura dos 24 no submit.
        """
        try:
            label = _sanitize(str(meta.get("label", "")), "label")
            if not label:
                raise ValueError("Label obrigatorio")

            btn_type = str(meta.get("button_type", ""))
            if btn_type not in VALID_BUTTON_TYPES:
                raise ValueError(f"Type invalido: {btn_type!r}")

            agent_name = _sanitize(str(meta.get("agent_name", "")), "agent_name")
            agent_path = _sanitize(str(meta.get("agent_path", "")), "agent_path")
            self._validate_agent_path(agent_path)

            action = _sanitize(str(meta.get("action", "")), "action")
            if not action:
                raise ValueError("Action obrigatoria")
            # Task 29: o gate de PERTINENCIA a `VALID_ACTIONS_PTBR` saiu. O
            # combo virou editavel e uma action nova nao pode mais exigir
            # edicao de Python. O que continua julgando a action e o par
            # persona-action logo abaixo (que reprova exatamente o que
            # reprovava antes, em persona conhecida) e, na hora de montar o
            # prompt, a exigencia de que o seed traga o proprio bloco
            # `## Prompt canonico` quando a action esta fora do catalogo.

            # G7: coerencia do PAR persona-action (C6). Paridade com o gate do
            # loader em `main_window._load_one_brainstorm_seed`: sem ele, o
            # gear grava um par que a proxima carga da grade recusa.
            incoerencia = validate_persona_action(agent_path, action)
            if incoerencia is not None:
                raise ValueError(f"G7: {incoerencia}")

            target_path = bool(meta.get("target_path", False))
            target_terminal = str(meta.get("target_terminal", ""))
            defer_to_radio = (
                target_terminal == SEED_TARGET_TERMINAL_RUNTIME_SENTINEL
            )
            if not defer_to_radio and target_terminal not in VALID_TERMINALS:
                raise ValueError(f"target_terminal invalido: {target_terminal!r}")
            # Task 29: action fora da tabela nao e mais reprovada -- o gate
            # ABSTEM, do mesmo jeito que `validate_persona_action` se abstem
            # de persona desconhecida. Inventar veredito para o que nunca foi
            # medido transformaria o gate em bloqueio de trabalho legitimo.
            # Para as actions mapeadas, a coerencia continua identica -- e as
            # validacoes DEPOIS deste bloco (sanitizacao do prompt, recusa de
            # linha comecando em `{`/`[`) valem para toda action, mapeada ou
            # nao: abstencao aqui nao pode virar `return` e pular o resto.
            coh = ACTION_COHERENCE.get(action)
            if coh is not None:
                if target_path not in coh["target_path"]:
                    raise ValueError(
                        f"Combinacao invalida: action={action!r} requer "
                        f"target_path in {sorted(coh['target_path'])}",
                    )
                if defer_to_radio:
                    # Adiar para o radio so e coerente quando a action aceita os
                    # TRES terminais. Se ela crava um terminal, o runtime nao pode
                    # escolher outro e o sentinel viraria publicacao no lugar errado.
                    if set(coh["target_terminal"]) != VALID_TERMINALS:
                        raise ValueError(
                            f"Combinacao invalida: action={action!r} exige terminal "
                            f"fixo in {sorted(coh['target_terminal'])}, entao "
                            f"target_terminal nao pode ser "
                            f"{SEED_TARGET_TERMINAL_RUNTIME_SENTINEL!r}",
                        )
                elif target_terminal not in coh["target_terminal"]:
                    raise ValueError(
                        f"Combinacao invalida: action={action!r} requer "
                        f"target_terminal in {sorted(coh['target_terminal'])}",
                    )

            _sanitize(prompt_text, "prompt")
            # O ESCRITOR tem de recusar exatamente o que o LEITOR recusa.
            # `validate_action_literal` e o gate do loader; sem ele aqui, o
            # gear gravava corpo vazio, com NUL, com token reservado do
            # renderer ou com `##` interno, o Save fechava dizendo OK, e o
            # rebuild seguinte recusava (botao some) ou truncava no `##` (o
            # modelo recebe meio prompt). Escrita e leitura discordando em
            # silencio -- a classe de defeito que a C2 existe para fechar.
            #
            # E TEM de ser sobre o buffer do editor: depois de gravado, um
            # `##` interno ja encerrou o bloco e a releitura nao consegue
            # mais distinguir "corpo truncado" de "corpo curto". A propria
            # docstring de `validate_action_literal` diz isso; faltava a
            # chamada.
            recusa = validate_action_literal(prompt_text)
            if recusa is not None:
                raise ValueError(recusa)
            for line in prompt_text.splitlines():
                stripped = line.lstrip()
                if stripped[:1] in ("{", "["):
                    raise ValueError(
                        "Prompt nao pode comecar linha com yaml flow style (`{`/`[`)",
                    )
        except KeyError as exc:  # meta incompleto vindo do disco
            raise ValueError(f"Campo ausente no registro: {exc}") from exc

    def _validate_all_records(self) -> bool:
        """Varre os 24 registros no submit, nao so o row visivel.

        Sem esta varredura da para deixar um registro invalido, navegar para
        outro valido -- o que zera o error label -- e salvar o conjunto
        inteiro, gravando em disco o registro que nunca passou. O row visivel
        ja foi capturado em `_seed_meta` pelo caller antes desta chamada, entao
        aqui `_seed_meta` e a verdade completa.

        Ao reprovar, SELECIONA o seed culpado: mandar corrigir sem dizer qual
        dos 24 esta errado deixa o operador procurando as cegas.
        """
        for i, meta in enumerate(self._seed_meta):
            try:
                self._validate_record(meta, self._seed_prompt[i])
            except ValueError as exc:
                nome = (
                    self._seed_paths[i].name
                    if i < len(self._seed_paths)
                    else f"seed #{i + 1}"
                )
                if i != self._current_index:
                    self._list_widget.setCurrentRow(i)
                self._error_label.setText(f"{nome}: {exc}")
                self._save_btn.setEnabled(False)
                return False
        return True

    def _validate_agent_path(self, agent_path: str) -> None:
        if not agent_path:
            raise ValueError("agent_path obrigatorio")
        if agent_path == "TODO":
            return  # placeholder permitido em refactor.
        ap = (self.repo_root / agent_path).resolve()
        try:
            ap.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"agent_path fora do repo: {agent_path}") from exc
        if not ap.is_file():
            raise ValueError(f"agent_path inexistente: {agent_path}")

    # ---- Save --------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        # Captura o row atual antes de validar.
        if self._current_index >= 0:
            self._capture_form_into(self._current_index)

        if not self._validate():
            return
        if not self._validate_all_records():
            return

        # Persiste todos os seeds (idempotente quando nao houve dirty per-seed,
        # mas re-grava igual mesmo assim - simplificacao defensiva).
        #
        # C2a.1: a gravacao passa por `save_seeds_transactional`. O laco antigo
        # de `save_seed` deixava o disco com um subconjunto aplicado quando o
        # K-esimo arquivo falhava -- e sem `saved` emitido, entao a grade
        # continuava servindo o texto velho de um arquivo ja reescrito.
        items: list[tuple[Path, dict[str, Any], str]] = []
        try:
            for i, p in enumerate(self._seed_paths):
                meta = self._seed_meta[i]
                prompt = self._seed_prompt[i]
                patch = {
                    "label": meta.get("label", ""),
                    "button_type": meta.get("button_type", "Claude"),
                    "agent_name": meta.get("agent_name", ""),
                    "agent_path": meta.get("agent_path", ""),
                    "action": meta.get("action", ""),
                    "target_path": bool(meta.get("target_path", False)),
                    "target_terminal": meta.get("target_terminal", ""),
                    "schema_version": meta.get(
                        "schema_version", CURRENT_SCHEMA_VERSION,
                    ),
                }
                items.append((p, patch, prompt))
            save_seeds_transactional(items)
        except SeedError as exc:
            self._error_label.setText(f"Falha de save: {exc}")
            self._save_btn.setEnabled(True)
            return
        except OSError as exc:
            self._error_label.setText(f"Falha de IO: {exc}")
            self._save_btn.setEnabled(True)
            return

        self.saved.emit()
        self.accept()
