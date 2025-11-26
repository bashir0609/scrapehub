# How to Run ScrapeHub

## Quick Start

### 1. Activate Virtual Environment

**Windows:**
```bash
.\venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 2. Run Database Migrations

```bash
python manage.py migrate
```

This will create all necessary database tables for:
- `scrapers.universal_api` - Universal API Client
- `scrapers.company_social_finder` - Company Social Finder
- `scrapers.ecommerce_scraper` - E-commerce Scraper

### 3. Create Superuser (Optional - for admin access)

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin user.

### 4. Run the Development Server

```bash
python manage.py runserver
```

### 5. Open in Browser

Navigate to:
```
http://127.0.0.1:8000
```

## Available Pages

- **Home / Universal API Client**: `http://127.0.0.1:8000/`
- **Company Social Finder**: `http://127.0.0.1:8000/web-scraper/`
- **E-commerce Scraper**: `http://127.0.0.1:8000/ecommerce-scraper/`
- **Admin Panel**: `http://127.0.0.1:8000/admin/`

## Project Structure

```
scrapehub/                    # Django project folder
├── settings.py
├── urls.py
└── wsgi.py

scrapers/                     # All scrapers
├── universal_api/            # Universal API Client
├── company_social_finder/    # Company Social Finder
└── ecommerce_scraper/        # E-commerce Scraper
```

## Troubleshooting

### If migrations fail:
1. Check that all apps are in `INSTALLED_APPS` in `scrapehub/settings.py`
2. Make sure virtual environment is activated
3. Try: `python manage.py migrate --run-syncdb`

### If port 8000 is already in use:
```bash
python manage.py runserver 8001
```

### To check for errors:
```bash
python manage.py check
```

## First Time Setup

If this is your first time running the app:

1. **Install dependencies** (if not already done):
   ```bash
   pip install -r requirements.txt
   ```

2. **Install Playwright browsers** (for JavaScript rendering):
   ```bash
   playwright install chromium
   ```

3. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

4. **Create superuser** (optional):
   ```bash
   python manage.py createsuperuser
   ```

5. **Run server**:
   ```bash
   python manage.py runserver
   ```

## Using Docker (Alternative)

If you prefer Docker:

```bash
docker-compose up --build
```

Then access at: `http://127.0.0.1:8001` (port 8001 for dev, 8000 for production)

