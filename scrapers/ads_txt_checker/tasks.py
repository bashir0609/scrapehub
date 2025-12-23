from celery import shared_task
from scrapers.jobs.models import Job, JobEvent
from scrapers.ads_txt_checker.views import detect_homepage_url, check_file
import time


@shared_task(bind=True)
def process_ads_txt_job(self, job_id, urls, start_index=0):
    """
    Celery task to process ads.txt checking job in the background.
    Updates Job model with progress and results.
    """
    print(f"=== TASK STARTED: job_id={job_id}, urls_count={len(urls)}, start_index={start_index} ===")
    try:
        # Get the job
        job = Job.objects.get(job_id=job_id)
        print(f"=== JOB FOUND: {job.job_id}, status={job.status} ===")
        
        job.status = 'running'
        job.total_items = len(urls)
        job.save()
        
        # Determine effective start index
        if start_index > 0:
            effective_start_index = start_index
            JobEvent.objects.create(
                job=job,
                event_type='resumed',
                message=f'Resuming processing from item {start_index + 1}/{len(urls)}'
            )
        else:
            effective_start_index = 0
            # Create started event only if starting from scratch
            JobEvent.objects.create(
                job=job,
                event_type='started',
                message=f'Started processing {len(urls)} URLs'
            )
        
        # Initialize results with existing data if resuming
        results = job.results_data if job.results_data else []
        
        # Only process the slice of URLs starting from effective_start_index
        urls_to_process = urls[effective_start_index:]
        
        for i, url_input in enumerate(urls_to_process):
            # Calculate actual index in the full list
            index = effective_start_index + i
            # Check if job should pause/stop
            job.refresh_from_db()
            if job.status == 'paused':
                JobEvent.objects.create(
                    job=job,
                    event_type='paused',
                    message=f'Job paused at {index}/{len(urls)} URLs'
                )
                # Wait for resume
                while job.status == 'paused':
                    time.sleep(2)
                    job.refresh_from_db()
                
                JobEvent.objects.create(
                    job=job,
                    event_type='resumed',
                    message=f'Job resumed at {index}/{len(urls)} URLs'
                )
            
            # Process URL
            try:
                # Detect homepage
                homepage_url, detection_status = detect_homepage_url(url_input)
                
                if not homepage_url:
                    results.append({
                        'original_url': url_input,
                        'error': f'Homepage detection failed: {detection_status}'
                    })
                    job.processed_items = index + 1
                    job.save()
                    continue
                
                # Check ads.txt and app-ads.txt
                ads_url = homepage_url + 'ads.txt'
                app_ads_url = homepage_url + 'app-ads.txt'
                
                ads_result = check_file(ads_url)
                app_ads_result = check_file(app_ads_url)
                
                results.append({
                    'original_url': url_input,
                    'homepage_url': homepage_url,
                    'homepage_detection': detection_status,
                    'ads_txt': ads_result,
                    'app_ads_txt': app_ads_result
                })
                
            except Exception as url_error:
                # Auto-pause on repeated errors
                job.retry_count += 1
                if job.retry_count >= 3:
                    job.status = 'auto_paused'
                    job.auto_pause_reason = f'Server error: {str(url_error)}'
                    job.save()
                    
                    JobEvent.objects.create(
                        job=job,
                        event_type='auto_paused',
                        message=f'Auto-paused after {job.retry_count} errors: {str(url_error)}'
                    )
                    
                    # Wait for manual resume
                    while job.status == 'auto_paused':
                        time.sleep(5)
                        job.refresh_from_db()
                    
                    job.retry_count = 0
                    JobEvent.objects.create(
                        job=job,
                        event_type='auto_resumed',
                        message='Job auto-resumed after server recovery'
                    )
                else:
                    # Retry with exponential backoff
                    time.sleep(2 ** job.retry_count)
                
                results.append({
                    'original_url': url_input,
                    'error': str(url_error)
                })
            
            
            # Update progress and save results periodically
            job.processed_items = index + 1
            
            # Save results every 10 items for live stats
            if (index + 1) % 10 == 0:
                job.results_data = results
                job.save()
                
                # Create progress event only every 100 items to avoid timeline clutter
                if (index + 1) % 100 == 0:
                    JobEvent.objects.create(
                        job=job,
                        event_type='progress',
                        message=f'Processed {index + 1}/{len(urls)} URLs'
                    )
            else:
                # Just update processed count
                job.save()
        
        # Job completed
        job.status = 'completed'
        job.results_data = results
        job.completed_at = time.time()
        job.save()
        
        JobEvent.objects.create(
            job=job,
            event_type='completed',
            message=f'Successfully processed {len(urls)} URLs'
        )
        
        return {'success': True, 'results': results}
        
    except Exception as e:
        # Job failed - try to update job if it exists
        try:
            if 'job' in locals():
                job.status = 'failed'
                job.error_message = str(e)
                job.save()
                
                JobEvent.objects.create(
                    job=job,
                    event_type='failed',
                    message=f'Job failed: {str(e)}'
                )
        except:
            pass  # If we can't update the job, just log the error
        
        # Always log to Celery
        print(f"Task failed for job_id {job_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {'success': False, 'error': str(e)}
