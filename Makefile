.PHONY: help install dev-install migrate makemigrations runserver test lint format clean docker-build docker-up docker-down

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	uv pip install -e .

dev-install: ## Install development dependencies
	uv pip install -e ".[dev]"

migrate: ## Apply database migrations
	uv run manage.py migrate

makemigrations: ## Create new migrations
	uv run manage.py makemigrations

runserver: ## Start development server
	uv run manage.py runserver

test: ## Run tests
	uv run pytest

lint: ## Run linting checks
	uv run ruff check .
	uv run mypy .

format: ## Format code
	uv run ruff format .
	uv run black .
	uv run isort .

clean: ## Clean up temporary files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache

docker-build: ## Build Docker image
	docker-compose build

docker-up: ## Start Docker services
	docker-compose up -d

docker-down: ## Stop Docker services
	docker-compose down

docker-logs: ## Show Docker logs
	docker-compose logs -f

shell: ## Start Django shell
	uv run manage.py shell

collectstatic: ## Collect static files
	uv run manage.py collectstatic --noinput

createsuperuser: ## Create superuser
	uv run manage.py createsuperuser

check: ## Run Django system check
	uv run manage.py check

setup: install migrate ## Initial setup
	@echo "Setup complete! Run 'make runserver' to start the development server."

dev-setup: dev-install migrate ## Development setup
	@echo "Development setup complete! Run 'make runserver' to start the development server."

uv-install: ## Install dependencies using uv
	uv sync

uv-dev-install: ## Install development dependencies using uv
	uv sync --extra dev

uv-run: ## Run a command with uv (usage: make uv-run cmd="your-command")
	uv run $(cmd) 