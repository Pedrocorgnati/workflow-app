.PHONY: run test lint install clean

install:
	pip install -e ".[dev]"

run:
	python -m workflow_app.main

test:
	python -m pytest tests/ -v --timeout=10

lint:
	python -m ruff check src/ tests/ || python -m flake8 src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
	find . -type f -name "*.pyc" -delete 2>/dev/null; \
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; \
	echo "Clean done"
