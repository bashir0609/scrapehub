from django.contrib import admin
from .models import WebScrapingRequest, WebScrapingResult, BulkWebScrapingRequest


@admin.register(WebScrapingRequest)
class WebScrapingRequestAdmin(admin.ModelAdmin):
    list_display = ['url', 'method', 'status_code', 'created_at']
    list_filter = ['method', 'created_at']
    search_fields = ['url']


@admin.register(WebScrapingResult)
class WebScrapingResultAdmin(admin.ModelAdmin):
    list_display = ['request', 'field_name', 'created_at']
    list_filter = ['created_at']
    search_fields = ['request__url', 'field_name']


@admin.register(BulkWebScrapingRequest)
class BulkWebScrapingRequestAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'total_urls', 'completed_urls', 'failed_urls', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name']

