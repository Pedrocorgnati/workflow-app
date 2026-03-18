# Guia de Contribuição

## Estratégia de Branches

| Branch | Propósito | Deploy |
|--------|-----------|--------|
| `main` | Código estável (protegida, requer PR + CI verde) | GitHub Release em cada tag `v*.*.*` |
| `develop` | Integração de features | — |
| `feature/{slug}` | Features em desenvolvimento | PR para `develop` |
| `fix/{slug}` | Correções de bugs | PR para `develop` |
| `hotfix/{slug}` | Correções urgentes | PR direto para `main` + cherry-pick para `develop` |

## Fluxo de Trabalho

```
1. Criar branch a partir de develop:
   git checkout -b feature/minha-feature develop

2. Implementar mudanças com testes

3. Garantir CI local:
   uv run ruff check src/ tests/
   uv run pytest tests/ --timeout=30 --ignore=tests/test_vault.py

4. Criar PR para develop usando o template fornecido

5. CI deve passar (lint, type-check, testes multi-plataforma)

6. Aguardar aprovação de pelo menos 1 revisor

7. Merge para develop

8. Quando pronto para release:
   git tag v1.2.3
   git push origin v1.2.3
   → GitHub Actions cria binários para Linux/macOS/Windows e publica GitHub Release
```

## Convenções de Commits

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:      nova funcionalidade
fix:       correção de bug
docs:      apenas documentação
refactor:  sem impacto funcional
test:      adição/correção de testes
chore:     build, config, dependências
perf:      melhoria de performance
```

Exemplos:
```
feat(sdk-adapter): add permission hook for manual mode
fix(pipeline-manager): resolve asyncio future deadlock on cancel
test(command-queue): add interactive advance widget tests
```

## Setup do Ambiente de Desenvolvimento

```bash
# Clonar
git clone git@github.com:Pedrocorgnati/workflow-app.git
cd workflow-app

# Instalar dependências (requer uv — https://docs.astral.sh/uv/)
uv sync --extra dev

# Rodar aplicação
uv run workflow-app

# Rodar testes
uv run pytest tests/ -v --timeout=30 --ignore=tests/test_vault.py

# Lint
uv run ruff check src/ tests/

# Seed do banco de dados
uv run python scripts/seed.py
```

## Versionamento

Seguir [SemVer](https://semver.org/):

- `MAJOR.x.x` — quebra de compatibilidade
- `x.MINOR.x` — nova funcionalidade (retrocompatível)
- `x.x.PATCH` — correção de bug

Pré-releases: `v1.0.0-rc.1`, `v1.0.0-beta.2`, `v1.0.0-alpha.1`
