from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import time
import requests
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


def normalize_url(url):
    """Normalize URL by removing fragments and cleaning up"""
    if not url:
        return None
    
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Remove fragment
    if '#' in url:
        url = url.split('#')[0]
    
    # Remove trailing slashes and clean up
    url = url.rstrip('/')
    
    return url


# Placeholder view for e-commerce scraper page
def ecommerce_scraper(request):
    return render(request, 'scrapers/ecommerce_scraper.html', {
        'page_title': 'E-commerce Scraper',
    })


@csrf_exempt
@require_http_methods(["GET"])
def ecommerce_proxy_page(request):
    """
    Proxy endpoint to fetch page HTML for visual selector picker.
    This bypasses CORS restrictions by fetching the page server-side.
    Uses Playwright for JavaScript rendering if needed.
    Query params:
    - url: URL to fetch
    - use_js: Optional, set to 'true' to force JavaScript rendering
    """
    try:
        url = request.GET.get('url')
        if not url:
            return JsonResponse({'error': 'URL parameter is required'}, status=400)
        
        # Normalize URL
        url = normalize_url(url)
        if not url:
            return JsonResponse({'error': 'Invalid URL format'}, status=400)
        
        # For visual selector picker, always use JavaScript rendering to get fully rendered page
        # This ensures we see the actual content that users will interact with
        html_content = None
        js_rendering_failed = False
        
        # Always try JavaScript rendering first for visual picker
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                page = context.new_page()
                
                # Navigate to page with longer timeout
                try:
                    page.goto(url, wait_until='networkidle', timeout=60000)
                except Exception:
                    # If networkidle fails, try domcontentloaded
                    page.goto(url, wait_until='domcontentloaded', timeout=60000)
                
                # Wait for dynamic content to load
                page.wait_for_timeout(3000)
                
                # Try to wait for common content indicators
                try:
                    page.wait_for_selector('body', timeout=5000)
                except:
                    pass
                
                # Get rendered HTML
                html_content = page.content()
                
                browser.close()
                    
        except ImportError:
            # Playwright not installed, try Selenium
            js_rendering_failed = True
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                
                chrome_options = Options()
                chrome_options.add_argument('--headless')
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                
                driver = webdriver.Chrome(options=chrome_options)
                try:
                    driver.get(url)
                    # Wait for page to load
                    WebDriverWait(driver, 30).until(EC.presence_of_element_located(("tag_name", "body")))
                    time.sleep(3)  # Additional wait for dynamic content
                    html_content = driver.page_source
                    js_rendering_failed = False
                finally:
                    driver.quit()
                    
            except Exception as selenium_error:
                js_rendering_failed = True
                if settings.DEBUG:
                    print(f"Selenium rendering failed: {selenium_error}")
        except Exception as js_error:
            js_rendering_failed = True
            if settings.DEBUG:
                print(f"Playwright rendering failed: {js_error}")
        
        # Fall back to simple HTTP request if JS rendering failed
        if js_rendering_failed or not html_content:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
                
                response = requests.get(url, headers=headers, timeout=30, verify=False, allow_redirects=True)
                response.raise_for_status()
                html_content = response.text
            except Exception as http_error:
                if settings.DEBUG:
                    print(f"HTTP fallback failed: {http_error}")
                pass
        
        # If we still don't have content, return error
        if not html_content:
            return HttpResponse(
                '<html><body style="font-family: Arial; padding: 40px; text-align: center;"><h2>Failed to Load Page</h2><p>Could not fetch or render the page content.</p><p>This might be a JavaScript-heavy site that requires browser rendering. Try opening the URL in a new tab and use browser DevTools to inspect elements manually.</p></body></html>',
                status=500,
                content_type='text/html'
            )
        
        # Check if we got actual HTML content
        if len(html_content.strip()) < 100:
            return HttpResponse(
                '<html><body style="font-family: Arial; padding: 40px; text-align: center;"><h2>Empty Response</h2><p>The website returned empty or minimal content.</p><p>This might be a JavaScript-heavy site. Try opening it in a new tab and use browser DevTools.</p></body></html>',
                status=200,
                content_type='text/html'
            )
        
        # Modify relative URLs to absolute URLs for resources
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Replace relative URLs with absolute URLs
        # Fix relative links (href)
        def make_absolute_href(match):
            path = match.group(1)
            if path.startswith('//'):
                return f'href="{path}"'
            elif path.startswith('/'):
                return f'href="{base_url}{path}"'
            elif not path.startswith('http'):
                return f'href="{urljoin(base_url, path)}"'
            return match.group(0)
        
        # Fix relative sources (src)
        def make_absolute_src(match):
            path = match.group(1)
            if path.startswith('//'):
                return f'src="{path}"'
            elif path.startswith('/'):
                return f'src="{base_url}{path}"'
            elif not path.startswith('http'):
                return f'src="{urljoin(base_url, path)}"'
            return match.group(0)
        
        # Fix data-src, data-lazy-src, etc.
        def make_absolute_data_src(match):
            attr = match.group(1)
            path = match.group(2)
            if path.startswith('//'):
                return f'{attr}="{path}"'
            elif path.startswith('/'):
                return f'{attr}="{base_url}{path}"'
            elif not path.startswith('http'):
                return f'{attr}="{urljoin(base_url, path)}"'
            return match.group(0)
        
        # Apply replacements
        html_content = re.sub(r'href="([^"]+)"', make_absolute_href, html_content)
        html_content = re.sub(r'src="([^"]+)"', make_absolute_src, html_content)
        html_content = re.sub(r'(data-src|data-lazy-src|data-original)="([^"]+)"', make_absolute_data_src, html_content)
        html_content = re.sub(r'url\(([^)]+)\)', lambda m: f'url({urljoin(base_url, m.group(1)) if not m.group(1).startswith("http") else m.group(1)})', html_content)
        
        # Remove any X-Frame-Options or Content-Security-Policy that might block iframe embedding
        html_content = re.sub(r'<meta[^>]*http-equiv=["\']X-Frame-Options["\'][^>]*>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<meta[^>]*http-equiv=["\']Content-Security-Policy["\'][^>]*>', '', html_content, flags=re.IGNORECASE)
        
        # Add a meta tag to allow same-origin access
        if '<head>' in html_content:
            html_content = html_content.replace('<head>', '<head><meta http-equiv="X-Frame-Options" content="SAMEORIGIN">')
        elif '<html>' in html_content:
            html_content = html_content.replace('<html>', '<html><head><meta http-equiv="X-Frame-Options" content="SAMEORIGIN"></head>')
        
        # Return HTML content with proper headers
        response = HttpResponse(html_content, content_type='text/html; charset=utf-8')
        # Add headers to allow iframe embedding
        response['X-Frame-Options'] = 'SAMEORIGIN'
        response['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
        
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': f'Failed to fetch page: {str(e)}'}, status=500)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ecommerce_test_selectors(request):
    """
    Test CSS selectors on a URL to preview extracted data.
    Accepts JSON with:
    - url: Product URL to test
    - selectors: Dict of field_name -> CSS selector
    """
    try:
        body = json.loads(request.body)
        
        url = body.get('url')
        selectors = body.get('selectors', {})
        
        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)
        
        # Normalize URL
        url = normalize_url(url)
        if not url:
            return JsonResponse({'error': 'Invalid URL format'}, status=400)
        
        # Scrape the page
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30, verify=False)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Test each selector
            results = {}
            for field_name, selector in selectors.items():
                if not selector:
                    continue
                
                try:
                    element = soup.select_one(selector)
                    if element:
                        # Extract text or attribute
                        if field_name == 'image':
                            value = element.get('src') or element.get('data-src') or element.get('href', '')
                        else:
                            value = element.get_text(strip=True)
                        results[field_name] = {
                            'found': True,
                            'value': value[:200],  # Limit length
                            'selector': selector
                        }
                    else:
                        results[field_name] = {
                            'found': False,
                            'value': None,
                            'selector': selector,
                            'error': 'Element not found'
                        }
                except Exception as e:
                    results[field_name] = {
                        'found': False,
                        'value': None,
                        'selector': selector,
                        'error': str(e)
                    }
            
            return JsonResponse({
                'success': True,
                'url': url,
                'results': results
            })
            
        except requests.exceptions.RequestException as e:
            return JsonResponse({
                'error': f'Failed to fetch URL: {str(e)}'
            }, status=500)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)
