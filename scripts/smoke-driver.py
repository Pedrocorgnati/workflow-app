#!/usr/bin/env python3
"""Driver semi-automatizado dos 11 cenarios do smoke T9.

Persiste estado a cada cenario em _INTEGRATION-LOG.md.partial.
Crash do operador (Ctrl+C) nao perde progresso. Ordem forcada.

Uso: python smoke-driver.py [--from N]
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

SCENARIOS: list[tuple[str, str]] = [
    ("01-bootstrap", "Aba brainstorm carrega com 9 botoes em grid 3x3"),
    ("02-picker", "Picker `brainstorm-md-picker` abre em blacksmith/brainstorm-mcp/"),
    ("03-gear", "Gear `toolbar-prompts-config-gear` abre modal R/U"),
    ("04-radio-default", "Radio `type-selector-radio-input` default = Claude"),
    ("05-claude-publica", "Botao Claude publica em terminal-interactive-output"),
    ("06-kimi-publica", "Radio=Kimi + botao dinamico publica em terminal-workspace-output"),
    ("07-codex-toast", "Radio=Codex + botao dinamico exibe toast canonico (T7)"),
    ("08-checkbox-stop", "Click APENAS na checkbox nao dispara prompt (T6)"),
    ("09-checkbox-marca", "Click no botao marca checkbox apos sucesso"),
    ("10-publish-failure", "WORKFLOW_APP_FORCE_PUBLISH_FAILURE=1 -> feedback erro + checkbox NAO marcada"),
    ("11-codex-no-t3", "Botao Codex fixo (seed temporario) bloqueado sem fallback silencioso (G4)"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", type=int, default=1)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    partial = root / "blacksmith" / "mcp-flow" / "_INTEGRATION-LOG.md.partial"
    partial.parent.mkdir(parents=True, exist_ok=True)
    if not partial.exists():
        partial.write_text(
            "# Smoke partial state (T9 semi-auto driver)\n\n"
            f"Started: {datetime.datetime.utcnow().isoformat()}Z\n\n",
            encoding="utf-8",
        )

    for n, (slug, desc) in enumerate(SCENARIOS, 1):
        if n < args.start:
            continue
        print(f"\n=== Cenario {n:02d}: {desc} ===")
        try:
            ans = input("[Enter] PASS, [F] FAIL, [S] SKIP, [Q] QUIT: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[abort] sem confirmacao - estado preservado em .partial")
            return 130
        if ans == "q":
            return 0
        result = {"": "PASS", "f": "FAIL", "s": "SKIP"}.get(ans, "PASS")
        ts = datetime.datetime.utcnow().isoformat()
        with partial.open("a", encoding="utf-8") as fp:
            fp.write(f"- [{n:02d}] {slug}: {result} ({ts}Z) - {desc}\n")
        if result == "FAIL":
            note = input("    nota livre (Enter para pular): ").strip()
            if note:
                with partial.open("a", encoding="utf-8") as fp:
                    fp.write(f"      nota: {note}\n")

    print(f"\nSmoke completo. Estado em: {partial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
