# ============================================================
# Workflow App — Dockerfile
# ============================================================
# Aplicação desktop Python/PySide6.
# Uso principal: CI/CD e testes headless (QT_QPA_PLATFORM=offscreen).
#
# Stages:
#   base  — Python + Qt headless + uv
#   deps  — dependências instaladas
#   dev   — deps + dev extras (pytest, ruff, mypy)
# ============================================================

# Stage 1: base — runtime + Qt libs + uv
FROM python:3.12-slim AS base

# Dependências de sistema necessárias para PySide6 headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libxcb-xfixes0 \
    && rm -rf /var/lib/apt/lists/*

# Instalar uv copiando do container oficial (sem curl/script)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Variáveis de ambiente padrão
ENV QT_QPA_PLATFORM=offscreen \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# Usuário não-root
RUN addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --ingroup appgroup appuser

# Stage 2: deps — instala dependências de produção
FROM base AS deps

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 3: dev — deps de desenvolvimento (pytest, ruff, mypy)
FROM base AS dev

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra dev

COPY --chown=appuser:appgroup . .

USER appuser

# Por padrão, roda a suite de testes headless
CMD ["uv", "run", "pytest", "tests/", "-v", "--timeout=30"]
