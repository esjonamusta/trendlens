.DEFAULT_GOAL := help
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install run test lint fmt clean docker-build docker-up docker-down

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install      Create venv and install dependencies"
	@echo "  run          Start the dev server at http://localhost:8000"
	@echo "  test         Run the test suite"
	@echo "  lint         Run ruff linter"
	@echo "  fmt          Auto-fix lint issues"
	@echo "  clean        Remove venv and cache files"
	@echo ""
	@echo "  docker-build Build the Docker image"
	@echo "  docker-up    Start with Docker Compose (detached)"
	@echo "  docker-down  Stop Docker Compose"

install:
	python -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ""
	@echo "Done. Activate with: source $(VENV)/bin/activate"
	@echo "Then copy .env.example to .env and add your API keys."

run:
	$(PYTHON) -m uvicorn main:app --reload

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff check --fix .

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker-build:
	docker build -t trendlens .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
