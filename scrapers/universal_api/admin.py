from django.contrib import admin
from .models import ScrapingRequest


@admin.register(ScrapingRequest)
class ScrapingRequestAdmin(admin.ModelAdmin):
    list_display = ['url', 'method', 'status_code', 'created_at', 'completed_at']
    list_filter = ['method', 'status_code', 'created_at']
    search_fields = ['url']
    readonly_fields = ['created_at', 'completed_at', 'response_data', 'status_code', 'error_message']
