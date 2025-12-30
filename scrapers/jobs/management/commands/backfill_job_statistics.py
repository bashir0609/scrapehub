from django.core.management.base import BaseCommand
from scrapers.jobs.models import Job
from django.utils import timezone


class Command(BaseCommand):
    help = 'Backfill cached statistics for existing jobs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Update statistics for all jobs, even if already calculated',
        )

    def handle(self, *args, **options):
        update_all = options['all']
        
        if update_all:
            jobs = Job.objects.all()
            self.stdout.write(f'Updating statistics for all {jobs.count()} jobs...')
        else:
            # Only update jobs where statistics haven't been calculated
            jobs = Job.objects.filter(stats_last_updated__isnull=True)
            self.stdout.write(f'Updating statistics for {jobs.count()} jobs without cached stats...')
        
        updated_count = 0
        for job in jobs:
            try:
                job.update_statistics()
                updated_count += 1
                
                if updated_count % 10 == 0:
                    self.stdout.write(f'  Processed {updated_count} jobs...')
                    
            except Exception as e:
                self.stderr.write(f'  Error updating job {job.job_id}: {str(e)}')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully updated statistics for {updated_count} jobs!')
        )
