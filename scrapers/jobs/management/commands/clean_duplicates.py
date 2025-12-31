from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Min
from scrapers.jobs.models import JobResult


class Command(BaseCommand):
    help = 'Clean duplicate JobResult entries, keeping only the first occurrence of each (job, original_url) pair'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find all duplicate groups
        self.stdout.write('Finding duplicate records...')
        duplicates = JobResult.objects.values('job_id', 'original_url').annotate(
            count=Count('id'),
            min_id=Min('id')
        ).filter(count__gt=1)
        
        duplicate_count = duplicates.count()
        
        if duplicate_count == 0:
            self.stdout.write(self.style.SUCCESS('No duplicates found!'))
            return
        
        self.stdout.write(f'Found {duplicate_count} duplicate groups')
        
        # Calculate total records to delete
        total_to_delete = 0
        for dup in duplicates:
            total_to_delete += dup['count'] - 1  # Keep one, delete the rest
        
        self.stdout.write(f'Total records to delete: {total_to_delete}')
        
        if dry_run:
            # Show sample of what would be deleted
            self.stdout.write('\nSample of duplicate groups (first 10):')
            for i, dup in enumerate(duplicates[:10], 1):
                job_id_short = str(dup['job_id'])[:8]
                url_short = dup['original_url'][:50] + '...' if len(dup['original_url']) > 50 else dup['original_url']
                self.stdout.write(
                    f"  {i}. Job: {job_id_short}, URL: {url_short}, "
                    f"Count: {dup['count']}, Keeping ID: {dup['min_id']}"
                )
            self.stdout.write(self.style.WARNING('\nRun without --dry-run to execute cleanup'))
            return
        
        # Perform the cleanup
        self.stdout.write('\nStarting cleanup...')
        deleted_count = 0
        affected_job_ids = set()
        
        with transaction.atomic():
            for dup in duplicates:
                affected_job_ids.add(dup['job_id'])
                # Delete all records except the one with min_id
                records_to_delete = JobResult.objects.filter(
                    job_id=dup['job_id'],
                    original_url=dup['original_url']
                ).exclude(id=dup['min_id'])
                
                count = records_to_delete.count()
                records_to_delete.delete()
                deleted_count += count
                
                if deleted_count % 100 == 0:
                    self.stdout.write(f'  Deleted {deleted_count} records so far...')
        
        self.stdout.write(self.style.SUCCESS(f'\n✓ Successfully deleted {deleted_count} duplicate records'))
        self.stdout.write(self.style.SUCCESS(f'✓ Kept {duplicate_count} unique records (earliest occurrence of each)'))
        
        # Update statistics for affected jobs
        self.stdout.write('\nUpdating statistics for affected jobs...')
        from scrapers.jobs.models import Job
        for job_id in affected_job_ids:
            try:
                job = Job.objects.get(job_id=job_id)
                self.stdout.write(f'  Updating stats for job {str(job_id)[:8]}...')
                job.update_statistics()
            except Job.DoesNotExist:
                pass
        self.stdout.write(self.style.SUCCESS('✓ Statistics updated'))
