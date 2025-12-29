
import os
import django
import sys

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scrapehub.settings")
django.setup()

from scrapers.jobs.models import Job

print("Listing last 5 jobs:")
try:
    jobs = Job.objects.all().order_by('-created_at')[:5]
    for j in jobs:
        print(f"ID: {j.job_id} | Status: {j.status} | Created: {j.created_at}")
    
    if not jobs:
        print("No jobs found in database.")
        
except Exception as e:
    print(f"Error listing jobs: {e}")
