#!/usr/bin/env bash
# Hook canonico - proibe `xfail(strict=True)` em tests/ (hardening T9 §2 do
# loop 05-21-implantation-tasklist-aba-brainstorm).
#
# Motivo: xfail(strict=True) cria zona morta. Quando a dependencia entrega
# o modulo, o teste passa e XPASS quebra o CI; operadores desativam strict
# em vez de remover o marcador, perdendo o sinal canonico de regressao.
#
# Mecanismo correto enquanto dependencia ausente:
#     pytest.importorskip("workflow_app.widgets.X")
#
# Integracao opcional via pre-commit framework:
#     - id: check-no-xfail-strict
#       entry: scripts/check-no-xfail-strict.sh
#       language: script
#       pass_filenames: false
#
# Exit codes:
#   0  ok - nenhum match.
#   1  encontrado xfail(strict=True).

set -euo pipefail

# Resolve script dir e roda a partir do submodulo workflow-app/.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
cd "$repo_dir"

# Aceita apenas uso REAL (decorator/marker chamando xfail), ignora menes-
# coes em docstrings/comentarios/CONTRACT.md. Padrao canonico de marker:
#   @pytest.mark.xfail(strict=True...
#   pytestmark = pytest.mark.xfail(strict=True...
#   pytest.mark.xfail(strict=True...
# Tudo dentro de prose markdown (CONTRACT.md/README) fica fora do escopo
# via --include="*.py".
matches=$(grep -rn --include="*.py" -E "pytest\.mark\.xfail\(.*strict=True" tests/ 2>/dev/null || true)
if [ -n "$matches" ]; then
    echo "ERRO: xfail(strict=True) e PROIBIDO em tests/ (hardening T9 §2)."
    echo "Use pytest.importorskip() para skip enquanto dependencia ausente."
    echo ""
    echo "$matches"
    exit 1
fi
exit 0
