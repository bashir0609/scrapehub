from django.urls import path
from . import views

urlpatterns = [
    path('ecommerce-scraper/', views.ecommerce_scraper, name='ecommerce_scraper'),
    path('api/ecommerce-proxy-page/', views.ecommerce_proxy_page, name='ecommerce_proxy_page'),
    path('api/ecommerce-test-selectors/', views.ecommerce_test_selectors, name='ecommerce_test_selectors'),
]

