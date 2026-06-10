"""
Codex compatibility — parallel whitelist for the Codex worker (T3).

Source of truth: blacksmith/claude-to-codex/progress.md. Commands listed here
are eligible for execution in the Codex CLI running on the T3 terminal
(`terminal-codex-output`), instead of the Claude Code interactive terminal.

This module is the Codex sibling of `kimi_whitelist.py` and mirrors its API on
purpose (regra 1 de source.md secao 8: "o formato deve espelhar
kimi_whitelist.py para reduzir surpresa"). The decision axis differs: the Kimi
rubric's Eixo 6 ("Wiring Codex/adversarial") is INVERTED for Codex — strong
codex/adversarial wiring RAISES the Codex score instead of pushing toward
KEEP_CLAUDE (regra 3). So most commands eligible here are the adversarial
review/audit commands that are KEEP_CLAUDE for Kimi.

A second, distinct axis exists: CAPABILITY EXCLUSIVITY. `/pictures-create` is
whitelisted not for adversarial wiring but because Codex is the ONLY LLM in the
queue (Claude/Kimi/Codex) with image generation (gpt-image-1) — Claude/Kimi
cannot execute its core task (producing pixels) at all. Same publish format
(slash-executor), highest %Codex in progress.md, different reason. See
blacksmith/claude-to-codex/progress.md (linha 14 + nota de eixo).

Publication: this module decides eligibility only. The Codex worker publishes a
whitelisted command to T3 via the existing `_build_codex_slash_executor_prompt`
+ `_dispatch_codex_command(to_t1=False)` path in `command_queue_widget.py`
(source.md secao 10). No new publication path is created here — the slash
executor points Codex at `.claude/commands/{slug}.md` and forwards the original
arguments verbatim.

Hardening: tests/test_codex_whitelist.py parses progress.md at test time and
fails if any whitelisted command drops below CODEX_THRESHOLD, loses its
`codex_publish_format`, disappears from the source-of-truth file, or fails to
resolve to a `.claude/commands/*.md` file (the slash-executor target).
"""

from __future__ import annotations

# Commands with %Codex >= CODEX_THRESHOLD in
# blacksmith/claude-to-codex/progress.md that ALSO declare a non-empty
# `codex_publish_format` (regra 5, criterio mecanico). The frozenset is the
# materialized cache of that predicate; the test re-derives it from progress.md
# and fails on drift.
#
# Match is by exact command name (the slash-command head, before the first
# space). The publish format for every command below is `slash-executor`.
CODEX_THRESHOLD: int = 70
CODEX_PROGRESS_PATH: str = "blacksmith/claude-to-codex/progress.md"

CODEX_COMPATIBLE_COMMANDS: frozenset[str] = frozenset({
    # C2 Review — wiring Codex/adversarial explicito (Eixo 6 invertido)
    "/mcp:cmd-best-practices",   # 90 (CODEX_PREFERRED)
    "/cmd:review",               # 88 (CODEX_PREFERRED)
    "/study:review-user",        # 80
    "/agents:troop-review",      # 78
    # C2 Review — review adversarial de codigo (Eixo 2 favoravel a Codex)
    "/python:py-review",         # 85
    "/typescript:ts-review",     # 85
    "/nextjs:next-review",       # 85
    "/dependency-audit",         # 84
    "/android:android-review",   # 82
    "/reactnative:rn-review",    # 82
    "/tech-debt-audit",          # 82
    "/study:triangulate",        # 78
    "/study:debate",             # 78
    # C3 Assets — capacidade EXCLUSIVA de geracao de imagem (REGRA AUTOMATICA,
    # score 100; eixo distinto do Eixo 6 adversarial). Ver IMAGE_GENERATION_COMMANDS.
    "/pictures-create",          # 100 (CODEX_PREFERRED) — cria imagem no repo
})

# ── Regra de capacidade exclusiva: GERACAO DE IMAGEM ──────────────────────── #
# Comandos que CRIAM imagem no repositorio. Entre Claude/Kimi/Codex, SO o Codex
# gera pixel (GPT Image: gpt-image-2/gpt-image-1/DALL-E). Por isso esta regra e
# AUTOMATICA e nao-negociavel (progress.md, Rubrica "Capacidade exclusiva"):
#   1. % Codex = 100 (o maior possivel) — nao ha duvida nem deliberacao;
#   2. qualquer LLM que NAO seja o Codex, roteada para gerar imagem, DEVE FALHAR
#      (Gate de Capacidade — Zero Silencio: nunca arquivo falso/vazio, nunca so
#      re-emitir o prompt como entregavel);
#   3. padrao de qualidade canonico: melhor modelo GPT Image que exista na API
#      (gpt-image-1.5; fallback gpt-image-1), quality=high, output_format=png.
#      (NAO gpt-image-2 — a API retorna "does not exist"; ver progress.md notas.)
# IMAGE_GENERATION_COMMANDS e subconjunto estrito de CODEX_COMPATIBLE_COMMANDS.
# Ao adicionar um novo comando que cria imagem: inclua-o aqui E na tabela do
# progress.md com score 100 (o test enforce as duas coisas).
IMAGE_GENERATION_COMMANDS: frozenset[str] = frozenset({
    "/pictures-create",
})

# Score canonico de um comando de geracao de imagem (regra automatica).
IMAGE_GENERATION_SCORE: int = 100


def is_codex_compatible(command_name: str) -> bool:
    """Return True if this slash-command is in the Codex-compatible whitelist.

    Match is on the first whitespace-delimited token (the slash-command head).
    Anything after — flags, config paths — is ignored for matching.

    Membership implies both halves of regra 5: a command only lives in
    CODEX_COMPATIBLE_COMMANDS when its progress.md score is >= CODEX_THRESHOLD
    and it declares a non-empty `codex_publish_format`. tests/test_codex_whitelist.py
    keeps that invariant from drifting.
    """
    if not command_name or not command_name.strip():
        return False
    head = command_name.strip().split(None, 1)[0]
    return head in CODEX_COMPATIBLE_COMMANDS


def is_image_generation_command(command_name: str) -> bool:
    """Return True if this slash-command CREATES images in the repository.

    Capability-exclusivity rule: only the Codex worker can generate pixels
    (Claude/Kimi cannot). Such commands are auto-scored 100 and MUST fail when
    routed to any non-Codex LLM (the command's own Gate de Capacidade enforces
    the runtime side; this helper lets callers detect the class). Always a strict
    subset of `is_codex_compatible` (every image-gen command is Codex-compatible).
    """
    if not command_name or not command_name.strip():
        return False
    head = command_name.strip().split(None, 1)[0]
    return head in IMAGE_GENERATION_COMMANDS
