# Use Python 3.12 slim image (required for Django 6.0)
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Selenium (simpler and more reliable in Docker)
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/* || true

# Install Playwright browsers
RUN playwright install chromium || true
RUN playwright install-deps chromium || true

# Copy project
COPY . /app/

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Command for production (migrations + worker + gunicorn)
CMD ["sh", "-c", "python manage.py migrate && python manage.py runworker & exec gunicorn scrapehub.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
