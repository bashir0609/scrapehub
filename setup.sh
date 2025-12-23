#!/bin/bash

# Exit on error
set -o errexit

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Installing Playwright browsers..."
# Playwright needs these for scraping
playwright install chromium
playwright install-deps chromium

echo "Collecting static files..."
python manage.py collectstatic --no-input

echo "Running migrations..."
python manage.py migrate

echo "Setup complete!"

