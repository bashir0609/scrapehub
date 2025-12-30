# ScrapeHub Development Server Launcher
# This script sets up PostgreSQL environment variables and runs the Django dev server

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ScrapeHub Development Server" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

Write-Host "Setting up PostgreSQL environment variables..." -ForegroundColor Yellow

# PostgreSQL Configuration (matching docker-compose.yml)
$env:POSTGRES_DB = "scrapehub"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "postgres"
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "5433"  # Docker maps PostgreSQL to port 5433 on host
$env:REDIS_HOST = "localhost"  # Docker maps Redis to port 6379 on host

# Django Configuration
$env:DEBUG = "1"
$env:SECRET_KEY = "django-insecure-your-secret-key-change-in-production"

Write-Host "`nDatabase Configuration:" -ForegroundColor Green
Write-Host "  Database: PostgreSQL" -ForegroundColor White
Write-Host "  Host: localhost:5433" -ForegroundColor White
Write-Host "  Database Name: scrapehub" -ForegroundColor White
Write-Host "  User: postgres" -ForegroundColor White

Write-Host "`nIMPORTANT: Make sure PostgreSQL is running in Docker:" -ForegroundColor Yellow
Write-Host "  docker-compose up -d db" -ForegroundColor Cyan

Write-Host "`nStarting Django development server..." -ForegroundColor Yellow
Write-Host "Server will be available at: http://localhost:8000" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server`n" -ForegroundColor Yellow

# Run Django development server
python manage.py runserver

