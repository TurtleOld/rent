.PHONY: help install dev-install migrate makemigrations runserver test lint format clean docker-build docker-up docker-down

help:
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:
	uv pip install -e .

dev-install:
	uv pip install -e ".[dev]"

migrate:
	uv run manage.py migrate

makemigrations:
	uv run manage.py makemigrations

runserver:
	uv run manage.py runserver

test:
	uv run pytest

lint:
	uv run ruff check . $(if $(FIX),--fix)
	uv run mypy .

format:
	uv run ruff format .
	uv run isort .

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

shell:
	uv run manage.py shell

collectstatic:
	uv run manage.py collectstatic --noinput

createsuperuser:
	uv run manage.py createsuperuser

check:
	uv run manage.py check

setup: install migrate
	@echo "Setup complete! Run 'make runserver' to start the development server."

dev-setup: dev-install migrate
	@echo "Development setup complete! Run 'make runserver' to start the development server."

uv-install:
	uv sync

uv-dev-install:
	uv sync --extra dev

uv-run:
	uv run $(cmd) 