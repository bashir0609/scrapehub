"""
URL configuration for scrapehub project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('scrapers.universal_api.urls')),
    path('', include('scrapers.company_social_finder.urls')),
    path('', include('scrapers.ecommerce_scraper.urls')),
    path('ads-txt-checker/', include('scrapers.ads_txt_checker.urls')),
    path('jobs/', include('scrapers.jobs.urls')),
    path('others/', include('scrapers.others_urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

