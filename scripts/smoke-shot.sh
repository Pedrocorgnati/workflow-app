#!/usr/bin/env bash
# Captura screenshot do workflow-app (T9-hardening item 6).
# Detecta Wayland vs X11 e usa a ferramenta apropriada.
# Uso: smoke-shot.sh <sha> <step>
set -euo pipefail

sha="${1:-$(git rev-parse --short=7 HEAD)}"
step="${2:-unnamed}"

repo_root="$(git rev-parse --show-toplevel)"
out_dir="$repo_root/blacksmith/mcp-flow/screenshots"
mkdir -p "$out_dir"
out="$out_dir/${sha}-${step}.png"

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    if command -v grim >/dev/null 2>&1; then
        grim "$out"
    elif command -v gnome-screenshot >/dev/null 2>&1; then
        gnome-screenshot -w -f "$out"  # tenta XWayland fallback
    else
        echo "Wayland: instale grim (sudo apt install grim) ou gnome-screenshot" >&2
        exit 1
    fi
else
    if command -v gnome-screenshot >/dev/null 2>&1; then
        gnome-screenshot -w -f "$out"
    elif command -v scrot >/dev/null 2>&1; then
        scrot -u "$out"
    elif command -v import >/dev/null 2>&1; then
        import -window root "$out"
    else
        echo "X11: instale gnome-screenshot, scrot ou imagemagick" >&2
        exit 1
    fi
fi

# Compactacao opcional (nao falha se ausente)
command -v pngquant >/dev/null 2>&1 && pngquant --force --output "$out" "$out" 2>/dev/null || true

stat -c 'screenshot %n: %s bytes, %y' "$out"
