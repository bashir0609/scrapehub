from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Job, JobEvent, JobResult
import json
import csv


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
    
    # Use cached statistics for performance
    # If statistics are stale (> 5 minutes old) or never calculated, recalculate
    from django.utils import timezone
    from datetime import timedelta
    
    should_recalculate = (
        job.stats_last_updated is None or 
        (timezone.now() - job.stats_last_updated) > timedelta(minutes=5)
    )
    
    if should_recalculate and job.status in ['completed', 'failed']:
        # Only recalculate for completed/failed jobs if stats are stale
        job.update_statistics()
        job.refresh_from_db()
    
    # Use cached statistics (much faster than counting)
    ads_success = job.stats_ads_success
    ads_error = job.stats_ads_error
    app_success = job.stats_app_success
    app_error = job.stats_app_error

    return JsonResponse({
        'job_id': job.job_id,
        'status': job.status,
        'progress': job.progress_percentage,
        'processed_items': job.processed_items,
        'total_items': job.total_items,
        'updated_at': job.updated_at.isoformat(),
        'stats': {
            'ads_success': ads_success,
            'ads_error': ads_error,
            'app_success': app_success,
            'app_error': app_error
        }
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
    """API endpoint to resume a paused, failed, or stopped job"""
    job = get_object_or_404(Job, job_id=job_id)
    
    if job.status in ['paused', 'auto_paused', 'failed', 'stopped']:
        # If job was failed/stopped, we reset it to running
        # The worker will pick up from processed_items
        job.status = 'running'
        job.auto_pause_reason = None
        job.retry_count = 0
        job.error_message = None # Clear error message
        job.save()
        
        if job.input_data and 'urls' in job.input_data:
            # Re-trigger the Django-Q2 background task from the last processed item
            from scrapers.ads_txt_checker.tasks import process_ads_txt_job
            from django_q.tasks import async_task
            current_index = job.processed_items
            async_task(process_ads_txt_job, str(job.job_id), job.input_data['urls'], start_index=current_index)
            
            message = f'Job manually resumed by user from status "{job.status}" (Worker restarted at item {current_index})'
        else:
            # Legacy behavior for jobs without saved input_data
            message = 'Job manually resumed by user'
            
        JobEvent.objects.create(
            job=job,
            event_type='resumed',
            message=message
        )
        
        return JsonResponse({'success': True, 'status': 'running'})
    
    return JsonResponse({'success': False, 'error': f'Cannot resume job in status "{job.status}"'}, status=400)


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


def download_job_results(request, job_id):
    """
    Download job results as CSV or JSON.
    Uses StreamingHttpResponse to handle large datasets efficiently.
    Streams directly from the database using iterator() on JobResult query.
    """
    job = get_object_or_404(Job, job_id=job_id)
    fmt = request.GET.get('format', 'json')
    
    # Queryset for results
    results_qs = job.results.all().iterator(chunk_size=1000)
    
    if fmt == 'csv':
        response = HttpResponse(
            content_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="job_{job.job_id}_results.csv"'},
        )
        
        writer = csv.writer(response)
        # Write header with all detailed fields
        writer.writerow([
            'Original URL',
            'Homepage URL',
            'Homepage Detection',
            'Ads.txt URL',
            'Ads.txt Status Code',
            'Ads.txt Has HTML',
            'Ads.txt Response Time (ms)',
            'Ads.txt Content',
            'App-ads.txt URL',
            'App-ads.txt Status Code',
            'App-ads.txt Has HTML',
            'App-ads.txt Response Time (ms)',
            'App-ads.txt Content',
            'Error'
        ])
        
        # Write rows with all detailed fields
        for r in results_qs:
            writer.writerow([
                r.original_url or '',
                r.homepage_url or '',
                r.homepage_detection or '',
                r.ads_txt_result.get('url', '') if r.ads_txt_result else '',
                r.ads_txt_result.get('status_code', '') if r.ads_txt_result else '',
                r.ads_txt_result.get('has_html', '') if r.ads_txt_result else '',
                r.ads_txt_result.get('time_ms', '') if r.ads_txt_result else '',
                r.ads_txt_result.get('content', '') if r.ads_txt_result else '',
                r.app_ads_txt_result.get('url', '') if r.app_ads_txt_result else '',
                r.app_ads_txt_result.get('status_code', '') if r.app_ads_txt_result else '',
                r.app_ads_txt_result.get('has_html', '') if r.app_ads_txt_result else '',
                r.app_ads_txt_result.get('time_ms', '') if r.app_ads_txt_result else '',
                r.app_ads_txt_result.get('content', '') if r.app_ads_txt_result else '',
                r.error or ''
            ])
            
        return response
        
    else:
        # For JSON streaming, we need to build a generator that yields parts of the JSON array
        def json_stream_generator():
            yield '['
            first = True
            for r in results_qs:
                if not first:
                    yield ','
                else:
                    first = False
                
                data = {
                    'original_url': r.original_url,
                    'homepage_url': r.homepage_url,
                    'homepage_detection': r.homepage_detection,
                    'ads_txt': r.ads_txt_result,
                    'app_ads_txt': r.app_ads_txt_result,
                    'error': r.error
                }
                yield json.dumps(data)
            yield ']'

        response = StreamingHttpResponse(
            json_stream_generator(),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="job_{job.job_id}_results.json"'
        return response


def job_results_api(request, job_id):
    """
    API endpoint for DataTables server-side processing.
    Handles pagination, searching, and sorting using the JobResult model directly.
    """
    job = get_object_or_404(Job, job_id=job_id)
    
    # Base queryset
    results = job.results.all()
    
    # Parameters from DataTables
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 10))
    search_value = request.GET.get('search[value]', '').strip()
    
    # Text Search (Filtering)
    if search_value:
        results = results.filter(
            Q(original_url__icontains=search_value) |
            Q(homepage_url__icontains=search_value) |
            Q(error__icontains=search_value)
        )
    
    # Sorting
    order_column_idx = int(request.GET.get('order[0][column]', 0))
    order_dir = request.GET.get('order[0][dir]', 'asc')
    
    # Map column index to field names
    # 0: expand button, 1: Original URL, 2: Homepage, 3: Ads.txt, 4: App-ads.txt
    column_map = {
        1: 'original_url',
        2: 'homepage_url',
        # Complex JSON fields or computed fields can't be easily sorted by DB
        # We'll stick to basic fields for efficient DB sorting, 
        # or defaults to insertion order (id)
    }
    
    order_field = column_map.get(order_column_idx)
    if order_field:
        if order_dir == 'desc':
            order_field = f'-{order_field}'
        results = results.order_by(order_field)
    else:
        # Default sort by newest first (descending ID)
        results = results.order_by('-id')

    # Pagination
    paginator = Paginator(results, length)
    # Calculate page number (1-based) from start offset
    page_number = (start // length) + 1
    
    try:
        page_obj = paginator.page(page_number)
        data_objects = page_obj.object_list
    except:
        data_objects = []
    
    # Serialize data for DataTables
    data = []
    for r in data_objects:
        data.append({
            'original_url': r.original_url,
            'homepage_url': r.homepage_url,
            'homepage_detection': r.homepage_detection,
            'ads_txt': r.ads_txt_result,
            'app_ads_txt': r.app_ads_txt_result,
            'error': r.error
        })
    
    return JsonResponse({
        "draw": draw,
        "recordsTotal": job.processed_items, # Approx total
        "recordsFiltered": paginator.count,   # Actual filtered count
        "data": data
    })

