#!/usr/bin/env bash
# daily-loop-autocast.sh — autocast unificado para /daily-loop:do e /daily-loop:review-done.
#
# Substitui blocos bash inline da FASE FINAL dos dois comandos por uma chamada
# deterministica a este script, eliminando a fragilidade de extracao de markdown
# por LLM e centralizando proof-of-completion + dedupe + state machine.
#
# Hardening (review adversarial 2026-05-13 via /mcp:codex):
#   - Lock atomico via mkdir per-(kind,item) — serializa invocacoes concorrentes.
#   - Stale lock auto-recovery (>60s).
#   - Dedupe via .notified marker recente (<30s) — bloqueia re-invocacao
#     acidental do mesmo run sem quebrar re-run legitimo apos minutos.
#   - State machine de marker: ready -> inflight -> notified | failed
#     (atomic mv como claim primitive).
#   - Marker JSON contem run_id, final_status, hashes de PROGRESS.md e
#     _LOOP-LOG.md como anchors de durabilidade — evidencia inspecionavel.
#   - Best-effort: SEMPRE exit 0 (non-blocking).
#
# Contrato:
#   --slug <slug>            obrigatorio.
#   --item <ID>              obrigatorio.
#   --kind do|review-done    opcional, default 'do' (backwards-compat).
#   --final-status <STATUS>  opcional. Se ausente, derivado de PROGRESS.md
#                            item state ([x]=DONE, [!]=FAILED, [>]=SKIPPED).
#   --verdict <V>            opcional, so usado em --kind review-done.
#   --run-id <ID>            opcional, gerado se ausente (uuid hex 16-char).
#   <channel>                positional, opcional ('interactive'|'workspace'|'workspace_xterm').
#                            Override via WF_CHANNEL_OVERRIDE env > arg > default.
#
# Marker path:
#   {loop_root}/.autocast/{kind}-{item}-{run_id}.{ready|inflight|notified|failed}.json
#
# Repo root resolvido via BASH_SOURCE[0] walk-up. Cwd-independent.

set -u

autocast_err() {
  printf 'daily-loop-autocast: %s\n' "$1" >&2
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

gen_run_id() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import uuid; print(uuid.uuid4().hex[:16])" 2>/dev/null && return 0
  fi
  if [ -r /proc/sys/kernel/random/uuid ]; then
    tr -d '-' < /proc/sys/kernel/random/uuid | cut -c1-16 && return 0
  fi
  printf '%s%s' "$(date +%s%N 2>/dev/null || date +%s)" "${RANDOM}${RANDOM}" \
    | sha256sum 2>/dev/null | cut -c1-16
}

file_sha() {
  local f="$1"
  [ -f "$f" ] || { printf 'absent'; return 0; }
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" 2>/dev/null | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" 2>/dev/null | cut -d' ' -f1
  else
    printf 'no-sha-tool'
  fi
}

mtime_epoch() {
  local f="$1"
  [ -e "$f" ] || { printf '0'; return 0; }
  stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || printf '0'
}

now_epoch() {
  date +%s 2>/dev/null || printf '0'
}

iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf '0'
}

# ─── Argument parsing ───────────────────────────────────────────────────────

item_id=""
loop_slug=""
kind="do"
final_status=""
verdict=""
run_id=""
channel_arg=""

while [ $# -gt 0 ]; do
  case "$1" in
    --slug) loop_slug="${2:-}"; shift 2 || shift ;;
    --slug=*) loop_slug="${1#--slug=}"; shift ;;
    --item) item_id="${2:-}"; shift 2 || shift ;;
    --item=*) item_id="${1#--item=}"; shift ;;
    --kind) kind="${2:-do}"; shift 2 || shift ;;
    --kind=*) kind="${1#--kind=}"; shift ;;
    --final-status) final_status="${2:-}"; shift 2 || shift ;;
    --final-status=*) final_status="${1#--final-status=}"; shift ;;
    --verdict) verdict="${2:-}"; shift 2 || shift ;;
    --verdict=*) verdict="${1#--verdict=}"; shift ;;
    --run-id) run_id="${2:-}"; shift 2 || shift ;;
    --run-id=*) run_id="${1#--run-id=}"; shift ;;
    interactive|workspace|workspace_xterm) channel_arg="$1"; shift ;;
    *) shift ;;
  esac
done

case "$kind" in
  do|review-done) ;;
  *)
    autocast_err "invalid --kind '$kind' (expected: do|review-done); falling back to 'do'"
    kind="do"
    ;;
esac

wf_channel="${WF_CHANNEL_OVERRIDE:-${channel_arg:-interactive}}"

# ─── Resolve repo root ──────────────────────────────────────────────────────

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="." ;;
esac

script_dir="$(CDPATH= cd -- "$script_dir" 2>/dev/null && pwd -P)" || {
  autocast_err "cannot resolve script directory from ${BASH_SOURCE[0]}"
  exit 0
}

repo_root="$(find_repo_root "$script_dir")" || {
  autocast_err "SystemForge root not found above $script_dir"
  exit 0
}

# ─── Standalone mode (no slug/item): direct notify, no precondition ────────
# Preserva comportamento legado para testes manuais.

if [ -z "$item_id" ] || [ -z "$loop_slug" ]; then
  notify_sh="$repo_root/ai-forge/workflow-app/scripts/wf-notify.sh"
  if [ ! -f "$notify_sh" ]; then
    autocast_err "wf-notify.sh not found at $notify_sh"
    exit 0
  fi
  if ! "${BASH:-bash}" "$notify_sh" --status success "$wf_channel"; then
    autocast_err "wf-notify.sh non-blocking failure for channel=$wf_channel (standalone mode)"
  fi
  exit 0
fi

# ─── Proof-of-completion: PROGRESS.md item terminal state ───────────────────

progress_file="$repo_root/blacksmith/loop-archives/$loop_slug/PROGRESS.md"
if [ ! -f "$progress_file" ]; then
  autocast_err "refused — PROGRESS.md not found at $progress_file"
  exit 0
fi

# Terminal states: do=[x|!|>], review-done=[x|!]
if [ "$kind" = "review-done" ]; then
  terminal_pattern='\[[x!]\]'
else
  terminal_pattern='\[[x!>]\]'
fi

if ! grep -qE "(^|[^0-9])${item_id}([^0-9]|$).*${terminal_pattern}" "$progress_file"; then
  autocast_err "refused — item $item_id (slug=$loop_slug, kind=$kind) nao esta em estado terminal em PROGRESS.md"
  exit 0
fi

loop_root="$repo_root/blacksmith/loop-archives/$loop_slug"
autocast_dir="$loop_root/.autocast"
mkdir -p "$autocast_dir" 2>/dev/null || {
  autocast_err "cannot create $autocast_dir"
  exit 0
}

# ─── Lock atomico per-(kind,item) ──────────────────────────────────────────
# mkdir e POSIX-atomic: 1 vencedor entre invocacoes concorrentes.
# Stale lock (>60s) e force-cleaned (proteger contra crash sem trap EXIT).

lockdir="$autocast_dir/${kind}-${item_id}.lock"
if [ -d "$lockdir" ]; then
  lock_age=$(( $(now_epoch) - $(mtime_epoch "$lockdir") ))
  if [ "$lock_age" -gt 60 ]; then
    autocast_err "stale lock detected ($lock_age s old); reclaiming"
    rm -rf "$lockdir" 2>/dev/null
  fi
fi

if ! mkdir "$lockdir" 2>/dev/null; then
  autocast_err "lock held by another invocation (kind=$kind, item=$item_id); exit"
  exit 0
fi
trap 'rm -rf "$lockdir" 2>/dev/null' EXIT

# ─── Dedupe: recent .notified marker (<30s) ────────────────────────────────
# Mitiga risco D (LLM invoca 2x acidentalmente em sequencia rapida).
# Re-run legitimo apos fix manual leva minutos -> nao falsa-positiva.

now=$(now_epoch)
shopt -s nullglob 2>/dev/null
for f in "$autocast_dir/${kind}-${item_id}-"*.notified.json; do
  [ -f "$f" ] || continue
  fage=$(( now - $(mtime_epoch "$f") ))
  if [ "$fage" -lt 30 ]; then
    autocast_err "recent .notified marker for ${kind}-${item_id} (age=${fage}s); dedup, exit"
    exit 0
  fi
done
shopt -u nullglob 2>/dev/null

# ─── Derivar final_status de PROGRESS.md se nao foi passado ────────────────

if [ -z "$final_status" ]; then
  state_char=$(grep -E "(^|[^0-9])${item_id}([^0-9]|$).*${terminal_pattern}" "$progress_file" \
    | head -1 | grep -oE '\[[x!>]\]' | head -1 | tr -d '[]')
  case "$state_char" in
    x) final_status="DONE" ;;
    !) final_status="FAILED" ;;
    \>) final_status="SKIPPED" ;;
    *) final_status="UNKNOWN" ;;
  esac
fi

# ─── Generate run_id se ausente ────────────────────────────────────────────

if [ -z "$run_id" ]; then
  run_id=$(gen_run_id)
fi

if [ -z "$run_id" ]; then
  autocast_err "could not generate run_id; aborting"
  exit 0
fi

# ─── Derivar status semantico do listener ────────────────────────────────────
# O listener vermelho existe para estados terminais que exigem intervencao.
# Portanto FAILED/RESSALVAS/BLOCKED nunca podem virar success. SKIPPED e
# terminal valido para kind=do e continua verde.

final_status_upper=$(printf '%s' "$final_status" | tr '[:lower:]' '[:upper:]')
verdict_upper=$(printf '%s' "$verdict" | tr '[:lower:]' '[:upper:]')
notify_status="success"
notify_reason=""

case "$final_status_upper" in
  FAILED|FAIL|ERROR|REPROVADO)
    notify_status="failure"
    notify_reason="VERIFY_FAILED"
    ;;
  BLOCKED|BLOQUEADO)
    notify_status="failure"
    notify_reason="BLOCKED"
    ;;
  RESSALVAS|*RESSALVA*)
    notify_status="failure"
    notify_reason="RESSALVAS"
    ;;
  UNKNOWN|"")
    notify_status="failure"
    notify_reason="BLOCKED"
    ;;
esac

case "$verdict_upper" in
  RESSALVAS|*RESSALVA*)
    notify_status="failure"
    notify_reason="RESSALVAS"
    ;;
  REPROVADO|REJECTED|REJEITADO)
    notify_status="failure"
    notify_reason="VERIFY_FAILED"
    ;;
  BLOCKED|BLOQUEADO)
    notify_status="failure"
    notify_reason="BLOCKED"
    ;;
esac

# ─── Compute hashes (durability anchors) ────────────────────────────────────

progress_sha=$(file_sha "$progress_file")
loop_log_sha=$(file_sha "$loop_root/_LOOP-LOG.md")

# ─── Write .ready.json (atomic via tmp+rename) ──────────────────────────────

ready_path="$autocast_dir/${kind}-${item_id}-${run_id}.ready.json"
tmp_path="${ready_path}.tmp"

{
  printf '{\n'
  printf '  "kind": "%s",\n' "$kind"
  printf '  "slug": "%s",\n' "$loop_slug"
  printf '  "item": "%s",\n' "$item_id"
  printf '  "run_id": "%s",\n' "$run_id"
  printf '  "final_status": "%s",\n' "$final_status"
  if [ -n "$verdict" ]; then
    printf '  "verdict": "%s",\n' "$verdict"
  fi
  printf '  "progress_sha": "%s",\n' "$progress_sha"
  printf '  "loop_log_sha": "%s",\n' "$loop_log_sha"
  printf '  "channel": "%s",\n' "$wf_channel"
  printf '  "ts": "%s"\n' "$(iso_now)"
  printf '}\n'
} > "$tmp_path" 2>/dev/null || {
  autocast_err "cannot write ready marker tmp at $tmp_path"
  exit 0
}

if ! mv "$tmp_path" "$ready_path" 2>/dev/null; then
  autocast_err "cannot rename tmp -> ready at $ready_path"
  rm -f "$tmp_path" 2>/dev/null
  exit 0
fi

# ─── State machine: ready -> inflight (atomic claim) ────────────────────────

inflight_path="$autocast_dir/${kind}-${item_id}-${run_id}.inflight.json"
if ! mv "$ready_path" "$inflight_path" 2>/dev/null; then
  autocast_err "ready marker disappeared (consumed by concurrent claim?); exit"
  exit 0
fi

# ─── Invoke wf-notify.sh ────────────────────────────────────────────────────

notify_sh="$repo_root/ai-forge/workflow-app/scripts/wf-notify.sh"
if [ ! -f "$notify_sh" ]; then
  autocast_err "wf-notify.sh not found at $notify_sh; marking failed"
  failed_path="$autocast_dir/${kind}-${item_id}-${run_id}.failed.json"
  mv "$inflight_path" "$failed_path" 2>/dev/null
  exit 0
fi

if [ "$notify_status" = "failure" ]; then
  "${BASH:-bash}" "$notify_sh" \
    --status failure --reason "$notify_reason" "$wf_channel"
  notify_rc=$?
else
  "${BASH:-bash}" "$notify_sh" --status success "$wf_channel"
  notify_rc=$?
fi

if [ "$notify_rc" -eq 0 ]; then
  notified_path="$autocast_dir/${kind}-${item_id}-${run_id}.notified.json"
  mv "$inflight_path" "$notified_path" 2>/dev/null
else
  autocast_err "wf-notify.sh failed for channel=$wf_channel; marker -> failed (replay possivel)"
  failed_path="$autocast_dir/${kind}-${item_id}-${run_id}.failed.json"
  mv "$inflight_path" "$failed_path" 2>/dev/null
fi

exit 0
