#!/bin/bash

echo "Setting up Django API Scraper..."
echo

echo "Creating virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
python manage.py migrate

echo
echo "Setup complete!"
echo
echo "To start the server, run:"
echo "  source venv/bin/activate"
echo "  python manage.py runserver"
echo
echo "Then open http://127.0.0.1:8000 in your browser"

