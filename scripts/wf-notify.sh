#!/usr/bin/env bash
# wf-notify.sh — invoca notify-terminal-idle.py por path absoluto, com canal
# validado e independente de cwd. Chamado pelo bloco canonico do "autocast
# contract" no fim de cada comando-skill (ver CONTRACT.md).
#
# Contrato:
#   - Argumento posicional 1 (preferido): canal "interactive" ou "workspace".
#   - Fallback: WF_CHANNEL_OVERRIDE (env) — usado pelo wrapper Kimi.
#   - WF_CHANNEL (env) e ignorado por seguranca: bleed entre PTYs reaproveitados.
#   - Default seguro: "interactive".
#   - Stderr visivel; exit code nao zero em falha — caller decide se bloqueia.

set -u

wf_err() {
  printf 'wf-notify: %s\n' "$1" >&2
}

find_repo_root() {
  local dir="$1"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/.claude/commands" ] && [ -d "$dir/ai-forge" ] && [ -f "$dir/CLAUDE.md" ]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="${dir%/*}"
    [ -n "$dir" ] || dir="/"
  done
  return 1
}

channel="${1:-${WF_CHANNEL_OVERRIDE:-interactive}}"
case "$channel" in
  interactive|workspace) ;;
  *)
    wf_err "invalid channel '$channel' (expected: interactive|workspace)"
    exit 2
    ;;
esac

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="." ;;
esac

script_dir="$(CDPATH= cd -- "$script_dir" && pwd -P)" || {
  wf_err "cannot resolve script directory from ${BASH_SOURCE[0]}"
  exit 1
}

repo_root="$(find_repo_root "$script_dir")" || {
  wf_err "SystemForge root not found above $script_dir"
  exit 1
}

notify_py="$repo_root/ai-forge/workflow-app/scripts/notify-terminal-idle.py"
if [ ! -f "$notify_py" ]; then
  wf_err "notify script not found: $notify_py"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  wf_err "python3 not found in PATH"
  exit 1
fi

python3 "$notify_py" "$channel"
