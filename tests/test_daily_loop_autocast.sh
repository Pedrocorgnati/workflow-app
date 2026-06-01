#!/usr/bin/env bash
# test_daily_loop_autocast.sh — testes de integracao para daily-loop-autocast.sh.
#
# Cobre os 5 cenarios obrigatorios do hardening (review adversarial 2026-05-13):
#   T1: PROGRESS.md item nao-terminal -> nao notifica, sem marker.
#   T2: Item terminal -> notifica 1x, marker .notified existe.
#   T3: Re-run dentro de 30s -> dedup, exit 0, marker original intacto, sem nova notify.
#   T4: Re-run apos sleep > 30s -> notify novo, novo marker .notified.
#   T5: Concorrencia (10 invocacoes paralelas) -> exatamente 1 notify.
#
# Bonus:
#   T6: Standalone mode (sem --slug/--item) -> notify direto sem precondicao.
#   T7: --kind review-done com item [>] (skipped) -> recusa (nao terminal para review-done).
#   T8: --final-status explicito sobrepoe derivacao de PROGRESS.md.
#   T9: wf-notify falha -> marker .failed, replayable.
#
# Cwd-independente. Cria sandbox isolado em $TMPDIR.

set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd -P)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd -P)"
AUTOCAST="$REPO_ROOT/ai-forge/workflow-app/scripts/daily-loop-autocast.sh"

if [ ! -f "$AUTOCAST" ]; then
  printf 'FAIL: autocast script not found at %s\n' "$AUTOCAST" >&2
  exit 1
fi

PASS=0
FAIL=0
FAILED_TESTS=()

ok() {
  PASS=$((PASS + 1))
  printf '  [PASS] %s\n' "$1"
}

fail() {
  FAIL=$((FAIL + 1))
  FAILED_TESTS+=("$1")
  printf '  [FAIL] %s\n' "$1" >&2
  if [ -n "${2:-}" ]; then
    printf '         %s\n' "$2" >&2
  fi
}

# ─── Sandbox: fake repo root with .claude/commands + ai-forge + CLAUDE.md ──

setup_sandbox() {
  local sandbox
  sandbox="$(mktemp -d -t daily-loop-autocast-test.XXXXXX)"
  mkdir -p "$sandbox/.claude/commands"
  mkdir -p "$sandbox/ai-forge/workflow-app/scripts"
  mkdir -p "$sandbox/blacksmith/loop-archives/test-loop"
  printf '# Fake CLAUDE.md\n' > "$sandbox/CLAUDE.md"
  # Symlink autocast into sandbox so BASH_SOURCE walk-up lands on sandbox
  cp "$AUTOCAST" "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh"
  chmod +x "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh"
  printf '%s\n' "$sandbox"
}

# Stub wf-notify.sh: increments counter file, exit 0 (or exit 1 if STUB_FAIL=1)
install_stub_notify() {
  local sandbox="$1"
  local counter="$2"
  local stub="$sandbox/ai-forge/workflow-app/scripts/wf-notify.sh"
  cat > "$stub" <<STUB
#!/usr/bin/env bash
# stub wf-notify.sh
printf '%s\n' "\$*" >> "$counter"
if [ "\${STUB_FAIL:-0}" = "1" ]; then
  exit 1
fi
exit 0
STUB
  chmod +x "$stub"
}

write_progress_md() {
  local sandbox="$1"
  local item="$2"
  local state="$3"  # x, !, >, or " "
  local pf="$sandbox/blacksmith/loop-archives/test-loop/PROGRESS.md"
  cat > "$pf" <<PMD
# Test Progress

| ID  | Status | Target | Bucket | Updated |
|-----|--------|--------|--------|---------|
| $item | [$state] | test-target | T-test | 2026-05-13T00:00:00Z |
PMD
}

count_notify() {
  local counter="$1"
  if [ ! -f "$counter" ]; then printf '0'; return; fi
  wc -l < "$counter" | tr -d ' '
}

count_markers() {
  local sandbox="$1"
  local pattern="$2"  # e.g., "*.notified.json"
  local dir="$sandbox/blacksmith/loop-archives/test-loop/.autocast"
  if [ ! -d "$dir" ]; then printf '0'; return; fi
  ls -1 "$dir"/$pattern 2>/dev/null | wc -l | tr -d ' '
}

last_notify_args() {
  local counter="$1"
  if [ ! -f "$counter" ]; then printf ''; return; fi
  tail -n 1 "$counter"
}

# ─────────────────────────────────────────────────────────────────────────────
# T1: PROGRESS.md item nao-terminal -> nao notifica
# ─────────────────────────────────────────────────────────────────────────────

test_t1_non_terminal_refuses() {
  printf '\nT1: item nao-terminal nao notifica\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "001" " "  # pending

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 001 --kind do interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "0" ]; then ok "T1: zero notify para item pending"; else fail "T1: esperado 0 notify, got $n"; fi

  local m; m=$(count_markers "$sandbox" "*.json")
  if [ "$m" = "0" ]; then ok "T1: zero markers escritos"; else fail "T1: esperado 0 markers, got $m"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T2: Item terminal [x] -> notifica 1x, marker .notified existe
# ─────────────────────────────────────────────────────────────────────────────

test_t2_terminal_notifies_once() {
  printf '\nT2: item terminal notifica 1x\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "002" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 002 --kind do --final-status DONE interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T2: exatamente 1 notify"; else fail "T2: esperado 1 notify, got $n"; fi
  local args; args=$(last_notify_args "$counter")
  if printf '%s' "$args" | grep -q -- '--status success'; then
    ok "T2: notify explicito de success"
  else
    fail "T2: esperado --status success" "$args"
  fi

  local m; m=$(count_markers "$sandbox" "do-002-*.notified.json")
  if [ "$m" = "1" ]; then ok "T2: 1 marker .notified existe"; else fail "T2: esperado 1 marker .notified, got $m"; fi

  local ready_count; ready_count=$(count_markers "$sandbox" "*.ready.json")
  local inflight_count; inflight_count=$(count_markers "$sandbox" "*.inflight.json")
  if [ "$ready_count" = "0" ] && [ "$inflight_count" = "0" ]; then
    ok "T2: zero markers stale (.ready/.inflight) — state machine fechou"
  else
    fail "T2: markers stale — ready=$ready_count inflight=$inflight_count"
  fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T3: Re-run dentro de 30s -> dedup, sem nova notify
# ─────────────────────────────────────────────────────────────────────────────

test_t3_dedup_within_window() {
  printf '\nT3: re-run dentro de 30s -> dedup\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "003" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 003 --kind do --final-status DONE interactive 2>/dev/null
  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 003 --kind do --final-status DONE interactive 2>/dev/null
  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 003 --kind do --final-status DONE interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T3: 3 invocacoes -> 1 notify (dedup)"; else fail "T3: esperado 1 notify, got $n"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T4: Re-run apos sleep > 30s -> notify novo
# ─────────────────────────────────────────────────────────────────────────────

test_t4_legitimate_rerun_after_window() {
  printf '\nT4: re-run apos 30s+ -> notify novo (skip se RUN_SLOW=0)\n'
  if [ "${RUN_SLOW:-1}" = "0" ]; then
    printf '  [SKIP] T4: RUN_SLOW=0 (este teste leva ~32s)\n'
    return
  fi
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "004" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 004 --kind do --final-status DONE interactive 2>/dev/null

  # Backdate the .notified marker mtime to >30s ago (simula passagem de tempo)
  local mdir="$sandbox/blacksmith/loop-archives/test-loop/.autocast"
  for f in "$mdir"/do-004-*.notified.json; do
    touch -d "60 seconds ago" "$f" 2>/dev/null || touch -A -000060 "$f" 2>/dev/null || true
  done

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 004 --kind do --final-status DONE interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "2" ]; then ok "T4: re-run pos-window -> 2 notify total"; else fail "T4: esperado 2 notify, got $n"; fi

  local m; m=$(count_markers "$sandbox" "do-004-*.notified.json")
  if [ "$m" = "2" ]; then ok "T4: 2 markers .notified (run_ids distintos)"; else fail "T4: esperado 2 markers, got $m"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T5: Concorrencia — 10 invocacoes paralelas -> exatamente 1 notify
# ─────────────────────────────────────────────────────────────────────────────

test_t5_concurrent_single_notify() {
  printf '\nT5: 10 invocacoes paralelas -> 1 notify\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "005" "x"

  local i
  for i in $(seq 1 10); do
    bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
      --slug test-loop --item 005 --kind do --final-status DONE interactive 2>/dev/null &
  done
  wait

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T5: 10 invocacoes concorrentes -> 1 notify (lock + dedup)"; else fail "T5: esperado 1 notify, got $n"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T6: Standalone mode (sem --slug/--item) -> notify direto
# ─────────────────────────────────────────────────────────────────────────────

test_t6_standalone_no_precondition() {
  printf '\nT6: standalone mode -> notify direto sem precondicao\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  # NAO escreve PROGRESS.md — standalone deve funcionar mesmo assim

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T6: standalone -> 1 notify"; else fail "T6: esperado 1 notify, got $n"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T7: --kind review-done com [>] (skipped) -> recusa
# ─────────────────────────────────────────────────────────────────────────────

test_t7_review_done_rejects_skipped() {
  printf '\nT7: review-done recusa item [>]\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "007" ">"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 007 --kind review-done interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "0" ]; then ok "T7: review-done com [>] -> 0 notify"; else fail "T7: esperado 0 notify, got $n"; fi

  # Mas /daily-loop:do com [>] DEVE notificar (skip-by-handoff e terminal valido para do)
  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 007 --kind do interactive 2>/dev/null

  n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T7: do com [>] -> 1 notify (terminal valido)"; else fail "T7: do com [>] esperado 1 notify, got $n"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T8: --final-status explicito vai para o marker
# ─────────────────────────────────────────────────────────────────────────────

test_t8_explicit_final_status() {
  printf '\nT8: --final-status explicito gravado no marker\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "008" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 008 --kind review-done \
    --final-status DONE-AFTER-FIX --verdict APROVADO interactive 2>/dev/null

  local marker
  marker=$(ls "$sandbox/blacksmith/loop-archives/test-loop/.autocast"/review-done-008-*.notified.json 2>/dev/null | head -1)
  if [ -z "$marker" ]; then fail "T8: marker .notified ausente"; rm -rf "$sandbox"; return; fi

  if grep -q '"final_status": "DONE-AFTER-FIX"' "$marker"; then
    ok "T8: final_status DONE-AFTER-FIX gravado"
  else
    fail "T8: final_status incorreto" "$(cat "$marker")"
  fi
  if grep -q '"verdict": "APROVADO"' "$marker"; then
    ok "T8: verdict APROVADO gravado"
  else
    fail "T8: verdict ausente" "$(cat "$marker")"
  fi
  if grep -q '"kind": "review-done"' "$marker"; then
    ok "T8: kind review-done gravado"
  else
    fail "T8: kind incorreto" "$(cat "$marker")"
  fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T9: wf-notify falha -> marker .failed, replayable
# ─────────────────────────────────────────────────────────────────────────────

test_t9_notify_failure_replayable() {
  printf '\nT9: wf-notify falha -> marker .failed\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "009" "x"

  STUB_FAIL=1 bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 009 --kind do --final-status DONE interactive 2>/dev/null

  local f; f=$(count_markers "$sandbox" "*.failed.json")
  if [ "$f" = "1" ]; then ok "T9: 1 marker .failed (replayable)"; else fail "T9: esperado 1 .failed, got $f"; fi

  local nfd; nfd=$(count_markers "$sandbox" "*.notified.json")
  if [ "$nfd" = "0" ]; then ok "T9: zero .notified (notify falhou)"; else fail "T9: esperado 0 .notified, got $nfd"; fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T10: final_status FAILED -> notify vermelho, nunca success legacy
# ─────────────────────────────────────────────────────────────────────────────

test_t10_failed_final_status_sends_failure_notify() {
  printf '\nT10: final_status FAILED -> notify failure\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "010" "!"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 010 --kind do interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T10: exatamente 1 notify"; else fail "T10: esperado 1 notify, got $n"; fi

  local args; args=$(last_notify_args "$counter")
  if printf '%s' "$args" | grep -q -- '--status failure' && \
     printf '%s' "$args" | grep -q -- '--reason VERIFY_FAILED'; then
    ok "T10: FAILED virou failure/VERIFY_FAILED"
  else
    fail "T10: esperado --status failure --reason VERIFY_FAILED" "$args"
  fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T11: verdict RESSALVAS -> notify vermelho, mesmo com final_status DONE
# ─────────────────────────────────────────────────────────────────────────────

test_t11_ressalvas_sends_failure_notify() {
  printf '\nT11: verdict RESSALVAS -> notify failure\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "011" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 011 --kind review-done \
    --final-status DONE --verdict RESSALVAS interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T11: exatamente 1 notify"; else fail "T11: esperado 1 notify, got $n"; fi

  local args; args=$(last_notify_args "$counter")
  if printf '%s' "$args" | grep -q -- '--status failure' && \
     printf '%s' "$args" | grep -q -- '--reason RESSALVAS'; then
    ok "T11: RESSALVAS virou failure/RESSALVAS"
  else
    fail "T11: esperado --status failure --reason RESSALVAS" "$args"
  fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T12: final_status BLOCKED -> notify vermelho/BLOCKED
# ─────────────────────────────────────────────────────────────────────────────

test_t12_blocked_final_status_sends_failure_notify() {
  printf '\nT12: final_status BLOCKED -> notify failure\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "012" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 012 --kind review-done \
    --final-status BLOCKED --verdict APROVADO interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T12: exatamente 1 notify"; else fail "T12: esperado 1 notify, got $n"; fi

  local args; args=$(last_notify_args "$counter")
  if printf '%s' "$args" | grep -q -- '--status failure' && \
     printf '%s' "$args" | grep -q -- '--reason BLOCKED'; then
    ok "T12: BLOCKED virou failure/BLOCKED"
  else
    fail "T12: esperado --status failure --reason BLOCKED" "$args"
  fi

  rm -rf "$sandbox"
}

# ─────────────────────────────────────────────────────────────────────────────
# T13: verdict REPROVADO -> notify vermelho/VERIFY_FAILED
# ─────────────────────────────────────────────────────────────────────────────

test_t13_reprovado_verdict_sends_failure_notify() {
  printf '\nT13: verdict REPROVADO -> notify failure\n'
  local sandbox; sandbox=$(setup_sandbox)
  local counter="$sandbox/notify.count"
  install_stub_notify "$sandbox" "$counter"
  write_progress_md "$sandbox" "013" "x"

  bash "$sandbox/ai-forge/workflow-app/scripts/daily-loop-autocast.sh" \
    --slug test-loop --item 013 --kind review-done \
    --final-status DONE --verdict REPROVADO interactive 2>/dev/null

  local n; n=$(count_notify "$counter")
  if [ "$n" = "1" ]; then ok "T13: exatamente 1 notify"; else fail "T13: esperado 1 notify, got $n"; fi

  local args; args=$(last_notify_args "$counter")
  if printf '%s' "$args" | grep -q -- '--status failure' && \
     printf '%s' "$args" | grep -q -- '--reason VERIFY_FAILED'; then
    ok "T13: REPROVADO virou failure/VERIFY_FAILED"
  else
    fail "T13: esperado --status failure --reason VERIFY_FAILED" "$args"
  fi

  rm -rf "$sandbox"
}

# ─── Run all ────────────────────────────────────────────────────────────────

printf '=== daily-loop-autocast.sh test suite ===\n'

test_t1_non_terminal_refuses
test_t2_terminal_notifies_once
test_t3_dedup_within_window
test_t4_legitimate_rerun_after_window
test_t5_concurrent_single_notify
test_t6_standalone_no_precondition
test_t7_review_done_rejects_skipped
test_t8_explicit_final_status
test_t9_notify_failure_replayable
test_t10_failed_final_status_sends_failure_notify
test_t11_ressalvas_sends_failure_notify
test_t12_blocked_final_status_sends_failure_notify
test_t13_reprovado_verdict_sends_failure_notify

printf '\n=== Result: %d passed, %d failed ===\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf 'Failed tests:\n'
  for t in "${FAILED_TESTS[@]}"; do
    printf '  - %s\n' "$t"
  done
  exit 1
fi
exit 0
