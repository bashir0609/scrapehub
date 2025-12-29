import requests
import json
import time
from bs4 import BeautifulSoup
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from urllib.parse import urlparse, urlunparse

def index(request):
    """Render the ads.txt checker interface"""
    return render(request, 'scrapers/ads_txt_checker_enhanced.html', {
        'page_title': 'Ads.txt Checker Pro',
        'page_description': 'Enterprise-grade bulk ads.txt and app-ads.txt validation'
    })

def detect_homepage_url(url_input):
    """
    Detect the actual homepage URL by following redirects and handling SSL/www variations.
    Returns the final homepage URL after all redirects.
    """
    # Clean the input URL - remove whitespace and quotes
    url = url_input.strip().strip('"\'')
    if not url:
        return None, 'Empty URL'
    
    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Try to detect homepage by following redirects
    try:
        response = requests.get(
            url, 
            timeout=10, 
            allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; ScrapeHub/1.0)'},
            verify=False  # Handle SSL issues
        )
        
        # Get the final URL after all redirects
        final_url = response.url
        
        # Parse to get the base domain
        parsed = urlparse(final_url)
        homepage_url = f"{parsed.scheme}://{parsed.netloc}/"
        
        return homepage_url, 'OK'
        
    except requests.exceptions.SSLError:
        # If HTTPS fails due to SSL, try HTTP
        try:
            http_url = url.replace('https://', 'http://')
            response = requests.get(
                http_url,
                timeout=10,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; ScrapeHub/1.0)'}
            )
            parsed = urlparse(response.url)
            homepage_url = f"{parsed.scheme}://{parsed.netloc}/"
            return homepage_url, 'OK (HTTP fallback)'
        except:
            return None, 'SSL Error'
    except requests.exceptions.Timeout:
        return None, 'Timeout'
    except requests.exceptions.ConnectionError:
        return None, 'Connection Error'
    except Exception as e:
        return None, f'Error: {str(e)}'

def check_file(url):
    """Helper to check a specific URL for ads.txt content"""
    result = {
        'url': url,
        'status_code': None,
        'result_text': 'Error',
        'content': '',
        'has_html': 'No',
        'time_ms': 0
    }
    
    start_time = time.time()
    try:
        response = requests.get(
            url, 
            timeout=10, 
            headers={'User-Agent': 'Mozilla/5.0 (compatible; ScrapeHub/1.0)'},
            verify=False  # Handle SSL issues
        )
        result['time_ms'] = int((time.time() - start_time) * 1000)
        result['status_code'] = response.status_code
        
        if response.status_code == 200:
            result['result_text'] = 'OK'
            result['content'] = response.text[:500] + '...' if len(response.text) > 500 else response.text
            
            # Check for HTML tags
            if '<html' in response.text.lower() or '<body' in response.text.lower() or '<div' in response.text.lower():
                result['has_html'] = 'Yes'
            else:
                try:
                    if bool(BeautifulSoup(response.text, "html.parser").find()):
                        result['has_html'] = 'Yes'
                except:
                    pass
        else:
            result['result_text'] = f'HTTP {response.status_code}'
            
    except requests.exceptions.Timeout:
        result['time_ms'] = int((time.time() - start_time) * 1000)
        result['result_text'] = 'Timeout'
    except requests.exceptions.ConnectionError:
        result['time_ms'] = int((time.time() - start_time) * 1000)
        result['result_text'] = 'Connection Error'
    except Exception as e:
        result['time_ms'] = int((time.time() - start_time) * 1000)
        result['result_text'] = str(e)
        
    return result

@csrf_exempt
@require_http_methods(["POST"])
def check_ads_txt(request):
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            urls = data.get('urls', [])
            if isinstance(urls, str):
                urls = [u.strip() for u in urls.split('\n') if u.strip()]
        else:
            urls = request.POST.getlist('urls[]')
             
        results = []
        
        for url_input in urls:
            # Step 1-4: Clean, validate, and detect homepage URL
            homepage_url, detection_status = detect_homepage_url(url_input)
            
            if not homepage_url:
                results.append({
                    'original_url': url_input,
                    'error': f'Homepage detection failed: {detection_status}'
                })
                continue
            
            # Step 5-6: Check ads.txt and app-ads.txt files
            ads_url = homepage_url + 'ads.txt'
            app_ads_url = homepage_url + 'app-ads.txt'
            
            ads_result = check_file(ads_url)
            app_ads_result = check_file(app_ads_url)
            
            # Step 7: Prepare result
            results.append({
                'original_url': url_input,
                'homepage_url': homepage_url,
                'homepage_detection': detection_status,
                'ads_txt': ads_result,
                'app_ads_txt': app_ads_result
            })
            
        return JsonResponse({'success': True, 'results': results})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def submit_job(request):
    """Submit a new ads.txt checking job to Celery"""
    try:
        from scrapers.jobs.models import Job, JobEvent
        from .tasks import process_ads_txt_job
        import uuid
        
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            urls = data.get('urls', [])
            if isinstance(urls, str):
                urls = [u.strip() for u in urls.split('\n') if u.strip()]
        else:
            urls = request.POST.getlist('urls[]')
        
        if not urls:
            return JsonResponse({'success': False, 'error': 'No URLs provided'}, status=400)
        
        # Create job record
        job = Job.objects.create(
            scraper_type='ads_txt_checker',
            status='running',
            total_items=len(urls),
            processed_items=0,
            input_data={'urls': urls}  # Save inputs for resumption
        )
        
        # Submit to Django-Q2 background task queue
        from django_q.tasks import async_task
        task_id = async_task(process_ads_txt_job, str(job.job_id), urls)
        
        return JsonResponse({
            'success': True,
            'job_id': str(job.job_id),
            'message': f'Job submitted with {len(urls)} URLs'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
