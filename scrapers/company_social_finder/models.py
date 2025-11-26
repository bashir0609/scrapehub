from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator


class WebScrapingRequest(models.Model):
    """Model to store web scraping requests"""
    url = models.URLField(max_length=500)
    selectors = models.JSONField(default=dict, help_text="CSS selectors or XPath expressions")
    method = models.CharField(max_length=20, default='beautifulsoup', choices=[
        ('beautifulsoup', 'BeautifulSoup (HTML)'),
        ('css', 'CSS Selector'),
        ('xpath', 'XPath'),
        ('selenium', 'Selenium (JavaScript)'),
    ])
    headers = models.JSONField(default=dict, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    wait_time = models.FloatField(default=0, help_text="Wait time in seconds before scraping")
    response_data = models.JSONField(null=True, blank=True)
    extracted_data = models.JSONField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Web Scrape: {self.url} - {self.created_at}"


class WebScrapingResult(models.Model):
    """Model to store individual extracted data items from web scraping"""
    request = models.ForeignKey(WebScrapingRequest, on_delete=models.CASCADE, related_name='results')
    field_name = models.CharField(max_length=200)
    field_value = models.TextField()
    selector = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['request', 'field_name']
    
    def __str__(self):
        return f"{self.request.url} - {self.field_name}"


class BulkWebScrapingRequest(models.Model):
    """Model to store bulk web scraping requests"""
    # Legacy field - kept for backward compatibility
    urls = models.JSONField(null=True, blank=True, help_text="List of URLs to scrape (legacy)")
    
    # New input options: Text area OR File
    urls_text = models.TextField(blank=True, help_text="Paste URLs here, one per line")
    urls_file = models.FileField(
        upload_to='bulk_inputs/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=['csv', 'txt'])],
        help_text="Upload a CSV or TXT file with URLs (one per line)"
    )
    
    name = models.CharField(max_length=255, blank=True, help_text="Optional name for this scraping request")
    selectors = models.JSONField(default=dict, help_text="CSS selectors or XPath expressions")
    method = models.CharField(max_length=20, default='beautifulsoup')
    headers = models.JSONField(default=dict, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    wait_time = models.FloatField(default=0)
    total_urls = models.IntegerField(default=0)
    completed_urls = models.IntegerField(default=0)
    failed_urls = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])
    results = models.JSONField(null=True, blank=True, help_text="Combined results from all URLs")
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def get_url_list(self):
        """Helper to combine URLs from text, file, and legacy JSON field"""
        urls = []
        
        # 1. Process text input
        if self.urls_text:
            urls.extend([u.strip() for u in self.urls_text.splitlines() if u.strip()])
        
        # 2. Process file input
        if self.urls_file:
            try:
                self.urls_file.open('r')
                content = self.urls_file.read()
                
                # Handle bytes vs str depending on storage
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                
                lines = content.splitlines()
                urls.extend([l.strip() for l in lines if l.strip()])
                self.urls_file.close()
            except Exception as e:
                print(f"Error reading file: {e}")
        
        # 3. Process legacy JSON field (for backward compatibility)
        if self.urls and isinstance(self.urls, list):
            urls.extend([str(u).strip() for u in self.urls if u])
        
        # Remove duplicates and empty strings
        return list(set([u for u in urls if u]))
    
    def __str__(self):
        return f"Bulk Scrape: {self.total_urls} URLs - {self.status}"

