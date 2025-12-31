from django.core.management.base import BaseCommand
from scrapers.jobs.models import Job, JobResult
from django.db.models import Q
import uuid

class Command(BaseCommand):
    help = 'Create a new job containing only failed or unprocessed URLs from a source job'

    def add_arguments(self, parser):
        parser.add_argument('source_job_id', type=str, help='The Job ID to retry from')
        parser.add_argument('--dry-run', action='store_true', help='Show counts without creating new job')

    def handle(self, *args, **options):
        job_id = options['source_job_id']
        dry_run = options['dry_run']

        try:
            # Flexible lookup (handle full UUID or short ID)
            if len(job_id) == 8:
                source_job = Job.objects.filter(job_id__startswith=job_id).first()
            else:
                source_job = Job.objects.get(job_id=job_id)
            
            if not source_job:
                self.stdout.write(self.style.ERROR(f'Job {job_id} not found'))
                return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error finding job: {e}'))
            return

        self.stdout.write(f"Analyzing Job: {source_job.job_id}")

        # 1. Get original input URLs
        input_data = source_job.input_data or {}
        input_urls = input_data.get('urls', [])
        
        if not input_urls:
            self.stdout.write(self.style.ERROR('Source job has no input URLs'))
            return

        total_input = len(input_urls)
        self.stdout.write(f"Total Input URLs: {total_input}")

        # 2. Get Successful URLs
        # Success = ads_txt (200 or 404) AND app_ads_txt (200 or 404)
        # 404 counts as success per user request (definitive check)
        success_codes = [200, 404]
        
        # We query JobResult for this job
        successful_results = JobResult.objects.filter(
            job=source_job,
            ads_txt_result__status_code__in=success_codes,
            app_ads_txt_result__status_code__in=success_codes
        ).values_list('original_url', flat=True)

        successful_urls_set = set(successful_results)
        success_count = len(successful_urls_set)
        
        self.stdout.write(self.style.SUCCESS(f"Found {success_count} successful checks (Status 200 or 404)"))

        # 3. Filter
        new_urls = [url for url in input_urls if url not in successful_urls_set]
        new_count = len(new_urls)
        
        self.stdout.write(f"URLs to Retry (Failed/Skipped/Unprocessed): {new_count}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: New job was NOT created."))
            return

        if new_count == 0:
            self.stdout.write(self.style.WARNING("No URLs to retry. All checks were successful!"))
            return

        # 4. Create New Job
        new_job_id = str(uuid.uuid4())
        new_job = Job.objects.create(
            job_id=new_job_id,
            scraper_type=source_job.scraper_type,
            status='pending',
            input_data={'urls': new_urls, 'source_job_id': str(source_job.job_id)},
            total_items=new_count
        )

        # Trigger Processing (if using signals or manual trigger)
        # Assuming existing signal or trigger logic handles it?
        # Usually jobs are submitted via views.py which triggers `async_task`.
        # We need to trigger it manually here.
        
        from scrapers.ads_txt_checker.tasks import process_ads_txt_job
        from django_q.tasks import async_task
        
        async_task(process_ads_txt_job, new_job_id, new_urls)
        
        new_job.status = 'running'
        new_job.save()

        self.stdout.write(self.style.SUCCESS(f"Created New Job: {new_job_id}"))
        self.stdout.write(f"Visit: /jobs/{new_job_id}")
