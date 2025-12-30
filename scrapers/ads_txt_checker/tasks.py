from scrapers.jobs.models import Job, JobEvent, JobResult
from scrapers.ads_txt_checker.views import detect_homepage_url, check_file
from django.utils import timezone
import time


def process_ads_txt_job(job_id, urls, start_index=0):
    """
    Celery task to process ads.txt checking job in the background.
    Updates Job model with progress and creates JobResult objects.
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
        
        # Only process the slice of URLs starting from effective_start_index
        urls_to_process = urls[effective_start_index:]
        
        for i, url_input in enumerate(urls_to_process):
            # Calculate actual index in the full list
            index = effective_start_index + i
            # Check if job should pause/stop
            job.refresh_from_db()
            
            # Check if job was stopped or failed
            if job.status in ['stopped', 'failed']:
                print(f"Job {job_id} was stopped/failed, exiting task")
                return {'success': False, 'error': f'Job was {job.status}'}
            
            # If job is paused, exit the task - it will be restarted on resume
            if job.status == 'paused' or job.status == 'auto_paused':
                print(f"Job {job_id} is paused at {index}/{len(urls)}, exiting task")
                JobEvent.objects.create(
                    job=job,
                    event_type='paused',
                    message=f'Job paused at {index}/{len(urls)} URLs (task will resume from this point)'
                )
                # Save current progress and exit - resume will restart from processed_items
                job.processed_items = index
                job.save()
                return {'success': True, 'paused': True, 'processed': index}
            
            # Process URL
            try:
                # Detect homepage
                homepage_url, detection_status = detect_homepage_url(url_input)
                
                # Check for duplicates (only for successful detection)
                if homepage_url and JobResult.objects.filter(job=job, homepage_url=homepage_url).exists():
                    # Duplicate domain found - skip adding checking logic and result
                    # But we still count it as processed
                    job.processed_items = index + 1
                    
                    # Update progress periodically even for duplicates
                    if (index + 1) % 50 == 0:
                        job.save()
                    
                    # Special check to ensure we save if we are at the end of a block
                    if (index + 1) % 10 == 0: 
                        job.save()
                        
                    continue

                result_entry = JobResult(
                    job=job,
                    original_url=url_input
                )

                if not homepage_url:
                    result_entry.error = f'Homepage detection failed: {detection_status}'
                    result_entry.save()
                    job.processed_items = index + 1
                    job.save()
                    continue
                
                # Check ads.txt and app-ads.txt
                ads_url = homepage_url + 'ads.txt'
                app_ads_url = homepage_url + 'app-ads.txt'
                
                ads_result = check_file(ads_url)
                app_ads_result = check_file(app_ads_url)
                
                result_entry.homepage_url = homepage_url
                result_entry.homepage_detection = detection_status
                result_entry.ads_txt_result = ads_result
                result_entry.app_ads_txt_result = app_ads_result
                result_entry.save()
                
                # Rate limiting: small delay to avoid overwhelming servers
                time.sleep(0.5)
                
            except Exception as url_error:
                # Log the error in results
                JobResult.objects.create(
                    job=job,
                    original_url=url_input,
                    error=str(url_error)
                )
                
                # Auto-pause on repeated errors
                job.retry_count += 1
                if job.retry_count >= 3:
                    job.status = 'auto_paused'
                    job.auto_pause_reason = f'Server error: {str(url_error)}'
                    job.processed_items = index  # Save current position
                    job.save()
                    
                    JobEvent.objects.create(
                        job=job,
                        event_type='auto_paused',
                        message=f'Auto-paused after {job.retry_count} errors at item {index + 1}/{len(urls)}: {str(url_error)}'
                    )
                    
                    # EXIT THE TASK - resume will restart from processed_items
                    print(f"Job {job_id} auto-paused at {index}/{len(urls)}, exiting task")
                    return {'success': True, 'auto_paused': True, 'processed': index}
                else:
                    # Retry with exponential backoff
                    time.sleep(2 ** job.retry_count)
            
            
            # Update progress periodically
            if (index + 1) % 50 == 0:
                job.processed_items = index + 1
                job.save()
                
                # Create progress event every 10% or every 100 items, whichever is larger
                progress_interval = max(100, len(urls) // 10)
                if (index + 1) % progress_interval == 0:
                    JobEvent.objects.create(
                        job=job,
                        event_type='progress',
                        message=f'Processed {index + 1}/{len(urls)} URLs'
                    )
            else:
                # Just update processed count occasionally to keep DB load low
                 if (index + 1) % 10 == 0:
                    job.processed_items = index + 1
                    job.save()
        
        # Ensure final count is accurate
        job.processed_items = len(urls)
        job.save()

        print(f"=== PROCESSING COMPLETE: job_id={job_id}, processed={len(urls)} ===")
        
        # Job completed
        try:
            job.refresh_from_db()  # Get latest status
            if job.status == 'running':  # Only complete if still running
                print(f"=== SETTING JOB TO COMPLETED: job_id={job_id} ===")
                job.status = 'completed'
                job.completed_at = timezone.now()
                job.save()
                
                JobEvent.objects.create(
                    job=job,
                    event_type='completed',
                    message=f'Successfully processed {len(urls)} URLs'
                )
                print(f"=== JOB COMPLETED SUCCESSFULLY: job_id={job_id} ===")
            else:
                print(f"=== JOB STATUS CHANGED TO {job.status}, NOT COMPLETING ===")
        except Exception as completion_error:
            print(f"ERROR completing job {job_id}: {str(completion_error)}")
            # import traceback
            # traceback.print_exc()
            raise
        
        return {'success': True}
        
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
            pass
        
        print(f"Task failed for job_id {job_id}: {str(e)}")
        # import traceback
        # traceback.print_exc()
        
        return {'success': False, 'error': str(e)}
