#!/bin/bash

# UV Runner Script for Django project
# Usage: ./scripts/uv-run.sh [command] [args...]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    print_error "uv is not installed. Please install it first."
    exit 1
fi

# Get the command from arguments
if [ $# -eq 0 ]; then
    print_error "No command specified"
    echo "Usage: $0 [command] [args...]"
    echo ""
    echo "Available commands:"
    echo "  server, runserver    - Start Django development server"
    echo "  migrate              - Apply database migrations"
    echo "  makemigrations       - Create new migrations"
    echo "  shell                - Start Django shell"
    echo "  test                 - Run tests"
    echo "  lint                 - Run linting"
    echo "  format               - Format code"
    echo "  check                - Run Django system check"
    echo "  collectstatic        - Collect static files"
    echo "  createsuperuser      - Create superuser"
    echo "  install              - Install dependencies"
    echo "  install-dev          - Install development dependencies"
    echo "  custom [command]     - Run custom command"
    exit 1
fi

COMMAND=$1
shift

case $COMMAND in
    "server"|"runserver")
        print_info "Starting Django development server..."
        uv run manage.py runserver "$@"
        ;;
    "migrate")
        print_info "Applying database migrations..."
        uv run manage.py migrate "$@"
        ;;
    "makemigrations")
        print_info "Creating new migrations..."
        uv run manage.py makemigrations "$@"
        ;;
    "shell")
        print_info "Starting Django shell..."
        uv run manage.py shell "$@"
        ;;
    "test")
        print_info "Running tests..."
        uv run pytest "$@"
        ;;
    "lint")
        print_info "Running linting checks..."
        uv run ruff check . "$@"
        uv run mypy . "$@"
        ;;
    "format")
        print_info "Formatting code..."
        uv run ruff format . "$@"
        uv run black . "$@"
        uv run isort . "$@"
        ;;
    "check")
        print_info "Running Django system check..."
        uv run manage.py check "$@"
        ;;
    "collectstatic")
        print_info "Collecting static files..."
        uv run manage.py collectstatic --noinput "$@"
        ;;
    "createsuperuser")
        print_info "Creating superuser..."
        uv run manage.py createsuperuser "$@"
        ;;
    "install")
        print_info "Installing dependencies..."
        uv sync "$@"
        ;;
    "install-dev")
        print_info "Installing development dependencies..."
        uv sync --extra dev "$@"
        ;;
    "custom")
        if [ $# -eq 0 ]; then
            print_error "No custom command specified"
            exit 1
        fi
        print_info "Running custom command: $*"
        uv run "$@"
        ;;
    *)
        print_error "Unknown command: $COMMAND"
        echo "Run '$0' without arguments to see available commands"
        exit 1
        ;;
esac

print_success "Command completed successfully!" 