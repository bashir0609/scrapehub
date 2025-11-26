from django.db import models


class ScrapingRequest(models.Model):
    """Model to store API scraping requests and results"""
    url = models.URLField(max_length=500)
    method = models.CharField(max_length=10, default='POST')
    request_data = models.JSONField(default=dict)
    response_data = models.JSONField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.method} {self.url} - {self.created_at}"
