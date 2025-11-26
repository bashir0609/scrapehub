from django.contrib import admin
from .models import Product, PriceHistory, EcommerceScrapingRequest, EcommercePlatform


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'platform', 'external_id', 'rating', 'review_count', 'last_scraped_at', 'created_at')
    list_filter = ('platform', 'created_at', 'last_scraped_at')
    search_fields = ('title', 'external_id', 'brand', 'description')
    readonly_fields = ('created_at', 'last_scraped_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('platform', 'product_url', 'external_id', 'title', 'description', 'brand')
        }),
        ('Media', {
            'fields': ('image_url',)
        }),
        ('Specifications', {
            'fields': ('specifications',)
        }),
        ('Ratings', {
            'fields': ('rating', 'review_count')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_scraped_at')
        }),
    )


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'price', 'currency', 'availability', 'scraped_at')
    list_filter = ('currency', 'availability', 'scraped_at')
    search_fields = ('product__title', 'product__external_id')
    readonly_fields = ('scraped_at',)
    date_hierarchy = 'scraped_at'


@admin.register(EcommerceScrapingRequest)
class EcommerceScrapingRequestAdmin(admin.ModelAdmin):
    list_display = ('platform', 'status', 'created_at', 'completed_at')
    list_filter = ('platform', 'status', 'created_at')
    search_fields = ('urls',)
    readonly_fields = ('created_at', 'completed_at')
    fieldsets = (
        ('Request Information', {
            'fields': ('platform', 'urls', 'status')
        }),
        ('Results', {
            'fields': ('results', 'error_message')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at')
        }),
    )

