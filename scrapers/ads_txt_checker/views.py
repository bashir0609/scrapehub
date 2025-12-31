import requests
import urllib3
import json
import time
from functools import wraps
from bs4 import BeautifulSoup
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from urllib.parse import urlparse, urlunparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Suppress InsecureRequestWarning since we intentionally use verify=False for scraping
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MockResponse:
    """Mock response object for Selenium fallback"""
    def __init__(self, content, status_code=200, url=None):
        self.text = content
        self.status_code = status_code
        self.url = url

def get_selenium_content(url):
    """
    Fetch content using headless Chrome via Selenium.
    Used as fallback for 403/401 errors.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    try:
        # Use system installed chromium-driver in Docker
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.set_page_load_timeout(30)
        driver.get(url)
        
        # Wait a bit for JS to execute (simple wait)
        time.sleep(2)
        
        content = driver.page_source
        current_url = driver.current_url
        
        return MockResponse(content, 200, current_url)
        
    except Exception as e:
        print(f"Selenium error for {url}: {str(e)}")
        # If selenium fails, return a 500 equivalent
        return MockResponse(str(e), 500, url)
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


def retry_with_backoff(max_retries=3, initial_delay=1, backoff_factor=2, exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
    """
    Retry decorator with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay on each retry
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        print(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        print(f"All {max_retries + 1} attempts failed for {func.__name__}")
            
            # If all retries failed, raise the last exception
            raise last_exception
        return wrapper
    return decorator

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

@retry_with_backoff(max_retries=1, initial_delay=1)
def _fetch_homepage(url):
    """Helper function to fetch homepage with retries and browser fallback"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        response = requests.get(
            url, 
            timeout=10,
            allow_redirects=True,
            headers=headers,
            verify=False
        )
        
        # Check for blocking status codes
        if response.status_code in [403, 401, 429, 503]:
            print(f"Got {response.status_code} for {url}, trying Selenium fallback...")
            return get_selenium_content(url)
            
        return response
        
    except (requests.exceptions.RequestException, Exception) as e:
        # If requests fails completely (e.g. strict SSL handshake issues), try selenium
        print(f"Request failed for {url}: {str(e)}. Trying Selenium fallback...")
        return get_selenium_content(url)

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
        response = _fetch_homepage(url)
        
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
            response = _fetch_homepage(http_url)
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


@retry_with_backoff(max_retries=1, initial_delay=0.5)
def _fetch_file(url):
    """Helper function to fetch file with retries and browser fallback"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/plain,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Cache-Control': 'no-cache',
    }

    try:
        response = requests.get(
            url, 
            timeout=10,
            headers=headers,
            verify=False
        )

        # Check for blocking status codes or soft 403s
        if response.status_code in [403, 401, 429, 503]:
            print(f"Got {response.status_code} for {url}, trying Selenium fallback...")
            return get_selenium_content(url)

        return response
    
    except (requests.exceptions.RequestException, Exception) as e:
        print(f"Request failed for {url}: {str(e)}. Trying Selenium fallback...")
        return get_selenium_content(url)

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
        response = _fetch_file(url)
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
