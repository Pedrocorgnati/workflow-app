"""Pytest configuration for Workflow App tests."""

from __future__ import annotations

import os
import sys

import pytest

# ── Guard de telemetria real (TASK 01) ──────────────────────────────────────
# Armado NO IMPORT do conftest, antes de qualquer coleta: `MetricsBar.
# _append_failure_telemetry` recusa escrever em `.claude/wf-failures/` do repo
# real enquanto esta variavel estiver setada. Escrita em tmp_path continua
# funcionando (o guard compara com a raiz real resolvida no modulo).
# Contrato: ai-forge/workflow-app/tests/test_telemetry_no_real_write.py
os.environ["WF_BLOCK_REAL_FAILURE_TELEMETRY"] = "1"

# ── Guard do sidecar de lifecycle (Task 24) ─────────────────────────────────
# Mesma forma, outro destino: sem isto a suite despeja centenas de eventos
# sinteticos em `~/.workflow-app/logs/loop-lifecycle-*.jsonl` e contamina o
# corpus que decide se um loop foi cancelado ou abandonado. O guard cede a
# `SF_LOOP_LIFECYCLE_DIR`, entao teste que aponta para tmp_path grava normal.
# Contrato: ai-forge/workflow-app/tests/test_loop_lifecycle_sink.py
os.environ["WF_BLOCK_REAL_LIFECYCLE_TELEMETRY"] = "1"

# Task 33: a leitura de ~/.claude/projects/*.jsonl so existe para custo real.
# Sem o guard a suite somaria tokens de sessoes humanas no host.
os.environ["WF_BLOCK_REAL_USAGE_JSONL"] = "1"

# Sidecar do brainstorm (C4/Task 33): os pontos de termino agora
# emitem, e sem esta guarda cada MainWindow construida pela suite gravaria
# eventos de teste no ~/.workflow-app/logs do operador.
os.environ["WF_BLOCK_REAL_BRAINSTORM_TELEMETRY"] = "1"
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from workflow_app.db.database_manager import DatabaseManager
from workflow_app.db.models import Base

# ── Markers opt-in ────────────────────────────────────────────────────────────


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`grok_live` so entra na coleta quando pedido explicitamente por `-m`.

    Os testes marcados exigem `GROK_API_KEY` e falham com `BLOCKED` (nunca skip)
    quando a credencial esta ausente — esse e o contrato C-58/G6 do item 025:
    skip nao conta como aprovacao. Mas o Grok deste host autentica por
    `~/.grok/auth.json`, nao por variavel de ambiente, entao a suite completa
    (aceite do item 029, piso de 0 falhas) nunca teria como satisfazer o marker.

    A resolucao preserva os dois contratos: quem roda o aceite do item 025
    (`-m grok_live`) continua vendo a falha dura sem credencial; a suite completa
    deseleciona o marker em vez de herdar uma falha estrutural do ambiente.
    """
    markexpr = str(getattr(config.option, "markexpr", "") or "")
    if "grok_live" in markexpr:
        return
    skip_marker = pytest.mark.skip(
        reason="grok_live e opt-in: rodar com `-m grok_live` (exige GROK_API_KEY)"
    )
    for item in items:
        if "grok_live" in item.keywords:
            item.add_marker(skip_marker)


# ── Qt ────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for PySide6 tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _block_real_failure_telemetry(monkeypatch):
    """Reafirma o guard a cada teste (TASK 01).

    O import do conftest ja arma a variavel; este autouse impede que um teste
    que mexa em `os.environ` deixe a guarda baixada para os testes seguintes.
    """
    monkeypatch.setenv("WF_BLOCK_REAL_FAILURE_TELEMETRY", "1")
    monkeypatch.setenv("WF_BLOCK_REAL_BRAINSTORM_TELEMETRY", "1")


@pytest.fixture(autouse=True)
def _cleanup_qt_widgets():
    """Close and dispose ALL widgets after every test (hardening T9).

    Without this, MainWindow instances created by tests accumulate in the
    session-scoped QApplication. Each subsequent `setStyleSheet`/repaint
    has to walk every leaked widget tree, which made the 5th window in
    test_main_window.py time out at 20-30s on `apply_theme`.

    Hardening do loop 05-21 (T8/T9): deletar `app.allWidgets()` (nao apenas
    `topLevelWidgets()`) porque widgets-filhos com parent NAO sao top-level
    e contaminam `findChildren` em testes subsequentes (vide cenarios T7
    Codex gate que dependem de testid unico).
    """
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    import gc

    try:
        import shiboken6
    except ImportError:
        shiboken6 = None  # type: ignore[assignment]

    from PySide6.QtCore import QCoreApplication, QEvent

    # 1) Fechar top-level e agendar a destruicao pelo event loop. Nao usar
    #    shiboken6.delete aqui: findChildren(QWidget) pode materializar wrappers
    #    Python dos filhos, e destruir o parent diretamente no C++ deixa esses
    #    wrappers em um estado que causa SIGSEGV durante suites longas.
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
            if shiboken6 is None or shiboken6.isValid(w):
                w.deleteLater()
        except (RuntimeError, ReferenceError):
            # Widget already deleted by the test itself.
            pass

    # 2) Hardening T9: limpar widgets filhos remanescentes (parents que
    #    sobreviveram top-level cleanup, e.g. dialogs reparented). Cada
    #    widget e protegido por try/except + shiboken6.isValid para nao
    #    explodir em widgets ja destruidos pela primeira passada.
    for w in list(app.allWidgets()):
        try:
            if shiboken6 is not None and not shiboken6.isValid(w):
                continue
            w.deleteLater()
        except (RuntimeError, ReferenceError):
            pass

    # processEvents() sozinho nao entrega DeferredDelete. Drenar esses eventos
    # explicitamente preserva a limpeza sincronizada entre testes sem recorrer
    # a destruicao direta via shiboken6.delete.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


# ── Hardening fixtures T9 (loop 05-21-implantation-tasklist-aba-brainstorm)


@pytest.fixture(autouse=True)
def qsettings_isolated(tmp_path, monkeypatch):
    """Isola QSettings em `tmp_path` por teste (cenario 9 - clear no restart).

    Hardening T9 §4: testes nao podem poluir `~/.config/` do usuario. Aponta
    `QSettings.setPath` para `tmp_path` em UserScope+SystemScope e seta
    `QT_QPA_PLATFORM=offscreen` (defensive contra ambientes sem display).
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        yield
        return
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.SystemScope,
        str(tmp_path / "sys"),
    )
    # O app constroi QSettings("systemForge", "workflow-app") SEM passar format,
    # entao usa NativeFormat (no Linux: ~/.config/systemForge/workflow-app.conf).
    # setPath e por-formato: redirecionar so IniFormat deixava o NativeFormat
    # ler o ~/.config REAL do dev — vazando overrides (ex.: personas/label_overrides)
    # para dentro dos testes. Redirecionar tambem NativeFormat fecha o vazamento.
    QSettings.setPath(
        QSettings.Format.NativeFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    QSettings.setPath(
        QSettings.Format.NativeFormat,
        QSettings.Scope.SystemScope,
        str(tmp_path / "sys"),
    )
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    yield


@pytest.fixture
def mcp_prompt_button_factory(qtbot):
    """Factory parametrizada de MCPPromptButton (hardening T9 §9).

    Cria um parent QWidget montado e exposto via `qtbot.waitExposed`,
    instancia o botao dentro do parent e retorna o tuplo (parent, btn)
    para que o teste possa interagir tanto com a janela raiz quanto
    com o botao.

    Argumentos opcionais permitem alterar button_type, action,
    target_path, agent_name/path, label, prompt e radio_state_getter.
    """
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    from workflow_app.widgets.mcp_prompt_button import MCPPromptButton

    def _make(
        button_type: str = "Claude",
        action: str = "Executar",
        target_path: str | None = "terminal-interactive-output",
        agent_name: str | None = "claude-coder",
        agent_path: str | None = "ai-forge/MCP/agents/claude-coder.md",
        radio_state_getter=None,
        label: str = "test-btn",
        prompt: str = "STUB",
        testid_slug: str | None = "test-slug",
    ):
        parent = QWidget()
        layout = QHBoxLayout(parent)
        if button_type == "Codex":
            target_path = "terminal-codex-output"
        btn = MCPPromptButton(
            label=label,
            button_type=button_type,
            prompt=prompt,
            agent_name=agent_name,
            agent_path=agent_path,
            action=action,
            target_path=target_path,
            testid_slug=testid_slug,
            radio_state_getter=radio_state_getter,
            parent=parent,
        )
        layout.addWidget(btn)
        qtbot.addWidget(parent)
        parent.show()
        qtbot.waitExposed(parent)
        return parent, btn

    return _make


@pytest.fixture
def mock_terminal_widget(qtbot):
    """Cria QPlainTextEdit OFF-SCREEN visivel (testid `terminal-codex-output`).

    Hardening T9 §3: o gate `_codex_target_alive` exige isVisibleTo(root) +
    isinstance(QPlainTextEdit|QTextEdit) + shiboken6.isValid. Mock invisivel
    via `WA_DontShowOnScreen` falha o gate (isVisibleTo retorna False).
    Solucao canonica: geometry off-screen (-10000, -10000) com show() real.
    """
    from PySide6.QtWidgets import QFrame, QPlainTextEdit

    root = QFrame()
    root.setObjectName("mock-terminal-root")
    root.setGeometry(-10000, -10000, 640, 480)
    term = QPlainTextEdit(root)
    term.setProperty("testid", "terminal-codex-output")
    term.setObjectName("mock-terminal-codex-output")
    root.show()
    qtbot.waitExposed(root)
    qtbot.addWidget(root)
    return root, term


@pytest.fixture
def frozen_clock(monkeypatch):
    """Mocka `time.monotonic_ns()` para testes de debounce <50ms.

    Hardening T9 §5: 30 testes x 800ms real = 24s desperdicados. O modulo
    `mcp_prompt_button` faz `time.monotonic_ns()` (acesso via attribute,
    nao import direto), entao patcheamos o atributo no objeto `time`
    importado dentro do modulo do widget.
    """
    import workflow_app.widgets.mcp_prompt_button as mod

    state = {"ns": 1_000_000_000}

    def _fake_monotonic_ns() -> int:
        return state["ns"]

    monkeypatch.setattr(mod.time, "monotonic_ns", _fake_monotonic_ns)

    def advance_ms(ms: int) -> None:
        state["ns"] += ms * 1_000_000

    advance_ms.state = state  # type: ignore[attr-defined]
    return advance_ms


@pytest.fixture
def codex_alive_factory(monkeypatch):
    """Monkeypatch granular de `MCPPromptButton._codex_target_alive`.

    Hardening T9 §10: testes de Codex blocking nao precisam subir T3 real
    em cada caso - substituem por funcao constante True/False. Como o
    cache `_codex_alive_cache` e populado preguicosamente, o caller deve
    chamar `codex_alive_factory(...)` ANTES de instanciar o botao para
    garantir que a primeira leitura do cache pegue o valor mockado.
    """
    from workflow_app.widgets.mcp_prompt_button import MCPPromptButton

    def _set(alive: bool) -> None:
        monkeypatch.setattr(
            MCPPromptButton,
            "_codex_target_alive",
            lambda self: alive,
        )

    return _set


# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_engine():
    """Session-scoped in-memory SQLite engine shared across all DB tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Enable foreign keys in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Function-scoped database session with automatic rollback via SAVEPOINT.

    Uses nested transactions so each test runs in isolation without
    recreating the schema.
    """
    connection = db_engine.connect()
    # Begin outer transaction
    transaction = connection.begin()
    # Create a SAVEPOINT for nested transaction
    nested = connection.begin_nested()

    Session = sessionmaker(bind=connection, expire_on_commit=False)
    session = Session()

    # Restart the nested transaction if it ends (e.g. after flush)
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if not trans.nested and trans is not nested:
            return
        nested = connection.begin_nested()

    yield session

    session.close()
    # Roll back to the savepoint, then roll back the outer transaction
    transaction.rollback()
    connection.close()


@pytest.fixture
def tmp_db_manager(tmp_path):
    """Function-scoped DatabaseManager using a temporary on-disk SQLite file."""
    db_path = tmp_path / "test_workflow.db"
    manager = DatabaseManager()
    manager.setup(db_path=str(db_path))
    yield manager
    manager.close()
