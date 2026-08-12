.PHONY: help install install-all dev test test-cov lint format run api clean docker-build docker-up docker-down check web-install web-build web-dev all

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install core + API + dev dependencies
	pip install -r requirements.txt

install-all: ## Install all dependencies including RAG
	pip install -r requirements.txt -r requirements-rag.txt

dev: ## Install dev dependencies
	pip install -r requirements-dev.txt

test: ## Run offline tests
	python -m pytest tests/ -v -m "not network" --ignore=tests/probes

test-cov: ## Run offline tests with coverage
	python -m pytest tests/ -v -m "not network" --ignore=tests/probes --cov=backend --cov-report=term-missing

lint: ## Run linter
	ruff check backend/ frontend/ tests/
	ruff format --check backend/ frontend/ tests/

format: ## Format code
	ruff format backend/ frontend/ tests/

run: ## Run Streamlit dashboard
	streamlit run frontend/dashboard.py

api: ## Run FastAPI backend
	uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

web-install: ## Install Vite React frontend dependencies
	cd apps/web && npm install

web-build: ## Build Vite React frontend
	cd apps/web && npm run build

web-dev: ## Run Vite React dev server
	cd apps/web && npm run dev

clean: ## Clean cache and temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache

docker-build: ## Build Docker image
	docker-compose build

docker-up: ## Start services
	docker-compose up -d

docker-down: ## Stop services
	docker-compose down

check: lint test ## Run lint + test

all: install check ## Install + lint + test
