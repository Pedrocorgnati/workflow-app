#!/bin/bash
# Mutation Testing Script for workflow-app
# Executa testes de mutação com opções configuráveis

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  WORKFLOW-APP — Mutation Testing"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Modo padrão: full (pode levar 5-10 min)
MODE=${1:-full}
TIMEOUT=${2:-30}

# Ativar venv se disponível
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Verificar se mutmut está instalado
if ! command -v mutmut &> /dev/null; then
    echo "❌ mutmut não encontrado. Instalando..."
    pip install mutmut>=2.4 pytest-cov>=5.0
fi

case "$MODE" in
    full)
        echo ""
        echo "🔬 Executando mutação COMPLETA (pode levar 5-10 min)..."
        echo ""
        mutmut run --timeout "$TIMEOUT"
        echo ""
        echo "✅ Mutação completa concluída!"
        echo ""
        echo "📊 Resultados:"
        mutmut results
        echo ""
        echo "💡 Dica: Para ver mutantes sobreviventes, execute:"
        echo "   mutmut results --show-all"
        echo "   mutmut show <id>"
        ;;

    quick)
        echo ""
        echo "⚡ Executando mutação RÁPIDA (apenas domain + errors + sdk)..."
        echo ""
        mutmut run \
            --paths-to-mutate src/workflow_app/domain/ \
            --paths-to-mutate src/workflow_app/errors/ \
            --paths-to-mutate src/workflow_app/sdk/ \
            --timeout "$TIMEOUT"
        echo ""
        echo "✅ Mutação rápida concluída!"
        mutmut results
        ;;

    module)
        if [ -z "$3" ]; then
            echo "❌ Modo 'module' requer argumento: ./run-mutation-tests.sh module <module_name>"
            echo ""
            echo "Exemplos:"
            echo "  ./run-mutation-tests.sh module pipeline"
            echo "  ./run-mutation-tests.sh module sdk/worker.py"
            exit 1
        fi

        MODULE="src/workflow_app/$3"
        if [ ! -e "$MODULE" ]; then
            echo "❌ Módulo não encontrado: $MODULE"
            exit 1
        fi

        echo ""
        echo "🔬 Mutando: $MODULE"
        echo ""
        mutmut run --paths-to-mutate "$MODULE" --timeout "$TIMEOUT"
        echo ""
        echo "✅ Mutação do módulo concluída!"
        mutmut results
        ;;

    results)
        echo ""
        echo "📊 Últimos resultados:"
        mutmut results --show-all
        ;;

    html)
        echo ""
        echo "🌐 Gerando relatório HTML..."
        mutmut html
        echo "✅ Abra 'html/index.html' no navegador"
        ;;

    clean)
        echo ""
        echo "🧹 Limpando cache de mutação..."
        rm -rf .mutmut-cache/
        rm -f .mutmut-id
        echo "✅ Cache limpo"
        ;;

    *)
        echo "❌ Modo desconhecido: $MODE"
        echo ""
        echo "Modos disponíveis:"
        echo "  full       - Mutação completa (padrão)"
        echo "  quick      - Mutação de módulos críticos"
        echo "  module     - Mutar módulo específico: module <path>"
        echo "  results    - Mostrar últimos resultados"
        echo "  html       - Gerar relatório HTML"
        echo "  clean      - Limpar cache"
        echo ""
        echo "Exemplos:"
        echo "  ./run-mutation-tests.sh full 30"
        echo "  ./run-mutation-tests.sh quick"
        echo "  ./run-mutation-tests.sh module sdk"
        exit 1
        ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
