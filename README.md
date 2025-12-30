# ScrapeHub 🚀

<div align="center">

**A powerful, multi-platform web scraping application built with Django**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2.7-green.svg)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## 📖 Overview

ScrapeHub is a comprehensive web scraping platform that provides a unified interface for extracting data from various sources. Whether you need to scrape APIs, websites, social media platforms, or e-commerce sites, ScrapeHub has you covered.

### Why ScrapeHub?

- 🎯 **Universal API Client** - Scrape any API endpoint with ease
- 🔍 **Company Social Finder** - Extract company information and social media profiles
- 🛒 **E-commerce Scraper** - Generic scraper that works with any e-commerce website
- ⚡ **RapidAPI Integration** - Access thousands of APIs through RapidAPI marketplace (Coming Soon)
- 📝 **Ads.txt Checker** - Bulk validate ads.txt and app-ads.txt files
- 📱 **Social Media Scraper** - Extract data from social platforms (Coming Soon)
- 🎨 **Modern UI** - Beautiful, responsive web interface
- 🐳 **Docker Ready** - Easy deployment with Docker Compose
- 📊 **Progress Tracking** - Real-time progress monitoring for bulk operations
- 💾 **Export Options** - CSV, JSON export capabilities

---

## ✨ Features

### ✅ Universal API Client (Fully Implemented)

- 🚀 **Any API Support** - Scrape any API endpoint (POST, GET, PUT, DELETE)
- 📝 **Request History** - Store and view all scraping requests in database
- 🎨 **Modern Interface** - Clean, responsive web UI
- 🔒 **Error Handling** - Comprehensive error handling and validation
- 📊 **History View** - View and manage scraping request history
- 📋 **Network Tab Import** - Import headers and payload from browser Network tab
- 🎯 **Field Selection** - Select and filter specific fields from responses
- 📄 **Pagination** - Automatic pagination support
- 💾 **Export** - CSV/JSON export functionality
- 🔎 **Dynamic Fields** - Automatic field extraction from API responses
- 🔎 **Dynamic Fields** - Automatic field extraction from API responses

### ✅ Ads.txt Checker (Fully Implemented)

A powerful tool for bulk validation of **ads.txt** and **app-ads.txt** files.

- 🔍 **Bulk Validation** - Validate thousands of domains at once
- 📂 **Auto-Discovery** - Automatically finds homepage and ads.txt location
- 📝 **Content Analysis** - detailed analysis of ads.txt content
- 📊 **Status Codes** - Checks for 200 OK, 403, 404, etc.
- 🚀 **Async Processing** - Fast parallel processing using Django-Q
- 📋 **Live Results** - Real-time progress tracking
- 💾 **Export** - Export validation results as CSV/JSON

**URL**: `/ads-txt-checker/`

Formerly known as "Web Scraper", this tool focuses on finding company information and social media profiles.

- 🌐 **HTML Parsing** - BeautifulSoup for HTML parsing
- 🎯 **CSS Selectors** - Extract data using CSS selectors
- 🔍 **XPath Support** - XPath expression support
- ⚙️ **JavaScript Rendering** - Selenium & Playwright for JS-heavy sites
- 📦 **Bulk Scraping** - Scrape multiple URLs at once
- 📁 **File Upload** - Upload CSV/TXT files with URL lists
- 📊 **Progress Tracking** - Real-time progress monitoring
- 🔄 **Pagination** - Handle paginated content
- 📋 **Table Extraction** - Extract tables from web pages
- 🔗 **Link & Image Extraction** - Extract all links and images
- 📝 **Structured Data** - Extract JSON-LD and microdata
- 💾 **Export** - CSV/JSON export

**URL**: `/company-social-finder/`

### ✅ E-commerce Scraper (Fully Implemented)

A **generic e-commerce scraper** that works with **ANY e-commerce website** - no platform restrictions!

- 🌍 **Universal Support** - Works with any e-commerce site (Amazon, eBay, Shopify, AliExpress, Daraz, etc.)
- 🎨 **Visual Selector Builder** - Click elements to generate CSS selectors
- ⚙️ **Custom Selectors** - Configure CSS selectors for any site
- 📦 **Listing Pages** - Scrape category, search, tag, and collection pages
- 🔄 **Pagination** - Automatic pagination handling
- 💰 **Price Tracking** - Historical price tracking
- 📊 **Product Data** - Extract title, price, images, ratings, reviews
- 🎯 **Product Cards** - Extract multiple products from listing pages
- 🔍 **Anti-Bot Measures** - Configuration framework for stealth scraping
- 📈 **Price History** - Track price changes over time
- 💾 **Export** - Export product data and price history

**URL**: `/ecommerce-scraper/`

### 🚧 Coming Soon

- 📱 **Social Scraper** - Extract data from Twitter, Instagram, Facebook, LinkedIn, etc.
- ⚡ **RapidAPI Scraper** - Browse and execute thousands of APIs from RapidAPI marketplace

---

## 🚀 Quick Start

### Using Docker (Recommended)

1. **Clone the repository**:

```bash
git clone <repository-url>
cd "API Scraper"
```

2. **Start the application**:

```bash
docker-compose up --build
```

3. **Open your browser**:

```
http://localhost:8001
```

**Note**: The app runs on port `8001` when using Docker (mapped from container port 8000).

### Manual Installation

1. **Create virtual environment**:

```bash
python -m venv venv
```

2. **Activate virtual environment**:

   - **Windows**: `venv\Scripts\activate`
   - **Linux/Mac**: `source venv/bin/activate`

3. **Install dependencies**:

```bash
pip install -r requirements.txt
```

4. **Run migrations**:

```bash
python manage.py migrate
```

5. **Create superuser** (optional):

```bash
python manage.py createsuperuser
```

6. **Run development server**:

```bash
python manage.py runserver
```

7. **Open browser**:

```
http://127.0.0.1:8000
```

---

## 📁 Project Structure

```
scrapehub/                          # Django project folder
├── scrapehub/                      # Project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── scrapers/                       # All scrapers organized in one folder
│   ├── universal_api/              # Universal API Client
│   │   ├── models.py
│   │   ├── views.py
│   │   └── urls.py
│   │
│   ├── company_social_finder/      # Company Social Finder
│   │   ├── models.py
│   │   ├── views.py
│   │   └── urls.py
│   │
│   └── ecommerce_scraper/         # E-commerce Scraper
│       ├── models.py
│       ├── views.py
│       └── scraper_helpers.py
│
├── templates/                      # HTML templates
│   ├── index.html                 # Home page
│   └── scrapers/                   # Scraper templates
│       ├── company_social_finder.html
│       ├── ecommerce_scraper.html
│       ├── rapidapi_scraper.html
│       └── social_scraper.html
│
├── static/                         # Development static files
├── media/                          # User uploads
├── manage.py
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## 💻 Usage

### Web Interface

1. Navigate to `http://localhost:8001` (or `http://127.0.0.1:8000` for local)
2. Choose your scraper:
   - **Universal API Client** - `/` (home page)
   - **Company Social Finder** - `/company-social-finder/`
   - **E-commerce Scraper** - `/ecommerce-scraper/`
   - **Ads.txt Checker** - `/ads-txt-checker/`
3. Configure your scraping parameters
4. Click "Scrape" and view results
5. Export data as CSV or JSON

### API Endpoints

#### Universal API Client

**Endpoint**: `POST /api/scrape/`

**Request**:

```json
{
  "url": "https://example.com/api/endpoint",
  "method": "POST",
  "data": {
    "current": 1,
    "size": 10
  },
  "headers": {
    "Content-Type": "application/json"
  }
}
```

**Response**:

```json
{
  "success": true,
  "status_code": 200,
  "data": {
    /* API response */
  },
  "request_id": 1
}
```

#### Company Social Finder

**Single Page Scraping**: `POST /api/web-scrape/`

**Bulk Scraping**: `POST /api/web-scrape-bulk/`

**Progress Tracking**: `GET /api/web-scrape-progress/?request_id={id}`

**Bulk Results**: `GET /api/web-scrape-bulk-results/?request_id={id}`

#### E-commerce Scraper

**Generic Scraping**: `POST /api/ecommerce-scrape/`

**Price Tracking**: `POST /api/ecommerce-price-track/`

**Price History**: `GET /api/ecommerce-price-history/?product_id={id}`

#### Ads.txt Checker

**Submit Job**: `POST /ads-txt-checker/api/submit-job/`

**Request**:

```json
{
  "urls": ["example.com", "nytimes.com", "cnn.com"]
}
```

**Check Status**: `GET /jobs/api/status/{job_id}/`

**Get Results**: `GET /jobs/api/results/{job_id}/`

---

## 🐳 Docker Commands

```bash
# Start containers
docker-compose up

# Start in background
docker-compose up -d

# Stop containers
docker-compose down

# View logs
docker-compose logs -f

# Rebuild after code changes
docker-compose up --build

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Run migrations
docker-compose exec web python manage.py migrate

# Access Django shell
docker-compose exec web python manage.py shell

# Access database
docker-compose exec db psql -U postgres -d scrapehub
```

### Production Deployment

For production, use the production docker-compose file:

```bash
docker-compose -f docker-compose.prod.yml up -d
```

**Environment Variables** (set in `.env` or docker-compose):

- `SECRET_KEY`: Django secret key
- `POSTGRES_PASSWORD`: Database password
- `DEBUG`: Set to `False` in production

---

## 🔧 Configuration

### Database

The application uses:

- **SQLite** for local development (default)
- **PostgreSQL** when running in Docker or when `POSTGRES_DB` environment variable is set

### Static Files

- **Development**: Static files served from `static/` folder
- **Production**: Run `python manage.py collectstatic` to collect static files to `staticfiles/`

### Media Files

User uploads (bulk URL files) are stored in `media/bulk_inputs/`

---

## 📚 Documentation

- **[Implementation Plan](./SCRAPER_IMPLEMENTATION_PLAN.md)** - Detailed roadmap and feature specifications
- **API Documentation** - Available in the web interface
- **Admin Panel** - Access at `/admin/` (requires superuser)

---

## 🛠️ Technologies Used

- **Backend**: Django 4.2.7
- **Database**: PostgreSQL 15 / SQLite
- **Web Scraping**: BeautifulSoup4, lxml, Selenium, Playwright
- **HTTP Requests**: Requests
- **Containerization**: Docker & Docker Compose
- **Frontend**: HTML, CSS, JavaScript (Vanilla)

### Key Dependencies

```
Django==4.2.7
requests==2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
selenium>=4.15.0
playwright>=1.40.0
django-cors-headers==4.3.1
fake-useragent>=1.4.0
```

See `requirements.txt` for complete list.

---

## 🗺️ Roadmap

See [SCRAPER_IMPLEMENTATION_PLAN.md](./SCRAPER_IMPLEMENTATION_PLAN.md) for detailed implementation roadmap.

### Current Status

- ✅ Universal API Client - Fully implemented
- ✅ Company Social Finder - Core features complete
- ✅ E-commerce Scraper - Fully implemented (generic)
- ✅ Ads.txt Checker - Fully implemented
- 🚧 Social Scraper - Planned
- 🚧 RapidAPI Scraper - Planned

### Upcoming Features

- Advanced authentication handling
- Proxy support and rotation
- User-Agent rotation
- CAPTCHA solving integration
- Scheduled scraping tasks
- Real-time notifications
- Advanced analytics dashboard

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## ⚠️ Legal & Ethical Considerations

- **Respect robots.txt** - Always check and respect website robots.txt files
- **Rate Limiting** - Implement appropriate delays between requests
- **Terms of Service** - Review and comply with each platform's ToS
- **Data Privacy** - Handle scraped data responsibly
- **Anti-Bot Measures** - Some sites may block automated scraping

**Disclaimer**: This tool is for educational and legitimate business purposes only. Users are responsible for ensuring their use complies with applicable laws and website terms of service.

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Django community for the excellent framework
- BeautifulSoup, Selenium, and Playwright teams for scraping tools
- All contributors and users of this project

---

## 📞 Support

For issues, questions, or contributions:

- Open an issue on GitHub
- Check the [Implementation Plan](./SCRAPER_IMPLEMENTATION_PLAN.md) for detailed documentation

---

<div align="center">

**Made with ❤️ for the scraping community**

⭐ Star this repo if you find it useful!

</div>
