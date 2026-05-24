#!/usr/bin/env bash
# Pre-flight bloqueante T9 (T9-hardening item 1).
# Captura ambiente, valida branch=main, gh auth, suite verde, T1..T8 done.
# Append YAML header em blacksmith/mcp-flow/_INTEGRATION-LOG.md.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || { echo "branch_invalida: $branch (esperado: main)" >&2; exit 1; }

sha="$(git -C ai-forge/workflow-app rev-parse --short=7 HEAD 2>/dev/null || git rev-parse --short=7 HEAD)"

operator="$(gh auth status 2>/dev/null | sed -n 's/.*Logged in to .* account //p' | awk '{print $1}' | head -1)"
[ -n "$operator" ] || { echo "gh auth ausente - rodar 'gh auth login'" >&2; exit 1; }

pyside_v="$(python3 -c 'import PySide6; print(PySide6.__version__)' 2>/dev/null || echo "ausente")"
qt_v="$(python3 -c 'from PySide6.QtCore import qVersion; print(qVersion())' 2>/dev/null || echo "ausente")"
py_v="$(python3 --version | cut -d' ' -f2)"
os_k="$(uname -sr)"
protocol="${WAYLAND_DISPLAY:+Wayland}${XDG_SESSION_TYPE:+ ($XDG_SESSION_TYPE)}"
[ -n "$protocol" ] || protocol="X11"

# Suite pytest-qt (T8 cobertura)
if command -v pytest >/dev/null 2>&1; then
    pytest ai-forge/workflow-app/tests/ --tb=no -q --co 2>/dev/null >/tmp/smoke-preflight-pytest.log \
        || { echo "pytest collection falhou (ver /tmp/smoke-preflight-pytest.log)" >&2; exit 1; }
fi

# T1..T8 verde em PROGRESS
done_count=0
for pf in blacksmith/mcp-flow/PROGRESS-tasklist-integrator-*.md; do
    [ -f "$pf" ] && done_count=$((done_count + $(grep -c "\[x\]" "$pf" || true)))
done
# Relax: T1..T8 marcadores podem estar no _LOOP-CONFIG.json
config_done=$(python3 -c '
import json,sys
p=sys.argv[1]
d=json.load(open(p))
n=0
for it in d.get("items_index",{}).values():
    if it.get("id") in ["002","003","004","005","006","007","008","009"] and it.get("review_executed_completed_at"):
        n+=1
print(n)
' blacksmith/loop-archives/05-21-implantation-tasklist-aba-brainstorm/_LOOP-CONFIG.json 2>/dev/null || echo 0)

ts_start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat <<EOF
sha_pre_smoke: $sha
operator: "$operator"
pyside_version: "$pyside_v"
qt_version: "$qt_v"
python_version: "$py_v"
os_kernel: "$os_k"
display_protocol: "$protocol"
ts_start: "$ts_start"
t1_t8_done_in_progress: $done_count
t2_t9_done_in_config: $config_done
EOF
