from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import Job, JobEvent


def jobs_list(request):
    """Render the jobs list page"""
    status_filter = request.GET.get('status', 'all')
    
    jobs = Job.objects.all()
    if status_filter != 'all':
        jobs = jobs.filter(status=status_filter)
    
    # Get counts for filters
    total_count = Job.objects.count()
    running_count = Job.objects.filter(status='running').count()
    paused_count = Job.objects.filter(status__in=['paused', 'auto_paused']).count()
    completed_count = Job.objects.filter(status='completed').count()
    failed_count = Job.objects.filter(status='failed').count()
    
    context = {
        'jobs': jobs[:100],  # Limit to 100 most recent
        'status_filter': status_filter,
        'total_count': total_count,
        'running_count': running_count,
        'paused_count': paused_count,
        'completed_count': completed_count,
        'failed_count': failed_count,
    }
    
    return render(request, 'jobs/jobs_list.html', context)


def job_detail(request, job_id):
    """Render job detail page"""
    job = get_object_or_404(Job, job_id=job_id)
    events = job.events.all().order_by('-created_at')[:50]  # Limit to 50 most recent events
    
    context = {
        'job': job,
        'events': events,
    }
    
    return render(request, 'jobs/job_detail.html', context)


def job_status_api(request, job_id):
    """API endpoint for real-time job status updates"""
    job = get_object_or_404(Job, job_id=job_id)
    
    return JsonResponse({
        'job_id': job.job_id,
        'status': job.status,
        'progress': job.progress_percentage,
        'processed_items': job.processed_items,
        'total_items': job.total_items,
        'updated_at': job.updated_at.isoformat(),
        'results_data': job.results_data or [],  # Include results for live display
    })


@require_http_methods(["POST"])
def pause_job(request, job_id):
    """API endpoint to pause a running job"""
    job = get_object_or_404(Job, job_id=job_id)
    
    if job.status == 'running':
        job.status = 'paused'
        job.save()
        
        JobEvent.objects.create(
            job=job,
            event_type='paused',
            message='Job manually paused by user'
        )
        
        return JsonResponse({'success': True, 'status': 'paused'})
    
    return JsonResponse({'success': False, 'error': 'Job is not running'}, status=400)


@require_http_methods(["POST"])
def resume_job(request, job_id):
    """API endpoint to resume a paused job"""
    job = get_object_or_404(Job, job_id=job_id)
    
    if job.status in ['paused', 'auto_paused']:
        job.status = 'running'
        job.auto_pause_reason = None
        job.retry_count = 0
        job.save()
        
        if job.input_data and 'urls' in job.input_data:
            # Re-trigger the Celery task from the last processed item
            from scrapers.ads_txt_checker.tasks import process_ads_txt_job
            current_index = job.processed_items
            process_ads_txt_job.delay(str(job.job_id), job.input_data['urls'], start_index=current_index)
            
            message = f'Job manually resumed by user (Worker restarted at item {current_index})'
        else:
            # Legacy behavior for jobs without saved input_data
            message = 'Job manually resumed by user'
            
        JobEvent.objects.create(
            job=job,
            event_type='resumed',
            message=message
        )
        
        return JsonResponse({'success': True, 'status': 'running'})
    
    return JsonResponse({'success': False, 'error': 'Job is not paused'}, status=400)


@require_http_methods(["POST"])
def stop_job(request, job_id):
    """API endpoint to stop a job"""
    job = get_object_or_404(Job, job_id=job_id)
    
    if job.status in ['running', 'paused', 'auto_paused']:
        job.status = 'failed'
        job.error_message = 'Job manually stopped by user'
        job.save()
        
        JobEvent.objects.create(
            job=job,
            event_type='failed',
            message='Job manually stopped by user'
        )
        
        return JsonResponse({'success': True, 'status': 'failed'})
    
    return JsonResponse({'success': False, 'error': 'Job cannot be stopped'}, status=400)
