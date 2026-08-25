"""Hardening do dispatch da grade brainstorm (PR1 (b) e (d)).

Dois furos que so aparecem no caminho de publicacao, depois do picker:

- (b) o `.md` escolhido pode sumir entre o clique no picker e o clique no
  botao da grade. O prompt saia com `{target-path}` apontando para um arquivo
  morto e o erro so aparecia no LLM.
- (d) `targets` tinha que ter exatamente um elemento (os radios T1/T2/T3 sao
  exclusivos). Com 2+, o laco publicava em varios terminais e reportava
  `dispatch_result` com base no ultimo alvo - publicacao parcial silenciosa.

Usa o mesmo padrao de stub de `test_brainstorm_mcp_grade.py`: chama o slot
desatachado da classe, sem construir a MainWindow inteira.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.main_window import MainWindow

pytestmark = pytest.mark.timeout(10)


class _Radio:
    """Stub minimo de QRadioButton: so `isChecked()` e lido pelo slot."""

    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:  # noqa: N802 (espelha a API do Qt)
        return self._checked


class _Stub:
    _prompt_in_flight = False

    def __init__(self, repo_root: Path, md_path: str | None) -> None:
        self._fake_root = repo_root
        self._brainstorm_md_path = md_path
        self.publish_calls: list[tuple[str, int]] = []

    # ---- superficie consumida por _on_mcp_prompt_requested ----------------

    def _systemforge_root(self) -> Path:
        return self._fake_root

    def _current_llm_provider(self) -> str:
        return "claude"

    def _rel_to_root(self, p: str) -> str:
        return "blacksmith/brainstorm-mcp/ideia.md"

    def _codex_terminal_available(self) -> bool:
        return True

    def _publish_to_specific_terminal(self, text: str, terminal: int) -> bool:
        self.publish_calls.append((text, terminal))
        return True

    _clear_brainstorm_md_selection = MainWindow._clear_brainstorm_md_selection


def _install_fakes(monkeypatch):
    """Neutraliza QTimer/signal_bus/build_prompt e devolve os buses capturados."""
    import workflow_app.main_window as mw

    toasts: list[tuple[str, str]] = []
    results: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        mw, "QTimer",
        type("QT", (), {"singleShot": staticmethod(lambda ms, fn: None)}),
    )
    monkeypatch.setattr(mw, "signal_bus", type("SB", (), {
        "toast_requested": type(
            "T", (), {"emit": staticmethod(lambda m, lvl: toasts.append((m, lvl)))},
        )(),
        "dispatch_result": type(
            "D", (), {"emit": staticmethod(lambda b, ok: results.append((b, ok)))},
        )(),
    })())
    monkeypatch.setattr(mw, "build_prompt", lambda meta, md_ref, root: "PROMPT FINAL")
    return toasts, results


_PAYLOAD = {
    "button_id": "mcp-prompt-btn-otimizar",
    "label": "Otimizar",
    "action": "Otimizar",
    "agent_name": "x",
    "agent_path": "agents/x.md",
    "button_type": "Claude",
    "target_path": "terminal-interactive-output",
    "target_path_edit_inplace": True,
}


def test_dispatch_aborts_when_selected_md_vanished(monkeypatch, tmp_path):
    """PR1(b): `.md` apagado depois da selecao aborta antes de publicar."""
    toasts, results = _install_fakes(monkeypatch)
    fantasma = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    stub = _Stub(tmp_path, str(fantasma))  # nunca criado em disco

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert stub.publish_calls == []
    assert results == [("mcp-prompt-btn-otimizar", False)]
    assert [m for m, lvl in toasts if lvl == "warning" and "nao existe mais" in m]
    # Selecao morta e limpa: o proximo clique nao repete o mesmo erro.
    assert stub._brainstorm_md_path is None


def test_dispatch_publishes_when_selected_md_exists(monkeypatch, tmp_path):
    """Controle do teste acima: com o arquivo em disco a publicacao acontece."""
    toasts, results = _install_fakes(monkeypatch)
    real = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    real.parent.mkdir(parents=True)
    real.write_text("# ideia\n", encoding="utf-8")
    stub = _Stub(tmp_path, str(real))

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert stub.publish_calls == [("PROMPT FINAL", 1)]
    assert results == [("mcp-prompt-btn-otimizar", True)]
    assert stub._brainstorm_md_path == str(real)


def test_dispatch_aborts_on_ambiguous_route(monkeypatch, tmp_path):
    """PR1(d): 2+ terminais marcados abortam inteiro, sem publicacao parcial."""
    toasts, results = _install_fakes(monkeypatch)
    real = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    real.parent.mkdir(parents=True)
    real.write_text("# ideia\n", encoding="utf-8")
    stub = _Stub(tmp_path, str(real))
    stub._chk_route_t1 = _Radio(True)
    stub._chk_route_t2 = _Radio(True)
    stub._chk_route_t3 = _Radio(False)

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert stub.publish_calls == []
    assert results == [("mcp-prompt-btn-otimizar", False)]
    assert [m for m, lvl in toasts if lvl == "error" and "Rota de terminal ambigua" in m]


def test_dispatch_single_route_still_publishes(monkeypatch, tmp_path):
    """Rota unica (o caso real dos radios exclusivos) segue publicando."""
    toasts, results = _install_fakes(monkeypatch)
    real = tmp_path / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    real.parent.mkdir(parents=True)
    real.write_text("# ideia\n", encoding="utf-8")
    stub = _Stub(tmp_path, str(real))
    stub._chk_route_t1 = _Radio(False)
    stub._chk_route_t2 = _Radio(True)
    stub._chk_route_t3 = _Radio(False)

    MainWindow._on_mcp_prompt_requested(stub, dict(_PAYLOAD))  # type: ignore[arg-type]

    assert stub.publish_calls == [("PROMPT FINAL", 2)]
    assert results == [("mcp-prompt-btn-otimizar", True)]
