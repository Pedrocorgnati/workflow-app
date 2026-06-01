"""Tests for wf-notify.sh wrapper — autocast contract hardening.

Cobre as quatro fragilidades resolvidas pelo wrapper:
- cwd drift: caller fora do repo deve falhar visivel sem corromper estado
- WF_CHANNEL bleed: env var WF_CHANNEL e ignorada (wrapper aceita so arg
  posicional ou WF_CHANNEL_OVERRIDE)
- fail-closed: --status e obrigatorio para nao converter estado ambiguo em
  success legado
- script ausente / python ausente: erro visivel em stderr, exit nao zero
- override Kimi/Codex: WF_CHANNEL_OVERRIDE=workspace/workspace_xterm vence
  default interactive
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = REPO_ROOT / "ai-forge/workflow-app/scripts/wf-notify.sh"
NOTIFY_PY = REPO_ROOT / "ai-forge/workflow-app/scripts/notify-terminal-idle.py"


def _read_notify_payload(channel: str, notify_dir: Path) -> dict | None:
    f = notify_dir / f"terminal-notify-{channel}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(WRAPPER), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Aponta HOME para tmp para que ~/.workflow-app/ seja sandboxado."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


_TEST_SESSION_ID = "session-test"


@pytest.fixture
def base_env(isolated_home):
    env = os.environ.copy()
    env["HOME"] = str(isolated_home)
    # Garantir que nao herda WF_CHANNEL ou OVERRIDE do shell do CI
    env.pop("WF_CHANNEL", None)
    env.pop("WF_CHANNEL_OVERRIDE", None)
    # Pin session ID so tests know where to find the notify files.
    env["WF_APP_SESSION_ID"] = _TEST_SESSION_ID
    return env


def _notify_dir(home: Path) -> Path:
    """Return the per-session IPC directory for tests."""
    return home / ".workflow-app" / _TEST_SESSION_ID


def test_wrapper_exists_and_executable():
    assert WRAPPER.is_file()
    assert os.access(WRAPPER, os.X_OK)


def test_missing_status_is_rejected(base_env, isolated_home):
    """Sem --status, o wrapper falha fechado e nao escreve verde legado."""
    proc = _run(["interactive"], cwd=REPO_ROOT, env=base_env)
    assert proc.returncode == 2
    assert "--status e obrigatorio" in proc.stderr
    assert _read_notify_payload("interactive", _notify_dir(isolated_home)) is None


def test_default_channel_is_interactive(base_env, isolated_home):
    """Com status explicito e sem channel, default = interactive."""
    proc = _run(["--status", "success"], cwd=REPO_ROOT, env=base_env)
    assert proc.returncode == 0, proc.stderr
    payload = _read_notify_payload("interactive", _notify_dir(isolated_home))
    assert payload is not None
    assert payload["channel"] == "interactive"
    assert payload["state"] == "idle"


def test_explicit_channel_arg_wins(base_env, isolated_home):
    """Arg posicional explicito wins."""
    proc = _run(["--status", "success", "workspace"], cwd=REPO_ROOT, env=base_env)
    assert proc.returncode == 0, proc.stderr
    payload = _read_notify_payload("workspace", _notify_dir(isolated_home))
    assert payload is not None
    assert payload["channel"] == "workspace"


def test_invalid_channel_rejected(base_env):
    """Canal desconhecido falha com exit 2 e stderr visivel."""
    proc = _run(["bogus"], cwd=REPO_ROOT, env=base_env)
    assert proc.returncode == 2
    assert "invalid channel" in proc.stderr


def test_wf_channel_env_is_ignored_bleed_proof(base_env, isolated_home):
    """WF_CHANNEL=workspace no env NAO deve afetar — wrapper so olha arg + OVERRIDE."""
    env = dict(base_env)
    env["WF_CHANNEL"] = "workspace"  # bleed do PTY
    # Sem arg, sem OVERRIDE — deve cair no default interactive, NUNCA workspace
    proc = _run(["--status", "success"], cwd=REPO_ROOT, env=env)
    assert proc.returncode == 0, proc.stderr
    nd = _notify_dir(isolated_home)
    interactive = _read_notify_payload("interactive", nd)
    workspace = _read_notify_payload("workspace", nd)
    assert interactive is not None and interactive["channel"] == "interactive"
    assert workspace is None, "WF_CHANNEL bleed: workspace foi escrito quando nao deveria"


def test_wf_channel_override_wins(base_env, isolated_home):
    """WF_CHANNEL_OVERRIDE=workspace vence o default e ignora WF_CHANNEL."""
    env = dict(base_env)
    env["WF_CHANNEL"] = "interactive"
    env["WF_CHANNEL_OVERRIDE"] = "workspace"
    proc = _run(["--status", "success"], cwd=REPO_ROOT, env=env)
    assert proc.returncode == 0, proc.stderr
    workspace = _read_notify_payload("workspace", _notify_dir(isolated_home))
    assert workspace is not None
    assert workspace["channel"] == "workspace"


def test_wf_channel_override_workspace_xterm_writes_t3(base_env, isolated_home):
    """WF_CHANNEL_OVERRIDE=workspace_xterm escreve o arquivo IPC do T3."""
    env = dict(base_env)
    env["WF_CHANNEL"] = "interactive"
    env["WF_CHANNEL_OVERRIDE"] = "workspace_xterm"
    proc = _run(["--status", "success"], cwd=REPO_ROOT, env=env)
    assert proc.returncode == 0, proc.stderr
    nd = _notify_dir(isolated_home)
    t3_payload = _read_notify_payload("workspace-xterm", nd)
    assert t3_payload is not None
    assert t3_payload["channel"] == "workspace_xterm"
    assert t3_payload["state"] == "idle"
    assert not (nd / "terminal-notify-workspace_xterm.json").exists()


def test_wf_app_session_id_controls_notify_dir(isolated_home):
    """WF_APP_SESSION_ID determina em qual subdiretorio o arquivo IPC e escrito.

    Isso e o contrato de isolamento entre instancias abertas em paralelo:
    cada processo do workflow-app injeta seu proprio WF_APP_SESSION_ID no
    PTY, garantindo que wf-notify.sh escreva em ~/.workflow-app/<session>/
    ao inves de um path global compartilhado.
    """
    env = os.environ.copy()
    env["HOME"] = str(isolated_home)
    env.pop("WF_CHANNEL", None)
    env.pop("WF_CHANNEL_OVERRIDE", None)

    session_a = "session-11111"
    session_b = "session-22222"

    # Instancia A escreve em sua sessao
    env_a = dict(env)
    env_a["WF_APP_SESSION_ID"] = session_a
    proc_a = _run(["--status", "success", "interactive"], cwd=REPO_ROOT, env=env_a)
    assert proc_a.returncode == 0, proc_a.stderr

    # Instancia B escreve em sua propria sessao
    env_b = dict(env)
    env_b["WF_APP_SESSION_ID"] = session_b
    proc_b = _run(
        ["--status", "failure", "--reason", "VERIFY_FAILED", "interactive"],
        cwd=REPO_ROOT,
        env=env_b,
    )
    assert proc_b.returncode == 0, proc_b.stderr

    # Sessao A tem success; sessao B tem failure — sem cross-contamination
    payload_a = _read_notify_payload(
        "interactive", isolated_home / ".workflow-app" / session_a
    )
    payload_b = _read_notify_payload(
        "interactive", isolated_home / ".workflow-app" / session_b
    )

    assert payload_a is not None
    assert payload_a["state"] == "idle", "sessao A deve ter state=idle (success)"

    assert payload_b is not None
    assert payload_b["state"] == "failed", "sessao B deve ter state=failed (failure)"

    # Cross-contamination check: sessao A nao deve ter sido afetada pelo write de B
    assert payload_a["state"] != "failed", "sessao A foi contaminada pela sessao B"


def test_fallback_session_default_when_no_env(isolated_home):
    """Quando WF_APP_SESSION_ID nao esta no env (CI headless, invocacao manual),
    o script cai para 'session-default' e nao aborta."""
    env = os.environ.copy()
    env["HOME"] = str(isolated_home)
    env.pop("WF_CHANNEL", None)
    env.pop("WF_CHANNEL_OVERRIDE", None)
    env.pop("WF_APP_SESSION_ID", None)

    proc = _run(["--status", "success", "interactive"], cwd=REPO_ROOT, env=env)
    assert proc.returncode == 0, proc.stderr

    fallback_dir = isolated_home / ".workflow-app" / "session-default"
    payload = _read_notify_payload("interactive", fallback_dir)
    assert payload is not None
    assert payload["state"] == "idle"


def test_override_env_overrides_explicit_arg(base_env, isolated_home):
    """WF_CHANNEL_OVERRIDE e fonte de verdade do PTY real."""
    proc = _run(
        ["--status", "success", "interactive"],
        cwd=REPO_ROOT,
        env=base_env | {"WF_CHANNEL_OVERRIDE": "workspace"},
    )
    assert proc.returncode == 0, proc.stderr
    workspace = _read_notify_payload("workspace", _notify_dir(isolated_home))
    assert workspace is not None
    assert workspace["channel"] == "workspace"


def test_cwd_drift_does_not_affect_resolution(base_env, isolated_home, tmp_path):
    """Wrapper invocado de qualquer cwd (fora do repo) ainda resolve repo via BASH_SOURCE."""
    drift_dir = tmp_path / "elsewhere"
    drift_dir.mkdir()
    proc = _run(["--status", "success", "interactive"], cwd=drift_dir, env=base_env)
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    payload = _read_notify_payload("interactive", _notify_dir(isolated_home))
    assert payload is not None


def test_missing_python3_visible_error(base_env, isolated_home, tmp_path):
    """Sem python3 no PATH (mas com bash), erro visivel em stderr, exit nao zero."""
    # Cria PATH minimo com bash + utilitarios coreutils, mas sem python3.
    sandbox_bin = tmp_path / "bin"
    sandbox_bin.mkdir()
    for tool in ("bash", "env", "cd", "pwd", "ls", "cat", "command", "printf", "test"):
        src = shutil.which(tool)
        if src:
            os.symlink(src, sandbox_bin / tool)
    env = dict(base_env)
    env["PATH"] = str(sandbox_bin)
    proc = _run(["--status", "success"], cwd=REPO_ROOT, env=env)
    assert proc.returncode != 0
    assert "python3 not found" in proc.stderr


def test_missing_notify_script_visible_error(base_env, isolated_home, tmp_path, monkeypatch):
    """Se notify-terminal-idle.py some, wrapper grita stderr e retorna nao zero."""
    notify_backup = NOTIFY_PY.with_suffix(".py.bak_test")
    shutil.move(str(NOTIFY_PY), str(notify_backup))
    try:
        proc = _run(["--status", "success"], cwd=REPO_ROOT, env=base_env)
        assert proc.returncode != 0
        assert "notify script not found" in proc.stderr
    finally:
        shutil.move(str(notify_backup), str(NOTIFY_PY))


def test_canonical_block_pattern_works_under_cwd_drift(base_env, isolated_home, tmp_path):
    """Simula o bloco canonico do template completo: walk-up + invoke wrapper."""
    drift_dir = tmp_path / "deep" / "subdir"
    drift_dir.mkdir(parents=True)
    block = r'''
wf_channel="${WF_CHANNEL_OVERRIDE:-interactive}"
wf_root="$PWD"
while [ "$wf_root" != "/" ] && { [ ! -d "$wf_root/.claude/commands" ] || [ ! -d "$wf_root/ai-forge" ] || [ ! -f "$wf_root/CLAUDE.md" ]; }; do
  wf_root="${wf_root%/*}"
  [ -n "$wf_root" ] || wf_root="/"
done
if [ "$wf_root" = "/" ]; then
  printf 'wf-notify: repo root not found from %s\n' "$PWD" >&2
  exit 0
elif ! "${BASH:-bash}" "$wf_root/ai-forge/workflow-app/scripts/wf-notify.sh" --status success "$wf_channel"; then
  printf 'wf-notify: non-blocking failure for channel=%s\n' "$wf_channel" >&2
fi
'''
    # Caso A: cwd dentro do repo (subpath profundo) -> walk-up acha root
    deep_in_repo = REPO_ROOT / "ai-forge" / "workflow-app" / "scripts"
    proc = subprocess.run(
        ["bash", "-c", block],
        cwd=str(deep_in_repo),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    payload = _read_notify_payload("interactive", _notify_dir(isolated_home))
    assert payload is not None, "bloco canonico falhou em escrever notify a partir de subpath do repo"

    # Caso B: cwd FORA do repo (drift total) -> walk-up para em / sem repo, mas exit 0
    proc2 = subprocess.run(
        ["bash", "-c", block],
        cwd=str(drift_dir),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc2.returncode == 0
    assert "repo root not found" in proc2.stderr
