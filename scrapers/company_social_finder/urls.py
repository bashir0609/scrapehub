from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('company-social-finder/', views.web_scraper, name='company_social_finder'),
    path('social-scraper/', views.social_scraper, name='social_scraper'),
    # E-commerce scraper page moved to ecommerce_scraper app
    path('rapidapi-scraper/', views.rapidapi_scraper, name='rapidapi_scraper'),
    path('api/scrape/', views.scrape_api, name='scrape_api'),
    path('api/web-scrape/', views.web_scrape, name='web_scrape'),
    path('api/web-scrape-bulk/', views.web_scrape_bulk, name='web_scrape_bulk'),
    path('api/web-scrape-progress/', views.web_scrape_progress, name='web_scrape_progress'),
    path('api/web-scrape-bulk-results/', views.web_scrape_bulk_results, name='web_scrape_bulk_results'),
    path('api/scrape-paginated/', views.scrape_paginated, name='scrape_paginated'),
    path('api/scraping-progress/', views.get_scraping_progress, name='scraping_progress'),
    path('api/history/', views.get_scraping_history, name='scraping_history'),
    path('api/export/', views.export_data, name='export_data'),
    path('api/available-fields/', views.get_available_fields, name='get_available_fields'),
    # E-commerce Scraper endpoints
    path('api/ecommerce-scrape/', views.ecommerce_scrape, name='ecommerce_scrape'),
    path('api/ecommerce-scrape-amazon/', views.ecommerce_scrape_amazon, name='ecommerce_scrape_amazon'),
    path('api/ecommerce-scrape-ebay/', views.ecommerce_scrape_ebay, name='ecommerce_scrape_ebay'),
    path('api/ecommerce-scrape-progress/', views.ecommerce_scrape_progress, name='ecommerce_scrape_progress'),
    path('api/ecommerce-price-track/', views.ecommerce_price_track, name='ecommerce_price_track'),
    path('api/ecommerce-price-history/', views.ecommerce_price_history, name='ecommerce_price_history'),
]

