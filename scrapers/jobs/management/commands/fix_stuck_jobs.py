from django.core.management.base import BaseCommand
from django.utils import timezone
from scrapers.jobs.models import Job, JobEvent


class Command(BaseCommand):
    help = 'Fix jobs stuck at 100% in running status'

    def handle(self, *args, **options):
        # Find jobs that are running but have processed all items
        stuck_jobs = Job.objects.filter(
            status='running',
            processed_items__gte=1
        )
        
        count = 0
        for job in stuck_jobs:
            # Check if job has processed all items
            if job.total_items > 0 and job.processed_items >= job.total_items:
                self.stdout.write(f'Fixing job {job.job_id}: {job.processed_items}/{job.total_items}')
                
                job.status = 'completed'
                job.completed_at = timezone.now()
                job.save()
                
                JobEvent.objects.create(
                    job=job,
                    event_type='completed',
                    message=f'Manually completed (was stuck at 100%)'
                )
                count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Fixed {count} stuck jobs'))
