#!/usr/bin/env python3
"""
Mutation Testing Script for workflow-app
Executa testes de mutação com opções configuráveis
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def run_command(cmd: list, description: str = ""):
    """Executa comando com feedback"""
    if description:
        print(f"\n{description}")
    print(f"  $ {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Erro ao executar: {' '.join(cmd)}")
        print(f"   Exit code: {e.returncode}")
        return False


def ensure_mutmut():
    """Garante que mutmut está instalado"""
    try:
        subprocess.run(["mutmut", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ mutmut não encontrado. Instalando...")
        run_command([sys.executable, "-m", "pip", "install", "mutmut>=2.4", "pytest-cov>=5.0"])


def print_header(title: str):
    """Imprime cabeçalho bonito"""
    print("\n" + "━" * 50)
    print(f"  {title}")
    print("━" * 50)


def cmd_full(timeout: int = 30):
    """Mutação completa"""
    print_header("MUTAÇÃO COMPLETA (5-10 min)")
    print(f"Timeout: {timeout}s\n")

    ensure_mutmut()

    run_command(
        ["mutmut", "run", "--timeout", str(timeout)],
        "🔬 Executando mutação completa...",
    )

    print("\n✅ Mutação concluída!\n")
    print("📊 Resultados:")
    subprocess.run(["mutmut", "results"])

    print("\n💡 Dica: Para ver mutantes sobreviventes:")
    print("   mutmut results --show-all")
    print("   mutmut show <id>")


def cmd_quick(timeout: int = 30):
    """Mutação rápida (módulos críticos)"""
    print_header("MUTAÇÃO RÁPIDA (módulos críticos)")
    print(f"Timeout: {timeout}s\n")

    ensure_mutmut()

    modules = [
        "src/workflow_app/domain/",
        "src/workflow_app/errors/",
        "src/workflow_app/sdk/",
    ]

    cmd = ["mutmut", "run", "--timeout", str(timeout)]
    for module in modules:
        cmd.extend(["--paths-to-mutate", module])

    print(f"Módulos: {', '.join(modules)}\n")

    run_command(cmd, "⚡ Executando...")

    print("\n✅ Mutação rápida concluída!")
    subprocess.run(["mutmut", "results"])


def cmd_module(module_path: str, timeout: int = 30):
    """Mutação de um módulo específico"""
    full_path = f"src/workflow_app/{module_path}"

    if not Path(full_path).exists():
        print(f"❌ Módulo não encontrado: {full_path}")
        sys.exit(1)

    print_header(f"MUTAÇÃO DO MÓDULO: {module_path}")
    print(f"Timeout: {timeout}s\n")

    ensure_mutmut()

    run_command(
        ["mutmut", "run", "--paths-to-mutate", full_path, "--timeout", str(timeout)],
        f"🔬 Mutando: {full_path}",
    )

    print("\n✅ Mutação concluída!")
    subprocess.run(["mutmut", "results"])


def cmd_results():
    """Mostra últimos resultados"""
    print_header("ÚLTIMOS RESULTADOS")
    print()
    subprocess.run(["mutmut", "results", "--show-all"])


def cmd_html():
    """Gera relatório HTML"""
    print_header("GERANDO RELATÓRIO HTML")
    print()

    ensure_mutmut()

    run_command(["mutmut", "html"], "🌐 Gerando HTML...")
    print("\n✅ Abra 'html/index.html' no navegador")


def cmd_clean():
    """Limpa cache"""
    print_header("LIMPANDO CACHE")
    print()

    cache_dir = PROJECT_ROOT / ".mutmut-cache"
    cache_file = PROJECT_ROOT / ".mutmut-id"

    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
        print(f"🗑️  Removido: {cache_dir}")

    if cache_file.exists():
        cache_file.unlink()
        print(f"🗑️  Removido: {cache_file}")

    print("\n✅ Cache limpo")


def print_usage():
    """Imprime ajuda"""
    print("\n" + "━" * 50)
    print("  WORKFLOW-APP — Mutation Testing")
    print("━" * 50)

    print("""
Modos disponíveis:
  full       - Mutação completa (padrão, 5-10 min)
  quick      - Mutação de módulos críticos
  module     - Mutar módulo específico
  results    - Mostrar últimos resultados
  html       - Gerar relatório HTML
  clean      - Limpar cache

Exemplos:
  python run_mutation_tests.py full 30
  python run_mutation_tests.py quick
  python run_mutation_tests.py module sdk
  python run_mutation_tests.py module pipeline/manager.py
  python run_mutation_tests.py results
  python run_mutation_tests.py html
  python run_mutation_tests.py clean

Argumentos:
  [mode]     - Modo de execução (padrão: full)
  [timeout]  - Timeout em segundos (padrão: 30)
""")


def main():
    """Entry point"""
    # Mudar para diretório do projeto
    os.chdir(PROJECT_ROOT)

    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    if mode == "full":
        cmd_full(timeout)
    elif mode == "quick":
        cmd_quick(timeout)
    elif mode == "module":
        if len(sys.argv) < 3:
            print("❌ Modo 'module' requer argumento: module <module_path>")
            print_usage()
            sys.exit(1)
        module = sys.argv[2]
        timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        cmd_module(module, timeout)
    elif mode == "results":
        cmd_results()
    elif mode == "html":
        cmd_html()
    elif mode == "clean":
        cmd_clean()
    elif mode in ["-h", "--help"]:
        print_usage()
    else:
        print(f"❌ Modo desconhecido: {mode}")
        print_usage()
        sys.exit(1)

    print("\n" + "━" * 50)


if __name__ == "__main__":
    main()
