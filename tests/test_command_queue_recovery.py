"""Tests for the listener-recovery dispatch handler.

Loop 06-01-listener-recovery-command, TASK 08 (handler-dispatch-command-queue).

Cobre os 5 casos de roteamento do handler `_on_request_recovery_command`:
  - T1 interactive + Claude -> slash cru (run_command_in_terminal)
  - T1 interactive + Codex  -> _build_codex_slash_executor_prompt(interactive)
  - T1 interactive + Kimi   -> /skill:slash-executor + slash cru
  - T2 workspace            -> Kimi blue-arrow (kimi_blue_arrow_dispatched)
  - T3 workspace_xterm      -> _build_codex_slash_executor_prompt(workspace_xterm)

Mais o gate do aceite: o builder PURO `build_recovery_prompt` NUNCA retorna
string iniciada por `/tools:listener-recovery` (o roteamento vive no handler,
nao no builder), e os 3 casos de violacao de contrato (canal, reason,
context-file) que produzem toast warning + failure/BLOCKED sem colar comando.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible
from workflow_app.metrics_bar.recovery_prompt import build_recovery_prompt
from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture()
def ctx_file(tmp_path: Path) -> str:
    """Snapshot diagnostico valido (existe em disco + termina em .md)."""
    p = tmp_path / "interactive-BLOCKED-snapshot.md"
    p.write_text("# recovery snapshot\n", encoding="utf-8")
    return str(p)


class _Recorder:
    """Coleta emissoes dos signals de dispatch/feedback e desconecta no fim."""

    def __init__(self) -> None:
        self.interactive: list[str] = []
        self.xterm: list[str] = []
        self.kimi_blue: list[tuple[str, int]] = []
        self.toast: list[tuple[str, str]] = []
        self.force_failed: list[tuple[str, str]] = []
        self._wires = [
            (signal_bus.run_command_in_terminal, self._on_t1),
            (signal_bus.run_command_in_workspace_xterm, self._on_t3),
            (signal_bus.kimi_blue_arrow_dispatched, self._on_blue),
            (signal_bus.toast_requested, self._on_toast),
            (signal_bus.terminal_force_failed, self._on_failed),
        ]
        for sig, slot in self._wires:
            sig.connect(slot)

    def _on_t1(self, cmd: str) -> None:
        self.interactive.append(cmd)

    def _on_t3(self, cmd: str) -> None:
        self.xterm.append(cmd)

    def _on_blue(self, prompt: str, delay: int) -> None:
        self.kimi_blue.append((prompt, delay))

    def _on_toast(self, msg: str, kind: str) -> None:
        self.toast.append((msg, kind))

    def _on_failed(self, channel: str, reason: str) -> None:
        self.force_failed.append((channel, reason))

    def disconnect(self) -> None:
        for sig, slot in self._wires:
            sig.disconnect(slot)


@pytest.fixture()
def rec() -> _Recorder:
    r = _Recorder()
    try:
        yield r
    finally:
        r.disconnect()


# ─────────────────────────── 5 casos de roteamento ─────────────────────────── #


class TestRecoveryDispatchRouting:
    def test_t1_interactive_claude_raw_slash(self, widget, rec, ctx_file):
        """T1 Claude (default): cola o slash CRU no terminal interactive."""
        # Claude e o default: nem Main Codex radio nem force-Kimi marcados.
        widget._on_request_recovery_command("interactive", "BLOCKED", ctx_file)

        assert len(rec.interactive) == 1
        payload = rec.interactive[0]
        assert payload == (
            f"/tools:listener-recovery --channel interactive "
            f"--reason BLOCKED --context-file {ctx_file}"
        )
        # nenhum outro canal recebeu dispatch
        assert rec.xterm == []
        assert rec.kimi_blue == []
        assert rec.force_failed == []

    def test_t1_interactive_codex_executor_prompt(self, widget, rec, ctx_file):
        """T1 Codex: transforma via _build_codex_slash_executor_prompt(interactive)."""
        widget._main_codex_radio.setChecked(True)
        widget._on_request_recovery_command("interactive", "VERIFY_FAILED", ctx_file)

        assert len(rec.interactive) == 1
        payload = rec.interactive[0]
        # prompt do executor Codex, nao o slash cru
        assert not payload.startswith("/tools:listener-recovery")
        assert "Expected listener channel: interactive" in payload
        assert (
            "Command: /tools:listener-recovery --channel interactive "
            "--reason VERIFY_FAILED" in payload
        )
        assert rec.xterm == []
        assert rec.kimi_blue == []

    def test_t1_interactive_kimi_slash_executor(self, widget, rec, ctx_file):
        """T1 Kimi: prefixa /skill:slash-executor antes do slash cru."""
        widget._force_kimi_chk.setChecked(True)
        widget._on_request_recovery_command("interactive", "RESSALVAS", ctx_file)

        assert len(rec.interactive) == 1
        payload = rec.interactive[0]
        assert payload == (
            f"/skill:slash-executor /tools:listener-recovery "
            f"--channel interactive --reason RESSALVAS --context-file {ctx_file}"
        )
        assert rec.xterm == []
        assert rec.kimi_blue == []

    def test_t2_workspace_kimi_blue_arrow(self, widget, rec, ctx_file):
        """T2 workspace: dispara a seta azul do Kimi (kimi_blue_arrow_dispatched).

        TASK 09 (path-t2-kimi-blue-arrow): o recovery do canal workspace e
        despachado via kimi_blue_arrow_dispatched(payload, 1000) por caminho
        dedicado (_dispatch_blue_arrow), com o delay DEFAULT preservado. Aqui o
        dispatch nao foi precedido de /clear, entao o delay e exatamente o
        default (_KIMI_BLUE_ARROW_DEFAULT_DELAY_MS == 1000), nao apenas > 0.
        """
        widget._on_request_recovery_command("workspace", "EXIT_NONZERO", ctx_file)

        assert len(rec.kimi_blue) == 1
        prompt, delay = rec.kimi_blue[0]
        assert prompt == (
            f"/skill:slash-executor /tools:listener-recovery "
            f"--channel workspace --reason EXIT_NONZERO --context-file {ctx_file}"
        )
        # Delay DEFAULT preservado: exatamente 1000ms (sem /clear previo).
        assert delay == CommandQueueWidget._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS
        assert delay == 1000
        # NAO foi para o terminal interactive nem xterm
        assert rec.interactive == []
        assert rec.xterm == []

    def test_t3_workspace_xterm_codex_executor(self, widget, rec, ctx_file):
        """T3 workspace_xterm: executor Codex com listener_channel=workspace_xterm."""
        widget._on_request_recovery_command("workspace_xterm", "TIMEOUT", ctx_file)

        assert len(rec.xterm) == 1
        payload = rec.xterm[0]
        assert not payload.startswith("/tools:listener-recovery")
        assert "Expected listener channel: workspace_xterm" in payload
        assert (
            "Command: /tools:listener-recovery --channel workspace_xterm "
            "--reason TIMEOUT" in payload
        )
        assert rec.interactive == []
        assert rec.kimi_blue == []


# ───────────── gate do aceite TASK 09: sem regressao de whitelist ───────────── #


class TestRecoveryWorkspaceIndependentOfWhitelist:
    """TASK 09: o recovery sintetico do canal workspace NAO pode regredir
    introduzindo dependencia de KIMI_COMPATIBLE_COMMANDS.

    O fire do red-listener nao e item de fila: ele dispara o blue-arrow
    diretamente por caminho dedicado (_dispatch_blue_arrow). O slash de
    recovery `/tools:listener-recovery` NAO esta (e nao deve estar) na
    whitelist de itens elegiveis a Kimi; ainda assim o dispatch tem que
    acontecer. Este gate trava qualquer futura introducao de um gate
    is_kimi_compatible/whitelist no caminho do recovery sintetico.
    """

    def test_recovery_slash_is_not_whitelisted_precondition(self):
        """Precondicao: o slash de recovery NAO esta na whitelist Kimi.

        Sem isso, o teste de no-regressao abaixo seria vacuamente verdadeiro.
        """
        assert is_kimi_compatible("/tools:listener-recovery") is False
        assert (
            is_kimi_compatible(
                "/tools:listener-recovery --channel workspace "
                "--reason EXIT_NONZERO --context-file /tmp/x.md"
            )
            is False
        )

    def test_workspace_recovery_dispatches_despite_non_whitelisted_slash(
        self, widget, rec, ctx_file
    ):
        """O blue-arrow do recovery workspace dispara mesmo o slash NAO sendo
        whitelisted — prova de que o caminho dedicado nao consulta a whitelist.
        """
        # Sanidade: o payload carrega o slash que comprovadamente nao e Kimi-compativel.
        assert is_kimi_compatible("/tools:listener-recovery") is False

        widget._on_request_recovery_command("workspace", "EXIT_NONZERO", ctx_file)

        # Dispatch aconteceu apesar do slash fora da whitelist.
        assert len(rec.kimi_blue) == 1
        prompt, delay = rec.kimi_blue[0]
        assert "/tools:listener-recovery --channel workspace" in prompt
        assert delay == CommandQueueWidget._KIMI_BLUE_ARROW_DEFAULT_DELAY_MS

    def test_recovery_skill_alias_exists_outside_whitelist(self):
        """O alias Kimi do recovery vive em .agents/skills/ mas NAO entra na
        whitelist migration-backed (SC47 em claude-to-kimi/progress.md = 41,
        KEEP_CLAUDE, below-threshold). TestSkillFilesExist em
        test_kimi_whitelist.py so itera a whitelist, logo NAO cobre este alias.
        Este gate impede que o alias seja deletado silenciosamente, o que
        deixaria o dispatch interactive+Kimi (`/skill:slash-executor
        /tools:listener-recovery ...`) sem skill resolvivel pelo Kimi CLI.
        """
        cur = Path(__file__).resolve()
        repo_root = next(
            (p for p in cur.parents if (p / "CLAUDE.md").is_file()), None
        )
        assert repo_root is not None, "repo root (CLAUDE.md) nao encontrado"
        alias = repo_root / ".agents" / "skills" / "tools:listener-recovery.md"
        assert alias.is_file(), f"alias de recovery ausente: {alias}"


# ─────────────────────── gate do aceite: builder puro ──────────────────────── #


class TestBuilderDoesNotReintroduceRouting:
    @pytest.mark.parametrize("llm", ["claude", "codex", "kimi"])
    @pytest.mark.parametrize(
        "channel", ["interactive", "workspace", "workspace_xterm"]
    )
    @pytest.mark.parametrize(
        "reason",
        ["BLOCKED", "RESSALVAS", "VERIFY_FAILED", "EXIT_NONZERO", "MISSING_ARG", "TIMEOUT"],
    )
    def test_build_recovery_prompt_never_starts_with_command(
        self, llm, channel, reason
    ):
        """O builder PURO nao pode reintroduzir o roteamento (slash cru)."""
        p = build_recovery_prompt(llm=llm, reason=reason, channel=channel)
        assert not p.lstrip().startswith("/tools:listener-recovery")


# ──────────────────────── violacoes de contrato ────────────────────────────── #


class TestRecoveryContractViolations:
    def test_invalid_channel_toast_only_no_dispatch(self, widget, rec, ctx_file):
        """Canal invalido: toast warning, sem dot para falhar, sem dispatch."""
        widget._on_request_recovery_command("bogus", "BLOCKED", ctx_file)

        assert rec.interactive == []
        assert rec.xterm == []
        assert rec.kimi_blue == []
        assert rec.force_failed == []  # canal invalido -> nenhum dot falha
        assert any(kind == "warning" for _msg, kind in rec.toast)

    def test_invalid_reason_warns_and_blocks_channel(self, widget, rec, ctx_file):
        """Reason fora de RECOVERY_REASONS: toast warning + failure/BLOCKED no canal."""
        widget._on_request_recovery_command("interactive", "FAILURE", ctx_file)

        assert rec.interactive == []
        assert ("interactive", "BLOCKED") in rec.force_failed
        assert any(kind == "warning" for _msg, kind in rec.toast)

    def test_missing_context_file_warns_and_blocks(self, widget, rec):
        """context-file inexistente: toast warning + failure/BLOCKED, sem paste."""
        widget._on_request_recovery_command(
            "workspace_xterm", "BLOCKED", "/nope/does-not-exist.md"
        )

        assert rec.xterm == []
        assert ("workspace_xterm", "BLOCKED") in rec.force_failed
        assert any(kind == "warning" for _msg, kind in rec.toast)

    def test_non_md_context_file_rejected(self, widget, rec, tmp_path):
        """context-file que nao termina em .md e rejeitado."""
        bad = tmp_path / "snapshot.txt"
        bad.write_text("x", encoding="utf-8")
        widget._on_request_recovery_command("interactive", "BLOCKED", str(bad))

        assert rec.interactive == []
        assert ("interactive", "BLOCKED") in rec.force_failed


# ───────────────────────── wiring do sinal (bus) ───────────────────────────── #


class TestRecoverySignalWiring:
    def test_handler_connected_to_request_recovery_command(
        self, widget, rec, ctx_file
    ):
        """Emitir o sinal pelo bus aciona o handler (conexao de _connect_signals)."""
        signal_bus.request_recovery_command.emit("interactive", "BLOCKED", ctx_file)

        assert len(rec.interactive) == 1
        assert rec.interactive[0].startswith("/tools:listener-recovery")
