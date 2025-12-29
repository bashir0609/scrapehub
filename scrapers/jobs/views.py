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
    
    # Calculate stats (only count processed items to avoid counting stale data)
    results = job.results_data or []
    # Only count stats for actually processed items
    results_to_count = results[:job.processed_items] if results else []
    
    ads_success = 0
    ads_error = 0
    app_success = 0
    app_error = 0
    
    for r in results_to_count:
        # Check ads.txt status
        if r.get('ads_txt'):
             if r['ads_txt'].get('status_code') == 200:
                 ads_success += 1
             else:
                 ads_error += 1
        
        # Check app-ads.txt status
        if r.get('app_ads_txt'):
             if r['app_ads_txt'].get('status_code') == 200:
                 app_success += 1
             else:
                 app_error += 1

    return JsonResponse({
        'job_id': job.job_id, # Keep job_id for client-side identification
        'status': job.status,
        'progress': job.progress_percentage,
        'processed_items': job.processed_items,
        'total_items': job.total_items,
        'updated_at': job.updated_at.isoformat(), # Keep updated_at for client-side freshness check
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
    """API endpoint to resume a paused job"""
    job = get_object_or_404(Job, job_id=job_id)
    
    if job.status in ['paused', 'auto_paused']:
        job.status = 'running'
        job.auto_pause_reason = None
        job.retry_count = 0
        job.save()
        
        if job.input_data and 'urls' in job.input_data:
            # Re-trigger the Django-Q2 background task from the last processed item
            from scrapers.ads_txt_checker.tasks import process_ads_txt_job
            from django_q.tasks import async_task
            current_index = job.processed_items
            async_task(process_ads_txt_job, str(job.job_id), job.input_data['urls'], start_index=current_index)
            
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


def download_job_results(request, job_id):
    """
    Download job results as CSV or JSON.
    Uses StreamingHttpResponse for CSV to handle large datasets efficiently.
    """
    import csv
    from django.http import StreamingHttpResponse, HttpResponse
    
    job = get_object_or_404(Job, job_id=job_id)
    fmt = request.GET.get('format', 'json')
    
    if fmt == 'csv':
        response = HttpResponse(
            content_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename="job_{job.job_id}_results.csv"'},
        )
        
        # Get results data
        results = job.results_data or []
        
        # Write CSV
        writer = csv.writer(response)
        
        # Write header
        writer.writerow(['Original URL', 'Homepage URL', 'Detection Status', 'Ads.txt Status', 'App-ads.txt Status', 'Error'])
        
        # Write rows
        for r in results:
            writer.writerow([
                r.get('original_url', ''),
                r.get('homepage_url', ''),
                r.get('homepage_detection', ''),
                r.get('ads_txt', {}).get('result_text', '') if isinstance(r.get('ads_txt'), dict) else '',
                r.get('app_ads_txt', {}).get('result_text', '') if isinstance(r.get('app_ads_txt'), dict) else '',
                r.get('error', '')
            ])
            
        return response
        
    else:
        # Default to JSON
        response = HttpResponse(
            content_type='application/json',
            headers={'Content-Disposition': f'attachment; filename="job_{job.job_id}_results.json"'},
        )
        response.write(json.dumps(job.results_data or [], indent=2))
        return response


def job_results_api(request, job_id):
    """
    API endpoint for DataTables server-side processing.
    Handles pagination, searching, and sorting for job results.
    """
    job = get_object_or_404(Job, job_id=job_id)
    all_results = job.results_data or []
    
    # Only show results that have been processed (avoid showing stale data)
    results = all_results[:job.processed_items] if all_results else []
    
    # Parameters from DataTables
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 10))
    search_value = request.GET.get('search[value]', '').lower()
    
    # Filtering
    if search_value:
        filtered_results = []
        for r in results:
            # Search in all relevant string fields
            text = f"{r.get('original_url', '')} {r.get('homepage_url', '')} {r.get('error', '')}"
            if search_value in text.lower():
                filtered_results.append(r)
        results = filtered_results
    
    # Sorting (basic implementation for key columns)
    order_column_idx = int(request.GET.get('order[0][column]', 0))
    order_dir = request.GET.get('order[0][dir]', 'asc')
    
    # Map column index to key (matches table creation order)
    # 0: Original URL, 1: Homepage, 2: Ads.txt, 3: App-ads.txt
    column_keys = ['original_url', 'homepage_url', 'ads_txt', 'app_ads_txt']
    if 0 <= order_column_idx < len(column_keys):
        key = column_keys[order_column_idx]
        reverse = (order_dir == 'desc')
        
        def get_sort_value(item):
            val = item.get(key, '')
            if isinstance(val, dict): # For ads_txt/app_ads_txt result/status objects
                return val.get('result_text', '') 
            return str(val).lower()
            
        results.sort(key=get_sort_value, reverse=reverse)

    # Pagination (use processed_items as the true total, not stale data)
    total_records = job.processed_items
    filtered_records = len(results)
    
    # Slice the results
    page_data = results[start : start + length]
    
    return JsonResponse({
        "draw": draw,
        "recordsTotal": total_records,
        "recordsFiltered": filtered_records,
        "data": page_data
    })
