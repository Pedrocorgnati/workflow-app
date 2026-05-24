#!/usr/bin/env python3
"""G6 gate: zero TODOs em seeds renderizados.

Uso: python check-seeds-no-todos.py <seeds_dir>
Exit 0 = G6 PASS; Exit 1 + lista de violacoes = G6 FAIL.
"""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: check-seeds-no-todos.py <seeds_dir>", file=sys.stderr)
        return 2
    seeds_dir = Path(argv[1])
    if not seeds_dir.is_dir():
        print(f"seeds_dir invalido: {seeds_dir}", file=sys.stderr)
        return 2
    violations: list[str] = []
    for md in sorted(seeds_dir.glob("*.md")):
        if md.name.startswith("_") or md.name.upper() == "INDEX.MD":
            continue
        text = md.read_text(encoding="utf-8")
        for ln, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                violations.append(f"{md}:{ln}: {line.strip()}")
    if violations:
        print("\n".join(violations))
        return 1
    print(f"G6 OK: zero TODOs em {seeds_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
