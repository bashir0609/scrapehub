from django.core.management.base import BaseCommand
from scrapers.jobs.models import Job, JobResult
import time

class Command(BaseCommand):
    help = 'Migrate results from Job.results_data to JobResult model'

    def handle(self, *args, **options):
        jobs = Job.objects.filter(results_data__isnull=False)
        total_jobs = jobs.count()
        
        self.stdout.write(f"Found {total_jobs} jobs with legacy data")
        
        for job in jobs:
            self.stdout.write(f"Migrating Job {job.job_id}...")
            results_data = job.results_data
            
            if not results_data:
                continue
                
            # Check if already migrated (simple check: if JobResult count > 0)
            if job.results.exists():
                self.stdout.write(f"Skipping Job {job.job_id}: Already has JobResult entries")
                continue
            
            batch = []
            count = 0
            
            for item in results_data:
                result = JobResult(
                    job=job,
                    original_url=item.get('original_url', ''),
                    homepage_url=item.get('homepage_url'),
                    homepage_detection=item.get('homepage_detection'),
                    ads_txt_result=item.get('ads_txt'),
                    app_ads_txt_result=item.get('app_ads_txt'),
                    error=item.get('error')
                )
                batch.append(result)
                count += 1
                
                if len(batch) >= 1000:
                    JobResult.objects.bulk_create(batch)
                    batch = []
                    self.stdout.write(f"  Saved {count} items...")
            
            if batch:
                JobResult.objects.bulk_create(batch)
            
            self.stdout.write(self.style.SUCCESS(f"Finished Job {job.job_id}: Migrated {count} results"))
            
            # Optional: Clear legacy data to save space? 
            # Better to keep it for now as backup until verified.
            # job.results_data = None
            # job.save()
            
        self.stdout.write(self.style.SUCCESS("Migration Complete"))
