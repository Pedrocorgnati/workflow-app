#!/usr/bin/env bash
# wf-notify.sh v2 — invoca notify-terminal-idle.py por path absoluto, com canal
# validado e independente de cwd. Chamado pelo bloco canonico do "autocast
# contract" no fim de cada comando-skill (ver CONTRACT.md).
#
# Contrato canonico em ai-forge/rules/workflow-app-listeners.md §2.3:
#
#   bash wf-notify.sh --status success interactive
#   bash wf-notify.sh --status failure --reason "VERIFY_FAILED" interactive
#   bash wf-notify.sh --status awaiting_user interactive
#
# Argumentos:
#   --status <s>   enum: success | failure | awaiting_user
#                  (OMITIDO = legacy v1 — warning + comportamento de success
#                   para retrocompat dos comandos ainda nao migrados.)
#   --reason <r>   enum canonico (§2.2): VERIFY_FAILED | BLOCKED | RESSALVAS |
#                  TIMEOUT | EXIT_NONZERO | MISSING_ARG. OBRIGATORIO quando
#                  --status=failure; ignorado nos demais casos.
#   --exit-code N  inteiro (opcional). Em success vale 0; em failure vale o
#                  exit code real do comando. Default: 0/1 conforme status.
#   --run-id S     string (opcional). Default: ISO-8601 + pid se ausente.
#   <channel>      posicional: interactive | workspace.
#                  Fallback: WF_CHANNEL_OVERRIDE (env). Default: interactive.
#
# Exit codes:
#   0  -> dispatch OK (success/failure/awaiting_user — payload escrito)
#   2  -> args invalidos (channel desconhecido, status fora do enum, --reason
#         ausente em failure, --reason fora do enum). App trata exit=2 como
#         FAILURE defensivamente.
#   3  -> notify-terminal-idle.py absent/unreachable. App trata como FAILURE +
#         log loud.
#
# Stderr visivel; nunca silencia.

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

# ── Parse flags + posicionais ────────────────────────────────────────────────
status=""
reason=""
exit_code=""
run_id=""
channel=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --status)
      [ "$#" -ge 2 ] || { wf_err "--status requer valor"; exit 2; }
      status="$2"; shift 2 ;;
    --status=*)
      status="${1#--status=}"; shift ;;
    --reason)
      [ "$#" -ge 2 ] || { wf_err "--reason requer valor"; exit 2; }
      reason="$2"; shift 2 ;;
    --reason=*)
      reason="${1#--reason=}"; shift ;;
    --exit-code)
      [ "$#" -ge 2 ] || { wf_err "--exit-code requer valor"; exit 2; }
      exit_code="$2"; shift 2 ;;
    --exit-code=*)
      exit_code="${1#--exit-code=}"; shift ;;
    --run-id)
      [ "$#" -ge 2 ] || { wf_err "--run-id requer valor"; exit 2; }
      run_id="$2"; shift 2 ;;
    --run-id=*)
      run_id="${1#--run-id=}"; shift ;;
    --)
      shift; channel="${1:-}"; [ -n "$channel" ] && shift; break ;;
    -*)
      wf_err "flag desconhecida '$1'"
      exit 2 ;;
    *)
      if [ -z "$channel" ]; then
        channel="$1"
      else
        wf_err "argumento posicional extra '$1' (channel ja definido como '$channel')"
        exit 2
      fi
      shift ;;
  esac
done

# Channel fallback (env + default)
if [ -z "$channel" ]; then
  channel="${WF_CHANNEL_OVERRIDE:-interactive}"
fi
case "$channel" in
  interactive|workspace) ;;
  *)
    wf_err "invalid channel '$channel' (expected: interactive|workspace)"
    exit 2
    ;;
esac

# Status validation — v1 legacy (omitido) e tratado como success com WARN
if [ -z "$status" ]; then
  wf_err "WARNING: --status ausente (modo legacy v1). Migrar para v2: --status success|failure|awaiting_user. Veja ai-forge/rules/workflow-app-listeners.md §2.3."
  status="success"
fi
case "$status" in
  success|failure|awaiting_user) ;;
  *)
    wf_err "invalid --status '$status' (expected: success|failure|awaiting_user)"
    exit 2
    ;;
esac

# Reason validation — obrigatorio em failure, ignorado caso contrario
if [ "$status" = "failure" ]; then
  if [ -z "$reason" ]; then
    wf_err "--reason e obrigatorio quando --status=failure"
    exit 2
  fi
  case "$reason" in
    VERIFY_FAILED|BLOCKED|RESSALVAS|TIMEOUT|EXIT_NONZERO|MISSING_ARG) ;;
    *)
      wf_err "invalid --reason '$reason' (expected canonical enum, see ai-forge/rules/workflow-app-listeners.md §2.2)"
      exit 2
      ;;
  esac
else
  # Em success ou awaiting_user reason e ignorado mas nao e erro receber.
  reason=""
fi

# Exit code default
if [ -z "$exit_code" ]; then
  case "$status" in
    success) exit_code="0" ;;
    failure) exit_code="1" ;;
    awaiting_user) exit_code="0" ;;
  esac
fi

# Run id default — ISO-8601 compacto + pid
if [ -z "$run_id" ]; then
  if date_iso=$(date -u +"%Y-%m-%dT%H-%M-%SZ" 2>/dev/null); then
    run_id="${date_iso}-$$"
  else
    run_id="run-$$"
  fi
fi

# ── Resolver script Python ───────────────────────────────────────────────────
script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="." ;;
esac

script_dir="$(CDPATH= cd -- "$script_dir" && pwd -P)" || {
  wf_err "cannot resolve script directory from ${BASH_SOURCE[0]}"
  exit 3
}

repo_root="$(find_repo_root "$script_dir")" || {
  wf_err "SystemForge root not found above $script_dir"
  exit 3
}

notify_py="$repo_root/ai-forge/workflow-app/scripts/notify-terminal-idle.py"
if [ ! -f "$notify_py" ]; then
  wf_err "notify script not found: $notify_py"
  exit 3
fi

if ! command -v python3 >/dev/null 2>&1; then
  wf_err "python3 not found in PATH"
  exit 3
fi

# ── Dispatch para notify-terminal-idle.py (v2 payload via flags nomeadas) ────
python3 "$notify_py" \
  --channel "$channel" \
  --status "$status" \
  --reason "$reason" \
  --exit-code "$exit_code" \
  --run-id "$run_id"
