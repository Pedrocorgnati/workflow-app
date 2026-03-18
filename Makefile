.PHONY: run test lint install clean e2e integration all-tests \
        docker-build docker-test docker-lint docker-typecheck docker-ci \
        docker-ws-test docker-ci-full docker-clean infra-install infra-tailscale-check

install:
	pip install -e ".[dev]"

run:
	python -m workflow_app.main

test:
	python -m pytest tests/ -v --timeout=10

lint:
	python -m ruff check src/ tests/ || python -m flake8 src/ tests/

e2e:
	python -m pytest tests/e2e/ -v --timeout=30 --tb=short

integration:
	uv run pytest tests/integration/ -v --timeout=30 --tb=short

all-tests:
	python -m pytest tests/ -v --timeout=30

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
	find . -type f -name "*.pyc" -delete 2>/dev/null; \
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; \
	echo "Clean done"

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker build --target dev -t workflow-app:dev .

docker-test:
	docker compose --profile test run --rm test

docker-lint:
	docker compose --profile lint run --rm lint

docker-typecheck:
	docker compose --profile typecheck run --rm typecheck

docker-ci:
	docker compose --profile ci run --rm ci

docker-ws-test:
	docker compose --profile ws-test run --rm ws-test

docker-ci-full:
	docker compose --profile ci-full run --rm ci-full

docker-clean:
	docker compose down -v --remove-orphans
	docker image rm workflow-app:dev 2>/dev/null || true

# ── Infra (desktop + workflow-mobile) ─────────────────────────────────────────

infra-install:
	bash infra/scripts/install.sh

infra-tailscale-check:
	bash infra/scripts/tailscale-check.sh
