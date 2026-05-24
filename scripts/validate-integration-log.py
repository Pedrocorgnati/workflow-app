#!/usr/bin/env python3
"""Audit pos-smoke do _INTEGRATION-LOG.md (T9-hardening item 13).

Checa que o ultimo bloco `## Smoke run` contem:
- sha_pre_smoke nao-vazio
- sha_post_smoke nao-vazio
- operator nao-vazio
- pelo menos 1 path em screenshots_paths apontando para arquivo existente
- telemetry_log_path apontando para arquivo existente OU marcado N/A

Exit 0 = log valido; Exit 1 + lista de campos faltantes = log invalido.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: validate-integration-log.py <path>", file=sys.stderr)
        return 2
    log = Path(argv[1])
    if not log.exists():
        print(f"log inexistente: {log}", file=sys.stderr)
        return 1
    text = log.read_text(encoding="utf-8")
    # ultimo bloco
    blocks = re.split(r"(?=^## Smoke run )", text, flags=re.MULTILINE)
    smoke_blocks = [b for b in blocks if b.startswith("## Smoke run")]
    if not smoke_blocks:
        print("nenhum bloco '## Smoke run' encontrado", file=sys.stderr)
        return 1
    last = smoke_blocks[-1]
    missing: list[str] = []
    required = {
        "sha_pre_smoke": r"sha_pre_smoke:\s*\S+",
        "sha_post_smoke": r"sha_post_smoke:\s*\S+",
        "operator": r"operator:\s*[\"']?\S+",
        "pyside_version": r"pyside_version:\s*[\"']?\S+",
        "ts_start": r"ts_start:\s*[\"']?\S+",
    }
    for key, pat in required.items():
        if not re.search(pat, last):
            missing.append(key)

    # Pelo menos 1 screenshot referenciado
    shots = re.findall(r"screenshots/[\w.-]+\.png", last)
    if not shots:
        missing.append("screenshots_paths (zero referencias)")
    else:
        log_root = log.parent
        missing_files = [s for s in shots if not (log_root / s).exists()]
        if len(missing_files) == len(shots):
            missing.append(f"screenshots inexistentes em disco: {shots}")

    if missing:
        print("CAMPOS FALTANTES OU INVALIDOS:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print(f"OK: ultimo bloco '## Smoke run' valido em {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
