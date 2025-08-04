# Use Python 3.13 slim image
FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Set work directory
WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y \
    g++ \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /app/logs \
    && pip install uv

# Copy pyproject.toml, README.md and lock file
COPY pyproject.toml README.md ./

# Install Python dependencies using uv
RUN uv pip install --system .

# Copy project
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app

# Make start script executable
COPY start_prod.sh /app/start_prod.sh
RUN chmod +x /app/start_prod.sh

USER app

# Expose port
EXPOSE 8000

# Run the application
CMD ["/app/start_prod.sh"] 