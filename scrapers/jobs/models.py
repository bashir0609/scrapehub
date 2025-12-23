from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid

class Job(models.Model):
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('paused', 'Paused'),
        ('auto_paused', 'Auto-Paused'),
    ]
    
    SCRAPER_CHOICES = [
        ('ads_txt_checker', 'Ads.txt Checker'),
        ('company_social_finder', 'Company Social Finder'),
        ('social_scraper', 'Social Scraper'),
        ('ecommerce_scraper', 'E-commerce Scraper'),
        ('rapidapi_scraper', 'RapidAPI Scraper'),
    ]
    
    job_id = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    scraper_type = models.CharField(max_length=50, choices=SCRAPER_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    total_items = models.IntegerField(default=0)
    processed_items = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    results_data = models.JSONField(null=True, blank=True)  # Store results as JSON
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    auto_pause_reason = models.TextField(null=True, blank=True)
    input_data = models.JSONField(null=True, blank=True)  # Store original input (e.g. list of URLs)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.get_scraper_type_display()} - {self.job_id[:8]}"
    
    @property
    def progress_percentage(self):
        if self.total_items == 0:
            return 0
        return int((self.processed_items / self.total_items) * 100)
    
    @property
    def is_active(self):
        return self.status in ['running', 'paused', 'auto_paused']
    
    @classmethod
    def cleanup_old_jobs(cls):
        """Delete jobs older than 30 days"""
        cutoff_date = timezone.now() - timedelta(days=30)
        old_jobs = cls.objects.filter(created_at__lt=cutoff_date)
        count = old_jobs.count()
        old_jobs.delete()
        return count


class JobEvent(models.Model):
    EVENT_TYPES = [
        ('started', 'Started'),
        ('paused', 'Paused'),
        ('auto_paused', 'Auto-Paused'),
        ('resumed', 'Resumed'),
        ('auto_resumed', 'Auto-Resumed'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('progress', 'Progress Update'),
    ]
    
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.job.job_id[:8]} - {self.get_event_type_display()}"
