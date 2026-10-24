.PHONY: help setup setup-backend setup-frontend install-hooks backend frontend ingest \
        test test-local lint lint-fix check clean clean-all dev-shell

.DEFAULT_GOAL := help
VENV := .venv
export PATH := $(CURDIR)/.runtime/node/bin:$(PATH)
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
UVICORN := $(PYTHON) -m uvicorn
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff

# ---------------------------------------------------------------------------
# Python 3.11 resolution — works on Linux, macOS, and any CI runner
#   Tries: python3.11 → python3 (if it is 3.11) → python (if it is 3.11)
#   Fails with a clear message pointing to the dev container.
# ---------------------------------------------------------------------------

define _check_ver
$(shell $(1) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null)
endef

ifeq ($(call _check_ver,$(PYTHON)),3.11)
  PYTHON311 := $(PYTHON)
else ifeq ($(call _check_ver,.runtime/python/cpython-3.11-macos-aarch64-none/bin/python3.11),3.11)
  PYTHON311 := .runtime/python/cpython-3.11-macos-aarch64-none/bin/python3.11
else ifeq ($(call _check_ver,python3.11),3.11)
  PYTHON311 := python3.11
else ifeq ($(call _check_ver,python3),3.11)
  PYTHON311 := python3
else ifeq ($(call _check_ver,python),3.11)
  PYTHON311 := python
else
  PYTHON311 :=
endif

.python-check:
	@if [ -z "$(PYTHON311)" ]; then \
	  echo ""; \
	  echo "ERROR: Python 3.11 not found on PATH."; \
	  echo ""; \
	  echo "Recommended: use the dev container — it ships Python 3.11 automatically."; \
	  echo "  VS Code:  'Dev Containers: Reopen in Container'"; \
	  echo "  CLI:      make dev-shell"; \
	  echo ""; \
	  echo "Or install Python 3.11 manually and ensure it appears on PATH as"; \
	  echo "  python3.11, python3, or python."; \
	  echo ""; \
	  exit 1; \
	fi
	@echo "Python 3.11 OK  ($(PYTHON311))"

# ---------------------------------------------------------------------------
# Node >= 24 resolution — works on Linux and macOS
# ---------------------------------------------------------------------------

.node-check:
	@if ! command -v node >/dev/null 2>&1; then \
	  echo ""; \
	  echo "ERROR: node not found."; \
	  echo ""; \
	  echo "Recommended: use the dev container — it ships Node 24 automatically."; \
	  echo "  VS Code:  'Dev Containers: Reopen in Container'"; \
	  echo "  CLI:      make dev-shell"; \
	  echo ""; \
	  exit 1; \
	fi
	@NODE_MAJOR=$$(node -e "process.stdout.write(String(process.versions.node.split('.')[0]))"); \
	if [ "$$NODE_MAJOR" -lt 24 ]; then \
	  echo "ERROR: Node.js >= 24 required, found $$(node --version)"; \
	  echo "       Use the dev container: make dev-shell"; \
	  exit 1; \
	fi
	@echo "Node $$(node --version) / npm $$(npm --version) OK"

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Recommended workflow:"
	@echo "    VS Code: 'Dev Containers: Reopen in Container'  (runs make setup automatically)"
	@echo "    CLI:     make dev-shell   then   make setup"

# ---------------------------------------------------------------------------
# Dev container shell — for non-VS Code users
# ---------------------------------------------------------------------------

dev-shell: ## Build the dev container (Python 3.11 + Node 24), run setup, drop into bash
	docker build -t aegis-rag-dev -f .devcontainer/Dockerfile .
	docker run --rm -it \
	  -v "$(CURDIR)":/workspace \
	  -w /workspace \
	  -p 8000:8000 \
	  -p 5173:5173 \
	  aegis-rag-dev bash

# ---------------------------------------------------------------------------
# Setup (run inside the dev container, or locally if Python 3.11 is present)
# ---------------------------------------------------------------------------

setup: setup-backend setup-frontend install-hooks ## Full first-time setup (backend + frontend + git hooks)
	@echo ""
	@echo "Setup complete. Next steps:"
	@echo "  1. Add PDFs to data/"
	@echo "  2. make ingest"
	@echo "  3. make backend     (terminal 1)"
	@echo "  4. make frontend    (terminal 2)"
	@echo "  5. Open http://localhost:5173"

install-hooks: ## Install git hooks from scripts/ into .git/hooks/
	@if git rev-parse --git-dir >/dev/null 2>&1; then \
	  hooks=$$(git rev-parse --git-path hooks); \
	  mkdir -p "$$hooks"; cp scripts/pre-commit "$$hooks/pre-commit"; \
	  chmod +x "$$hooks/pre-commit"; echo "Git hook installed"; \
	else echo "No Git repository; skipping hooks"; fi

setup-backend: .python-check ## Install Python deps and spacy model
	@test -x $(PYTHON) || "$(PYTHON311)" -m venv $(VENV)
	@$(PYTHON) -c "import sys; assert sys.version_info[:2] == (3, 11), 'Existing .venv must use Python 3.11'"
	$(PIP) install --quiet --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-test.txt
	$(PIP) install --quiet "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit if needed")

setup-frontend: .node-check ## Install frontend npm dependencies
	cd frontend && npm ci

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

backend: .backend-check ## Start the FastAPI backend (http://localhost:8000)
	PYTHONPATH=. $(UVICORN) app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000

frontend: .frontend-check ## Start the Vite dev server (http://localhost:5173)
	cd frontend && npm run dev

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

ingest: .backend-check ## Ingest all PDFs in data/ into ChromaDB
	PYTHONPATH=. $(PYTHON) -m app.rag.ingest

# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------

compile-deps: ## Recompile requirements.txt from requirements.in (runs inside dev container)
	docker build -q -t aegis-rag-dev -f .devcontainer/Dockerfile .
	docker run --rm \
	  -v "$(CURDIR)":/workspace \
	  -w /workspace \
	  aegis-rag-dev \
	  pip-compile requirements.in \
	    --output-file requirements.txt \
	    --strip-extras \
	    --resolver=backtracking
	@echo ""
	@echo "requirements.txt updated. Review the diff then run: make setup-backend"

# ---------------------------------------------------------------------------
# Test & lint
# ---------------------------------------------------------------------------

test: ## Run pytest in Docker container (Python 3.11, all dependencies pinned)
	docker build -q --target test -t aegis-rag-test -f Dockerfile .
	docker run --rm \
	  -v "$(CURDIR)":/workspace \
	  aegis-rag-test

test-local: ## Run pytest locally (requires Python 3.11 venv)
	PYTHONPATH=. $(PYTEST) tests/ -v

lint: ## Run ruff linter
	$(RUFF) check .

lint-fix: ## Run ruff with auto-fix
	$(RUFF) check . --fix

check: lint test ## Run lint + tests (in Docker)

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

clean: ## Remove generated files (chroma data, telemetry db, caches)
	rm -rf .chroma/ telemetry.db llms-txt/*.md
	find . -type d -name __pycache__ | grep -v .venv | xargs rm -rf
	find . -type d -name .pytest_cache | grep -v .venv | xargs rm -rf
	find . -type d -name .ruff_cache | grep -v .venv | xargs rm -rf

clean-all: clean ## Also remove venv and frontend node_modules
	rm -rf $(VENV) frontend/node_modules frontend/dist

.PHONY: doctor .backend-check .frontend-check .python-check .node-check
.backend-check:
	@test -x $(PYTHON) || (echo "Run make setup-backend first"; exit 1)
	@$(PYTHON) -c "import sys; assert sys.version_info[:2] == (3, 11); import fastapi, uvicorn, chromadb, ollama, spacy, en_core_web_sm, aiosqlite"

.frontend-check: .node-check
	@test -d frontend/node_modules || (echo "Run make setup-frontend first"; exit 1)

doctor: .backend-check .frontend-check ## Check dependencies, models and local configuration
	$(PIP) check
	$(PYTHON) -m app.doctor

.PHONY: deploy-demo verify-demo rollback-demo evaluate-demo
deploy-demo: ## Pull and verify a complete published release (VERSION=full commit SHA)
	$(PYTHON) scripts/deploy_demo.py deploy --version "$(VERSION)"

verify-demo: ## Verify isolated release ingestion, two chat turns and feedback
	$(PYTHON) scripts/deploy_demo.py verify

rollback-demo: ## Restore the previous verified release, preserving demo data
	$(PYTHON) scripts/deploy_demo.py rollback

evaluate-demo: ## Run a reporting-only real model quality and drift evaluation
	$(PYTHON) scripts/deploy_demo.py evaluate
