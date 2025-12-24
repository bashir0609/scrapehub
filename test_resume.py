import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scrapehub.settings')
django.setup()

from scrapers.jobs.models import Job, JobEvent

# Get the job
job_id = '65f4482a-e802-44ed-8c05-10355140443e'
job = Job.objects.get(job_id=job_id)

print(f"Current status: {job.status}")
print(f"Processed items: {job.processed_items}/{job.total_items}")
print(f"Has input_data: {job.input_data is not None}")

if job.input_data:
    print(f"URLs in input_data: {len(job.input_data.get('urls', []))}")

# Pause the job
if job.status == 'running':
    job.status = 'paused'
    job.save()
    JobEvent.objects.create(
        job=job,
        event_type='paused',
        message='Job paused by test script'
    )
    print(f"\n✓ Job paused")

# Resume the job
if job.status == 'paused':
    job.status = 'running'
    job.save()
    
    if job.input_data and 'urls' in job.input_data:
        from scrapers.ads_txt_checker.tasks import process_ads_txt_job
        current_index = job.processed_items
        task = process_ads_txt_job.delay(str(job.job_id), job.input_data['urls'], start_index=current_index)
        
        JobEvent.objects.create(
            job=job,
            event_type='resumed',
            message=f'Job resumed by test script (Worker restarted at item {current_index})'
        )
        print(f"✓ Job resumed")
        print(f"✓ Celery task triggered: {task.id}")
        print(f"✓ Resuming from item: {current_index}")
    else:
        print("✗ No input_data found, cannot resume")
