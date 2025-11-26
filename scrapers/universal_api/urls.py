from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/scrape/', views.scrape_api, name='scrape_api'),
    path('api/scrape-paginated/', views.scrape_paginated, name='scrape_paginated'),
    path('api/scraping-history/', views.get_scraping_history, name='get_scraping_history'),
    path('api/scraping-progress/', views.get_scraping_progress, name='get_scraping_progress'),
    path('api/export-data/', views.export_data, name='export_data'),
    path('api/available-fields/', views.get_available_fields, name='get_available_fields'),
]

