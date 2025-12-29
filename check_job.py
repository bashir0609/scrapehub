
import os
import django
import sys

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scrapehub.settings")
django.setup()

from scrapers.jobs.models import Job

job_id = "8cefebfd-5ee6-40de-a35c-db75d36ec624"
log_path = r"e:\Apps\Python\ScrapeHub\worker_logs.txt"

print(f"Checking job: {job_id}")

try:
    job = Job.objects.get(job_id=job_id)
    print(f"Status: {job.status}")
    print(f"Progress: {job.progress_percentage}%")
    print(f"Items Processed: {job.processed_items}/{job.total_items}")
    print(f"Created At: {job.created_at}")
    print(f"Updated At: {job.updated_at}")
except Job.DoesNotExist:
    print("Job not found!")
except Exception as e:
    print(f"Error checking job: {e}")

print("\n--- Recent Worker Logs ---")
try:
    if os.path.exists(log_path):
        # Try utf-16le first as hinted by error, fallback to utf-8 then latin-1
        try:
            with open(log_path, "r", encoding="utf-16le") as f:
                lines = f.readlines()
        except UnicodeError:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeError:
                with open(log_path, "r", encoding="latin-1") as f:
                    lines = f.readlines()
        
        for line in lines[-20:]:
            print(line.strip())
    else:
        print("worker_logs.txt not found.")
except Exception as e:
    print(f"Error reading logs: {e}")
