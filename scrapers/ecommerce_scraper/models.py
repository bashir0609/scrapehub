from django.db import models


class EcommercePlatform(models.TextChoices):
    # Common platforms (for metadata/analytics only - not required for scraping)
    AMAZON = 'amazon', 'Amazon'
    EBAY = 'ebay', 'eBay'
    SHOPIFY = 'shopify', 'Shopify'
    ALIEXPRESS = 'aliexpress', 'AliExpress'
    ETSY = 'etsy', 'Etsy'
    DARAZ = 'daraz', 'Daraz'
    # Generic option - works with ANY e-commerce site
    OTHER = 'other', 'Other (Generic)'


class Product(models.Model):
    """Model to store product information from e-commerce platforms"""
    platform = models.CharField(max_length=50, choices=EcommercePlatform.choices)
    product_url = models.URLField(max_length=2000, unique=True)
    external_id = models.CharField(max_length=255, blank=True, help_text="ASIN, eBay Item ID, etc.")
    
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(max_length=2000, blank=True)
    
    # Store dynamic specs (Color, Size, Technical Specs) as JSON
    specifications = models.JSONField(default=dict, blank=True)
    
    rating = models.FloatField(null=True, blank=True)
    review_count = models.IntegerField(default=0)
    
    last_scraped_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_scraped_at']
        indexes = [
            models.Index(fields=['platform', '-last_scraped_at']),
            models.Index(fields=['external_id']),
        ]

    def __str__(self):
        return f"{self.platform} - {self.title[:50]}"


class PriceHistory(models.Model):
    """Model to track price history for products"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='price_history')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    availability = models.BooleanField(default=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scraped_at']
        indexes = [
            models.Index(fields=['product', '-scraped_at']),
        ]

    def __str__(self):
        return f"{self.product.title[:30]} - ${self.price} ({self.currency})"


class EcommerceScrapingRequest(models.Model):
    """Model to store e-commerce scraping requests"""
    urls = models.TextField(help_text="URLs to scrape, one per line or comma-separated")
    platform = models.CharField(max_length=50, choices=EcommercePlatform.choices, default='other', 
                                help_text="Platform name (for metadata only - scraping works with any site)")
    # Custom selectors (optional - if provided, overrides platform defaults)
    custom_selectors = models.JSONField(null=True, blank=True, 
                                       help_text="Custom CSS selectors: {'title': '...', 'price': '...', etc.}")
    status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])
    results = models.JSONField(null=True, blank=True, help_text="Scraped product data")
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.platform} - {self.status} - {self.created_at}"

