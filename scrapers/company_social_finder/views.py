import json
import requests
import csv
import time
import copy
import uuid
import re
import os
import threading
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
from lxml import etree, html
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from .models import WebScrapingRequest, WebScrapingResult, BulkWebScrapingRequest
from scrapers.ecommerce_scraper.models import Product, PriceHistory, EcommerceScrapingRequest, EcommercePlatform
from scrapers.ecommerce_scraper.scraper_helpers import (
    get_platform_from_url,
    scrape_product_generic,
    scrape_product_listing,
    is_listing_page,
    scrape_product_amazon,
    scrape_product_ebay,
    scrape_product_shopify,
    scrape_product_daraz,
    scrape_product_aliexpress,
    scrape_product_etsy,
)

try:
    import urllib3
    URLLIB3_AVAILABLE = True
except ImportError:
    URLLIB3_AVAILABLE = False


def extract_field_paths(obj, parent_key='', sep='.', max_depth=10, current_depth=0):
    """
    Extract all field paths from a nested dictionary/list structure.
    
    Args:
        obj: Object to extract paths from (dict, list, or primitive)
        parent_key: Parent key prefix (used recursively)
        sep: Separator for nested keys (default: '.')
        max_depth: Maximum depth to traverse (prevent infinite loops)
        current_depth: Current depth in recursion
    
    Returns:
        Set of field paths (e.g., {'id', 'name', 'address.city', 'address.country.label'})
    """
    field_paths = set()
    
    if current_depth >= max_depth:
        return field_paths
    
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            field_paths.add(new_key)
            
            if isinstance(v, (dict, list)):
                # Recursively extract paths from nested structures
                nested_paths = extract_field_paths(v, new_key, sep=sep, max_depth=max_depth, current_depth=current_depth + 1)
                field_paths.update(nested_paths)
    elif isinstance(obj, list) and len(obj) > 0:
        # For lists, check the first item if it's a dict
        first_item = obj[0]
        if isinstance(first_item, dict):
            nested_paths = extract_field_paths(first_item, parent_key, sep=sep, max_depth=max_depth, current_depth=current_depth + 1)
            field_paths.update(nested_paths)
        else:
            # For simple lists, just add the parent key
            if parent_key:
                field_paths.add(parent_key)
    
    return field_paths


def flatten_dict(d, parent_key='', sep='.'):
    """
    Flatten a nested dictionary using dot notation.
    
    Args:
        d: Dictionary to flatten
        parent_key: Parent key prefix (used recursively)
        sep: Separator for nested keys (default: '.')
    
    Returns:
        Flattened dictionary with dot-separated keys
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # For lists, convert to JSON string or handle each item
            if len(v) > 0 and isinstance(v[0], dict):
                # If list contains dicts, convert to JSON string
                items.append((new_key, json.dumps(v, ensure_ascii=False)))
            else:
                # For simple lists, join with semicolon or convert to JSON
                items.append((new_key, json.dumps(v, ensure_ascii=False)))
        else:
            items.append((new_key, v))
    return dict(items)


def filter_record_fields(record, fields):
    """
    Filter a record to keep only specified fields.
    Supports dot notation for nested fields (e.g., 'exhibitor.name').
    
    Args:
        record: Dictionary to filter
        fields: List of field paths (e.g., ['name', 'exhibitor.name', 'exhibitor.address.city'])
    
    Returns:
        Filtered dictionary with only specified fields
    """
    if not fields or len(fields) == 0:
        return record
    
    if not isinstance(record, dict):
        return record
    
    filtered = {}
    
    for field_path in fields:
        # Clean and split field path by dots to handle nested fields
        if isinstance(field_path, str):
            field_path = field_path.strip()
        else:
            field_path = str(field_path).strip()
            
        if not field_path:
            continue
            
        parts = field_path.split('.')
        value = record
        
        # Navigate through nested structure
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        
        # If value found, set it in filtered dict using the same structure
        if value is not None:
            # Deep copy the value to avoid reference issues
            if isinstance(value, (dict, list)):
                value = copy.deepcopy(value)
            
            current = filtered
            # Build the nested structure for all parts except the last
            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    # If the path already exists but is not a dict, replace it with a dict
                    current[part] = {}
                current = current[part]
            
            # Set the final value
            # Only overwrite if the key doesn't exist or if it's not a dict
            final_key = parts[-1]
            if final_key not in current:
                current[final_key] = value
            elif isinstance(current[final_key], dict) and isinstance(value, dict):
                # Merge dictionaries if both are dicts
                def merge_dicts(d1, d2):
                    """Recursively merge two dictionaries"""
                    result = copy.deepcopy(d1)
                    for k, v in d2.items():
                        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                            result[k] = merge_dicts(result[k], v)
                        else:
                            result[k] = copy.deepcopy(v)
                    return result
                current[final_key] = merge_dicts(current[final_key], value)
            else:
                # Overwrite if types don't match or value is not a dict
                current[final_key] = value
    
    return filtered


def normalize_url(url):
    """
    Normalize and validate a URL.
    - Removes whitespace
    - Adds http:// or https:// if missing
    - Removes trailing slashes (optional, can be configured)
    - Validates URL format
    """
    if not url:
        return None
    
    # Remove whitespace
    url = url.strip()
    
    if not url:
        return None
    
    # Remove common trailing characters that might be in CSV
        url = url.rstrip('.,;)\\]}')
    
    # If URL doesn't start with http:// or https://, add https://
    if not url.startswith(('http://', 'https://')):
        # Check if it looks like a domain
        if '.' in url and not url.startswith('/'):
            url = 'https://' + url
        else:
            return None  # Invalid URL format
    
    # Parse and reconstruct URL to normalize it
    try:
        parsed = urlparse(url)
        # Reconstruct with normalized components
        normalized = urlunparse((
            parsed.scheme or 'https',
            parsed.netloc.lower(),  # Lowercase domain
            parsed.path.rstrip('/') if parsed.path != '/' else '/',  # Remove trailing slash except root
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
        return normalized
    except Exception as e:
        if settings.DEBUG:
            print(f"URL normalization error for '{url}': {e}")
        return None


def make_request_with_retry(url, headers=None, timeout=30, max_retries=3, verify_ssl=True):
    """
    Make HTTP request with retry logic and SSL handling.
    
    Args:
        url: URL to request
        headers: Request headers
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        verify_ssl: Whether to verify SSL certificates
    
    Returns:
        Response object or None if all retries failed
    """
    if headers is None:
        headers = {}
    
    # Disable SSL warnings if verification is disabled
    if not verify_ssl and URLLIB3_AVAILABLE:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                verify=verify_ssl,
                allow_redirects=True
            )
            return response
        except requests.exceptions.SSLError as e:
            last_exception = e
            # Try again with SSL verification disabled
            if verify_ssl and attempt < max_retries - 1:
                if settings.DEBUG:
                    print(f"SSL error for {url}, retrying with SSL verification disabled...")
                verify_ssl = False
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                continue
            else:
                if settings.DEBUG:
                    print(f"SSL error for {url} after {attempt + 1} attempts: {e}")
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                if settings.DEBUG:
                    print(f"Connection error for {url}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                if settings.DEBUG:
                    print(f"Connection error for {url} after {max_retries} attempts: {e}")
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                if settings.DEBUG:
                    print(f"Timeout for {url}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                if settings.DEBUG:
                    print(f"Timeout for {url} after {max_retries} attempts: {e}")
        except requests.exceptions.RequestException as e:
            last_exception = e
            if settings.DEBUG:
                print(f"Request error for {url}: {e}")
            break  # Don't retry for other request exceptions
    
    return None


@csrf_exempt
@require_http_methods(["POST"])
def scrape_api(request):
    """
    API endpoint to scrape data from external APIs.
    Accepts JSON with:
    - url: API endpoint URL
    - method: HTTP method (default: POST)
    - data: Request payload/data
    - headers: Optional custom headers
    """
    try:
        # Parse request data
        body = json.loads(request.body)
        
        api_url = body.get('url')
        method = body.get('method', 'POST').upper()
        request_data = body.get('data', {})
        headers = body.get('headers', {})
        fields = body.get('fields')  # Optional list of fields to keep
        
        # Validate and normalize fields
        if fields is None:
            fields = []
        elif isinstance(fields, str):
            # If fields is a string, split it
            fields = [f.strip() for f in fields.split(',') if f.strip()]
        elif not isinstance(fields, list):
            fields = []
        else:
            # Ensure all fields are strings and trimmed, filter out empty strings
            fields = [f.strip() if isinstance(f, str) else str(f).strip() for f in fields if f and str(f).strip()]
        
        if settings.DEBUG:
            print(f"[scrape_api] Fields received (raw): {body.get('fields')}")
            print(f"[scrape_api] Fields after normalization: {fields}")
            print(f"[scrape_api] Fields type: {type(fields)}, length: {len(fields) if isinstance(fields, list) else 'N/A'}")
        
        # Validate required fields
        if not api_url:
            return JsonResponse({
                'error': 'URL is required'
            }, status=400)
        
        # Create scraping request record
        scraping_request = ScrapingRequest.objects.create(
            url=api_url,
            method=method,
            request_data=request_data
        )
        
        # Default headers
        default_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        default_headers.update(headers)
        
        # Make the API request
        try:
            if method == 'POST':
                response = requests.post(
                    api_url,
                    json=request_data,
                    headers=default_headers,
                    timeout=30
                )
            elif method == 'GET':
                response = requests.get(
                    api_url,
                    params=request_data,
                    headers=default_headers,
                    timeout=30
                )
            elif method == 'PUT':
                response = requests.put(
                    api_url,
                    json=request_data,
                    headers=default_headers,
                    timeout=30
                )
            elif method == 'DELETE':
                response = requests.delete(
                    api_url,
                    headers=default_headers,
                    timeout=30
                )
            else:
                scraping_request.error_message = f'Unsupported HTTP method: {method}'
                scraping_request.save()
                return JsonResponse({
                    'error': f'Unsupported HTTP method: {method}'
                }, status=400)
            
            # Try to parse JSON response
            try:
                response_data = response.json()
            except ValueError:
                response_data = {'raw_response': response.text}
            
            # Filter fields if specified
            if isinstance(fields, list) and len(fields) > 0:
                # Try to extract records from response (similar to scrape_paginated logic)
                records = []
                data_section = response_data.get('data', {})
                result_section = response_data.get('result', {})
                
                # Check for result.hits (Messe Frankfurt API structure)
                if isinstance(result_section, dict) and 'hits' in result_section:
                    hits = result_section['hits']
                    # Extract exhibitor objects from hits (Messe Frankfurt API structure)
                    records = []
                    for hit in hits:
                        if isinstance(hit, dict) and 'exhibitor' in hit:
                            # Extract exhibitor object
                            records.append(hit['exhibitor'].copy())
                        else:
                            # If no exhibitor key, use the hit itself
                            records.append(hit)
                # Check for data.records (standard structure)
                elif isinstance(data_section, dict) and 'records' in data_section:
                    records = data_section['records']
                elif isinstance(data_section, list):
                    records = data_section
                elif isinstance(response_data, list):
                    records = response_data
                
                # Filter records if found
                if records:
                    # For Messe Frankfurt API (result.hits), if we extracted exhibitor objects,
                    # strip 'exhibitor.' prefix from field paths since records are already exhibitor objects
                    normalized_fields = fields
                    if isinstance(result_section, dict) and 'hits' in result_section and records:
                        # Check if first record looks like an exhibitor object (has 'id', 'name', etc.)
                        first_record = records[0] if records else {}
                        if isinstance(first_record, dict) and 'id' in first_record and 'name' in first_record and 'exhibitor' not in first_record:
                            # Strip 'exhibitor.' prefix from field paths
                            normalized_fields = []
                            for field in fields:
                                field_str = str(field).strip()
                                if field_str.startswith('exhibitor.'):
                                    normalized_fields.append(field_str[10:])  # Remove 'exhibitor.' prefix
                                else:
                                    normalized_fields.append(field_str)
                            if settings.DEBUG and normalized_fields != fields:
                                print(f"[scrape_api] Normalized fields from {fields} to {normalized_fields}")
                    
                    if settings.DEBUG:
                        print(f"[scrape_api] Filtering {len(records)} records with fields: {normalized_fields}")
                    
                    filtered_records = [filter_record_fields(record, normalized_fields) for record in records]
                    
                    if settings.DEBUG:
                        print(f"[scrape_api] Filtered to {len(filtered_records)} records")
                        if filtered_records:
                            sample_keys = list(filtered_records[0].keys())[:10] if isinstance(filtered_records[0], dict) else []
                            print(f"[scrape_api] Sample filtered record keys: {sample_keys}")
                    
                    # Replace records in response
                    if isinstance(result_section, dict) and 'hits' in result_section:
                        # For Messe Frankfurt API, replace hits with filtered exhibitor records
                        # But keep the structure - put filtered records back as hits
                        response_data['result']['hits'] = filtered_records
                    elif isinstance(data_section, dict) and 'records' in data_section:
                        response_data['data']['records'] = filtered_records
                    elif isinstance(data_section, list):
                        response_data['data'] = filtered_records
                    elif isinstance(response_data, list):
                        response_data = filtered_records
                else:
                    # If no records found, filter the entire response
                    if settings.DEBUG:
                        print(f"[scrape_api] No records found, filtering entire response with fields: {fields}")
                    response_data = filter_record_fields(response_data, fields)
            else:
                # If no fields specified, keep original response
                if settings.DEBUG:
                    print(f"[scrape_api] No fields specified (fields={fields}), keeping original response")
            
            # Update scraping request record
            scraping_request.status_code = response.status_code
            scraping_request.response_data = response_data
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            
            # Return response
            return JsonResponse({
                'success': True,
                'status_code': response.status_code,
                'data': response_data,
                'headers': dict(response.headers),
                'request_id': scraping_request.id
            }, status=200)
            
        except requests.exceptions.Timeout:
            scraping_request.error_message = 'Request timeout'
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            return JsonResponse({
                'error': 'Request timeout'
            }, status=504)
            
        except requests.exceptions.ConnectionError:
            scraping_request.error_message = 'Connection error'
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            return JsonResponse({
                'error': 'Connection error - could not reach the server'
            }, status=503)
            
        except requests.exceptions.RequestException as e:
            scraping_request.error_message = str(e)
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            return JsonResponse({
                'error': f'Request failed: {str(e)}'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON in request body'
        }, status=400)
        
    except Exception as e:
        return JsonResponse({
            'error': f'Server error: {str(e)}'
        }, status=500)


def index(request):
    """Home page with scraping interface"""
    from django.shortcuts import render
    return render(request, 'index.html')

def web_scraper(request):
    """Company Social Finder - Find company information and social media profiles"""
    from django.shortcuts import render
    return render(request, 'scrapers/company_social_finder.html', {
        'page_title': 'Company Social Finder',
        'page_description': 'Find company information and social media profiles from websites'
    })

def social_scraper(request):
    """Placeholder view for Social Scraper"""
    from django.shortcuts import render
    return render(request, 'scrapers/social_scraper.html', {
        'page_title': 'Social Scraper',
        'page_description': 'Scrape data from social media platforms'
    })

def ecommerce_scraper(request):
    """Placeholder view for E-commerce Scraper"""
    from django.shortcuts import render
    return render(request, 'scrapers/ecommerce_scraper.html', {
        'page_title': 'E-commerce Scraper',
        'page_description': 'Scrape product data from e-commerce websites'
    })

def rapidapi_scraper(request):
    """Placeholder view for RapidAPI Scraper"""
    from django.shortcuts import render
    return render(request, 'scrapers/rapidapi_scraper.html', {
        'page_title': 'RapidAPI Scraper',
        'page_description': 'Access thousands of APIs through RapidAPI marketplace'
    })


@csrf_exempt
@require_http_methods(["POST"])
def web_scrape(request):
    """
    Web scraping endpoint.
    Accepts JSON with:
    - url: URL to scrape
    - selectors: Dict of field_name -> CSS selector/XPath
    - method: 'beautifulsoup', 'css', 'xpath', 'selenium'
    - headers: Optional custom headers
    - user_agent: Optional custom user agent
    - wait_time: Optional wait time in seconds
    - pagination: Optional pagination config
      - enabled: bool
      - selector: CSS selector or XPath for next page link
      - max_pages: Maximum number of pages to scrape
    """
    try:
        body = json.loads(request.body)
        
        url = body.get('url')
        selectors = body.get('selectors', {})
        method = body.get('method', 'beautifulsoup')
        headers = body.get('headers', {})
        user_agent = body.get('user_agent', '')
        wait_time = body.get('wait_time', 0)
        pagination = body.get('pagination', {})
        pagination_enabled = pagination.get('enabled', False)
        pagination_selector = pagination.get('selector', '')
        max_pages = pagination.get('max_pages', 10)
        
        if not url:
            return JsonResponse({'error': 'URL is required'}, status=400)
        
        # Normalize URL
        url = normalize_url(url)
        if not url:
            return JsonResponse({'error': 'Invalid URL format'}, status=400)
        
        # Note: selectors are optional - predefined fields are automatically extracted
        
        # Create scraping request record
        scraping_request = WebScrapingRequest.objects.create(
            url=url,
            selectors=selectors,
            method=method,
            headers=headers,
            user_agent=user_agent,
            wait_time=wait_time
        )
        
        # Prepare request headers
        request_headers = {
            'User-Agent': user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        request_headers.update(headers)
        
        # Wait if specified
        if wait_time > 0:
            time.sleep(wait_time)
        
        # Make the HTTP request
        try:
            # Check if JavaScript rendering is needed
            use_js_rendering = method in ['selenium', 'playwright']
            html_content = None
            
            if use_js_rendering:
                # Use Selenium or Playwright for JavaScript rendering
                try:
                    if method == 'selenium':
                        from selenium import webdriver
                        from selenium.webdriver.chrome.options import Options
                        from selenium.webdriver.chrome.service import Service
                        from selenium.webdriver.common.by import By
                        from selenium.webdriver.support.ui import WebDriverWait
                        from selenium.webdriver.support import expected_conditions as EC
                        
                        chrome_options = Options()
                        chrome_options.add_argument('--headless')
                        chrome_options.add_argument('--no-sandbox')
                        chrome_options.add_argument('--disable-dev-shm-usage')
                        chrome_options.add_argument('--disable-gpu')
                        chrome_options.add_argument(f'user-agent={user_agent or "Mozilla/5.0"}')
                        
                        # Try Chrome first, then Chromium
                        try:
                            driver = webdriver.Chrome(options=chrome_options)
                        except Exception:
                            # Fallback to Chromium if Chrome is not available
                            chrome_options.binary_location = '/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else '/usr/bin/chromium-browser'
                            driver = webdriver.Chrome(options=chrome_options)
                        try:
                            driver.get(url)
                            if wait_time > 0:
                                time.sleep(wait_time)
                            html_content = driver.page_source
                        finally:
                            driver.quit()
                    
                    elif method == 'playwright':
                        try:
                            from playwright.sync_api import sync_playwright
                            
                            with sync_playwright() as p:
                                browser = p.chromium.launch(headless=True)
                                context = browser.new_context(user_agent=user_agent or 'Mozilla/5.0')
                                page = context.new_page()
                                page.goto(url)
                                if wait_time > 0:
                                    page.wait_for_timeout(int(wait_time * 1000))
                                html_content = page.content()
                                browser.close()
                        except ImportError:
                            return JsonResponse({
                                'error': 'Playwright not installed. Run: playwright install chromium'
                            }, status=500)
                
                except ImportError as e:
                    return JsonResponse({
                        'error': f'JavaScript rendering library not available: {str(e)}. Install selenium or playwright.'
                    }, status=500)
                except Exception as e:
                    return JsonResponse({
                        'error': f'JavaScript rendering failed: {str(e)}'
                    }, status=500)
            
            # Get HTML content
            if html_content:
                response_text = html_content
                response_status = 200
                scraping_request.status_code = 200
            else:
                # Use retry logic with SSL handling
                response = make_request_with_retry(url, headers=request_headers, timeout=30, max_retries=3, verify_ssl=False)
                if response is None:
                    scraping_request.error_message = 'Failed to connect after multiple retries'
                    scraping_request.completed_at = timezone.now()
                    scraping_request.save()
                    return JsonResponse({
                        'error': 'Failed to connect to the server. Please check the URL and try again.',
                        'request_id': scraping_request.id
                    }, status=503)
                
                response_text = response.text
                response_status = response.status_code
                scraping_request.status_code = response_status
            
            if response_status != 200:
                scraping_request.error_message = f'HTTP {response_status}: {response.reason if not use_js_rendering else "Error"}'
                scraping_request.completed_at = timezone.now()
                scraping_request.save()
                return JsonResponse({
                    'error': f'HTTP {response_status}: {response.reason if not use_js_rendering else "Error"}',
                    'request_id': scraping_request.id
                }, status=response_status)
            
            # Parse HTML
            soup = BeautifulSoup(response_text, 'lxml')
            # Also create lxml tree for XPath support
            lxml_tree = html.fromstring(response_text.encode('utf-8'))
            scraping_request.response_data = {'html_length': len(response_text)}
            
            # Helper function to extract tables
            def extract_tables(soup):
                """Extract all tables from the page and return as list of dictionaries."""
                tables = soup.find_all('table')
                extracted_tables = []
                
                for table in tables:
                    table_data = []
                    headers = []
                    
                    # Try to find headers
                    header_row = table.find('thead')
                    if header_row:
                        headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                    else:
                        # Try first row as headers
                        first_row = table.find('tr')
                        if first_row:
                            headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                    
                    # Extract rows
                    tbody = table.find('tbody') or table
                    rows = tbody.find_all('tr')
                    
                    # Skip header row if no thead
                    start_idx = 1 if not header_row and first_row else 0
                    
                    for row in rows[start_idx:]:
                        cells = row.find_all(['td', 'th'])
                        if cells:
                            row_data = {}
                            for i, cell in enumerate(cells):
                                header = headers[i] if i < len(headers) else f'Column_{i+1}'
                                row_data[header] = cell.get_text(strip=True)
                            table_data.append(row_data)
                    
                    if table_data:
                        extracted_tables.append({
                            'headers': headers,
                            'rows': table_data,
                            'row_count': len(table_data)
                        })
                
                return extracted_tables
            
            # Helper function to detect if selector is XPath
            def is_xpath(selector):
                """Check if selector is XPath (starts with /, //, or contains xpath: prefix)."""
                if not selector:
                    return False
                selector = selector.strip()
                return (selector.startswith('/') or 
                        selector.startswith('//') or 
                        selector.startswith('xpath:') or
                        selector.startswith('XPath:'))
            
            # Helper function to extract elements using XPath
            def extract_with_xpath(tree, xpath_expr):
                """Extract elements using XPath."""
                try:
                    # Remove xpath: prefix if present
                    if xpath_expr.startswith('xpath:') or xpath_expr.startswith('XPath:'):
                        xpath_expr = xpath_expr.split(':', 1)[1].strip()
                    
                    elements = tree.xpath(xpath_expr)
                    return elements
                except Exception as e:
                    if settings.DEBUG:
                        print(f"XPath error: {e}")
                    return []
            
            # Helper function to get text/attributes from both BeautifulSoup and lxml elements
            def get_element_text(elem):
                """Get text content from BeautifulSoup or lxml element."""
                if hasattr(elem, 'get_text'):  # BeautifulSoup
                    return elem.get_text(strip=True)
                elif hasattr(elem, 'text_content'):  # lxml
                    return elem.text_content().strip()
                elif isinstance(elem, str):  # Already text
                    return elem.strip()
                else:
                    return str(elem).strip()
            
            def get_element_attr(elem, attr):
                """Get attribute from BeautifulSoup or lxml element."""
                if hasattr(elem, 'get'):  # BeautifulSoup
                    return elem.get(attr, '')
                elif hasattr(elem, 'get'):  # lxml (also has get method)
                    return elem.get(attr, '')
                else:
                    return ''
            
            # Extract data based on selectors
            extracted_data = {}
            results = []
            
            # Define fallback selectors for common fields
            fallback_selectors = {
                'Company Name': [
                    'h1', 'h1.title', '.company-name', '.brand', '.logo-text', 
                    '[itemprop="name"]', '.site-title', 'title', 'meta[property="og:site_name"]',
                    'header h1', '.header h1', 'nav .brand', '.navbar-brand'
                ],
                'Homepage URL': [
                    'a.logo[href]', 'a[href="/"]', '.homepage-link', 'a.brand[href]',
                    'header a[href="/"]', 'nav a[href="/"]', '.logo a[href]'
                ],
                'Email': [
                    'a[href^="mailto:"]', '[itemprop="email"]', '.email', '.contact-email',
                    'a.email', '.mail', 'a[href*="mailto"]', '*[href^="mailto:"]'
                ],
                'Phone': [
                    'a[href^="tel:"]', '[itemprop="telephone"]', '.phone', '.contact-phone',
                    'a.phone', '.tel', 'a[href*="tel:"]', '*[href^="tel:"]'
                ],
                'Contact Page URL': [
                    'a[href*="contact"]', 'a.contact-link', 'nav a[href*="contact"]',
                    'a[href*="contact-us"]', 'a[href*="contactus"]', 'footer a[href*="contact"]'
                ],
                'Social Media URLs': [
                    'a[href*="facebook.com"]', 'a[href*="twitter.com"]', 'a[href*="linkedin.com"]',
                    'a[href*="instagram.com"]', 'a[href*="youtube.com"]', '.social-link',
                    'a.social', '.social-media a', 'footer a[href*="facebook"]',
                    'footer a[href*="twitter"]', 'footer a[href*="linkedin"]'
                ]
            }
            
            # Helper function to extract a predefined field
            def extract_predefined_field(field_name, soup, url):
                """Extract a predefined field using fallback selectors and regex."""
                elements = []
                found_value = None
                
                # Try fallback selectors
                if field_name in fallback_selectors:
                    for fallback_selector in fallback_selectors[field_name]:
                        try:
                            elements = soup.select(fallback_selector)
                            if elements:
                                if settings.DEBUG:
                                    print(f"Auto-extracted {field_name} using selector: {fallback_selector}")
                                break
                        except Exception:
                            continue
                
                # Process found elements
                if elements:
                    if len(elements) == 1:
                        elem = elements[0]
                        if 'email' in field_name.lower():
                            href = elem.get('href', '')
                            if href.startswith('mailto:'):
                                found_value = href.replace('mailto:', '').strip()
                            else:
                                text = elem.get_text()
                                email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                if email_match:
                                    found_value = email_match.group(0)
                        elif 'phone' in field_name.lower():
                            href = elem.get('href', '')
                            if href.startswith('tel:'):
                                found_value = href.replace('tel:', '').strip()
                            else:
                                found_value = elem.get_text(strip=True)
                            if found_value:
                                found_value = re.sub(r'[^\d+\-() ]', '', found_value).strip()
                        elif 'url' in field_name.lower() or 'social' in field_name.lower():
                            href = elem.get('href', '')
                            if href:
                                found_value = urljoin(url, href) if not href.startswith('http') else href
                                # Always return as array for Social Media URLs
                                if 'social' in field_name.lower():
                                    found_value = [found_value] if found_value else []
                            else:
                                found_value = elem.get_text(strip=True)
                                # Always return as array for Social Media URLs
                                if 'social' in field_name.lower():
                                    found_value = [found_value] if found_value else []
                        else:
                            found_value = elem.get_text(strip=True) or elem.get('href', '') or elem.get('src', '')
                    else:
                        # Multiple elements
                        values = []
                        for elem in elements:
                            if 'email' in field_name.lower():
                                href = elem.get('href', '')
                                if href.startswith('mailto:'):
                                    values.append(href.replace('mailto:', '').strip())
                                else:
                                    text = elem.get_text()
                                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                    if email_match:
                                        values.append(email_match.group(0))
                            elif 'phone' in field_name.lower():
                                href = elem.get('href', '')
                                if href.startswith('tel:'):
                                    values.append(href.replace('tel:', '').strip())
                                else:
                                    val = elem.get_text(strip=True)
                                    if val:
                                        values.append(re.sub(r'[^\d+\-() ]', '', val).strip())
                            elif 'url' in field_name.lower() or 'social' in field_name.lower():
                                href = elem.get('href', '')
                                if href:
                                    values.append(urljoin(url, href) if not href.startswith('http') else href)
                            else:
                                val = elem.get_text(strip=True) or elem.get('href', '') or elem.get('src', '')
                                if val:
                                    values.append(val)
                        
                        # Remove duplicates
                        seen = set()
                        unique_values = [v for v in values if v and v not in seen and not seen.add(v)]
                        # Always return as array for Social Media URLs
                        if 'social' in field_name.lower():
                            found_value = unique_values if unique_values else []
                        else:
                            found_value = unique_values if len(unique_values) > 1 else (unique_values[0] if unique_values else None)
                
                # Regex fallbacks for email and phone
                if not found_value:
                    if 'email' in field_name.lower():
                        page_text = soup.get_text()
                        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                        email_matches = re.findall(email_pattern, page_text)
                        if email_matches:
                            found_value = email_matches[0]
                            if settings.DEBUG:
                                print(f"Auto-extracted {field_name} using regex")
                    elif 'phone' in field_name.lower():
                        # First try tel: links
                        tel_links = soup.select('a[href^="tel:"], *[href^="tel:"]')
                        if tel_links:
                            found_value = tel_links[0].get('href', '').replace('tel:', '').strip()
                            if settings.DEBUG:
                                print(f"Auto-extracted {field_name} from tel: link: {found_value}")
                        else:
                            # Try itemprop="telephone"
                            tel_elem = soup.find(attrs={'itemprop': 'telephone'})
                            if tel_elem:
                                found_value = tel_elem.get_text(strip=True) or tel_elem.get('content', '')
                                if found_value:
                                    found_value = re.sub(r'[^\d+\-() ]', '', found_value)
                                    found_value = re.sub(r'\s+', ' ', found_value).strip()
                                    # Take only first phone if multiple found
                                    parts = re.split(r'[,\n\r;]', found_value)
                                    if parts:
                                        found_value = parts[0].strip()
                                    if settings.DEBUG:
                                        print(f"Auto-extracted {field_name} from itemprop: {found_value}")
                            
                            # If still not found, search page text with improved patterns
                            if not found_value:
                                page_text = soup.get_text()
                                # More comprehensive phone patterns
                                phone_patterns = [
                                    r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format with optional country code
                                    r'\+?\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # International
                                    r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
                                    r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # Simple format
                                    r'\+?[\d\s\-\(\)\.]{10,}',  # General pattern
                                ]
                                for pattern in phone_patterns:
                                    phone_matches = re.findall(pattern, page_text)
                                    if phone_matches:
                                        # Filter out false positives (like years, zip codes, etc.)
                                        for match in phone_matches:
                                            cleaned = re.sub(r'[^\d]', '', match)
                                            # Phone should have 10-15 digits
                                            if 10 <= len(cleaned) <= 15:
                                                # Preserve original format, just clean unwanted chars
                                                found_value = re.sub(r'[^\d+\-() ]', '', match)
                                                found_value = re.sub(r'\s+', ' ', found_value).strip()
                                                # Take only first phone if multiple found
                                                parts = re.split(r'[,\n\r;]', found_value)
                                                if parts:
                                                    found_value = parts[0].strip()
                                                if settings.DEBUG:
                                                    print(f"Auto-extracted {field_name} using regex: {found_value}")
                                                break
                                        if found_value:
                                            break
                    elif 'company name' in field_name.lower() or 'company' in field_name.lower():
                        title_tag = soup.find('title')
                        if title_tag:
                            title_text = title_tag.get_text(strip=True)
                            title_text = re.sub(r'\s*[-|]\s*(Home|Welcome|Official).*$', '', title_text, flags=re.IGNORECASE)
                            if title_text:
                                found_value = title_text
                        if not found_value:
                            og_site = soup.find('meta', property='og:site_name')
                            if og_site:
                                found_value = og_site.get('content', '').strip()
                        if not found_value:
                            h1_tag = soup.find('h1')
                            if h1_tag:
                                h1_text = h1_tag.get_text(strip=True)
                                if h1_text and len(h1_text) < 100:
                                    found_value = h1_text
                    elif 'homepage' in field_name.lower() and 'url' in field_name.lower():
                        # First try to find homepage link
                        homepage_links = soup.select('a[href="/"], a.logo[href], .homepage-link[href], a.brand[href], header a[href="/"], nav a[href="/"]')
                        if homepage_links:
                            href = homepage_links[0].get('href', '')
                            if href:
                                found_value = urljoin(url, href) if not href.startswith('http') else href
                        # If no link found, use the base URL of the website
                        if not found_value:
                            from urllib.parse import urlparse
                            parsed_url = urlparse(url)
                            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                            found_value = base_url
                    elif 'contact' in field_name.lower() and 'url' in field_name.lower():
                        contact_links = soup.select('a[href*="contact"]')
                        if contact_links:
                            href = contact_links[0].get('href', '')
                            if href:
                                found_value = urljoin(url, href) if not href.startswith('http') else href
                    elif 'social' in field_name.lower():
                        # Comprehensive list of social media domains
                        social_domains = [
                            'facebook.com', 'fb.com', 'm.facebook.com',
                            'twitter.com', 'x.com', 'mobile.twitter.com',
                            'linkedin.com', 'linkedin.com/company',
                            'instagram.com',
                            'youtube.com', 'youtu.be',
                            'tiktok.com',
                            'pinterest.com',
                            'snapchat.com',
                            'reddit.com',
                            'tumblr.com',
                            'flickr.com',
                            'vimeo.com',
                            'github.com',
                            'medium.com',
                            'behance.net',
                            'dribbble.com'
                        ]
                        social_links = []
                        # Try multiple selector patterns
                        for domain in social_domains:
                            # Direct href contains domain
                            links = soup.select(f'a[href*="{domain}"]')
                            social_links.extend(links)
                            # Also check data attributes and class names
                            domain_short = domain.split('.')[0]
                            links_by_class = soup.select(f'a[class*="{domain_short}"], a[class*="social"]')
                            for link in links_by_class:
                                href = link.get('href', '')
                                if domain in href.lower() and link not in social_links:
                                    social_links.append(link)
                        
                        # Also check for social media icons/links in common containers
                        social_containers = soup.select('.social, .social-media, .social-links, .social-icons, [class*="social"], footer a, .footer a')
                        for container in social_containers:
                            if container.name == 'a':
                                href = container.get('href', '')
                                if any(domain in href.lower() for domain in social_domains):
                                    if container not in social_links:
                                        social_links.append(container)
                            else:
                                # If it's a container, find links inside
                                links = container.select('a[href]')
                                for link in links:
                                    href = link.get('href', '')
                                    if any(domain in href.lower() for domain in social_domains):
                                        if link not in social_links:
                                            social_links.append(link)
                        
                        if social_links:
                            social_urls = []
                            seen_urls = set()
                            for link in social_links[:20]:  # Limit to 20
                                href = link.get('href', '')
                                if href:
                                    # Clean up href (remove tracking parameters)
                                    if '?' in href:
                                        href = href.split('?')[0]
                                    full_url = urljoin(url, href) if not href.startswith('http') else href
                                    # Normalize URL (remove trailing slashes, etc.)
                                    full_url = full_url.rstrip('/')
                                    if full_url not in seen_urls:
                                        seen_urls.add(full_url)
                                        social_urls.append(full_url)
                            
                            if social_urls:
                                # Always return as array for Social Media URLs
                                found_value = social_urls
                                if settings.DEBUG:
                                    print(f"Auto-extracted {field_name}: {found_value}")
                
                # Final safeguard: Always return array for Social Media URLs
                if 'social' in field_name.lower() and 'url' in field_name.lower():
                    if found_value is None:
                        return []
                    elif isinstance(found_value, list):
                        return found_value
                    else:
                        return [found_value]
                
                return found_value
            
            # Process user-provided selectors (if any)
            for field_name, selector in (selectors.items() if selectors else []):
                try:
                    elements = []
                    found_value = None
                    is_xpath_selector = is_xpath(selector)
                    
                    # Try the provided selector first
                    if selector and selector.strip():
                        try:
                            if is_xpath_selector:
                                # Use XPath
                                xpath_elements = extract_with_xpath(lxml_tree, selector.strip())
                                # Convert lxml elements to BeautifulSoup-like objects for consistent processing
                                # We'll process XPath results differently
                                elements = xpath_elements
                            else:
                                # Use CSS selector
                                elements = soup.select(selector.strip())
                        except Exception as e:
                            if settings.DEBUG:
                                print(f"Error with selector '{selector}': {e}")
                    
                    # If not found and not XPath, try splitting comma-separated selectors
                    if not elements and selector and ',' in selector and not is_xpath_selector:
                        selector_list = [s.strip() for s in selector.split(',') if s.strip()]
                        for single_selector in selector_list:
                            try:
                                elements = soup.select(single_selector)
                                if elements:
                                    if settings.DEBUG:
                                        print(f"Found {field_name} using individual selector: {single_selector}")
                                    break
                            except Exception as e:
                                if settings.DEBUG:
                                    print(f"Error with selector '{single_selector}': {e}")
                                continue
                    
                    # If still not found and we have fallbacks, try them
                    if not elements and field_name in fallback_selectors:
                        for fallback_selector in fallback_selectors[field_name]:
                            try:
                                elements = soup.select(fallback_selector)
                                if elements:
                                    if settings.DEBUG:
                                        print(f"Found {field_name} using fallback selector: {fallback_selector}")
                                    break
                            except Exception as e:
                                if settings.DEBUG:
                                    print(f"Error with fallback selector '{fallback_selector}': {e}")
                                continue
                    
                    # Also try text-based extraction for email and phone if no elements found
                    if not elements:
                        if 'email' in field_name.lower():
                            # Search entire page for email pattern
                            page_text = soup.get_text()
                            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                            email_matches = re.findall(email_pattern, page_text)
                            if email_matches:
                                found_value = email_matches[0]  # Take first match
                                if settings.DEBUG:
                                    print(f"Found {field_name} using regex pattern: {found_value}")
                        
                        elif 'phone' in field_name.lower():
                            # First try tel: links
                            tel_links = soup.select('a[href^="tel:"], *[href^="tel:"]')
                            if tel_links:
                                found_value = tel_links[0].get('href', '').replace('tel:', '').strip()
                                if settings.DEBUG:
                                    print(f"Found {field_name} from tel: link: {found_value}")
                            else:
                                # Try itemprop="telephone"
                                tel_elem = soup.find(attrs={'itemprop': 'telephone'})
                                if tel_elem:
                                    found_value = tel_elem.get_text(strip=True) or tel_elem.get('content', '')
                                    if found_value:
                                        found_value = re.sub(r'[^\d+\-() ]', '', found_value).strip()
                                        if settings.DEBUG:
                                            print(f"Found {field_name} from itemprop: {found_value}")
                                
                                # If still not found, search page text with improved patterns
                                if not found_value:
                                    page_text = soup.get_text()
                                    phone_patterns = [
                                        r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format with optional country code
                                        r'\+?\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # International
                                        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
                                        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # Simple format
                                        r'\+?[\d\s\-\(\)\.]{10,}',  # General pattern
                                    ]
                                    for pattern in phone_patterns:
                                        phone_matches = re.findall(pattern, page_text)
                                        if phone_matches:
                                            # Filter out false positives
                                            for match in phone_matches:
                                                cleaned = re.sub(r'[^\d]', '', match)
                                                if 10 <= len(cleaned) <= 15:
                                                    # Preserve original format, just clean unwanted chars
                                                    found_value = re.sub(r'[^\d+\-() ]', '', match)
                                                    found_value = re.sub(r'\s+', ' ', found_value).strip()
                                                    # Take only first phone if multiple found
                                                    parts = re.split(r'[,\n\r;]', found_value)
                                                    if parts:
                                                        found_value = parts[0].strip()
                                                    if settings.DEBUG:
                                                        print(f"Found {field_name} using regex: {found_value}")
                                                    break
                                            if found_value:
                                                break
                    
                    if elements:
                        if len(elements) == 1:
                            # Single element - get text or attribute
                            elem = elements[0]
                            value = None
                            
                            # Special handling for email
                            if 'email' in field_name.lower():
                                href = get_element_attr(elem, 'href')
                                if href and href.startswith('mailto:'):
                                    value = href.replace('mailto:', '').strip()
                                else:
                                    value = get_element_text(elem)
                                # Also check for email pattern in text
                                if not value or '@' not in value:
                                    text = get_element_text(elem) if not hasattr(elem, 'get_text') else elem.get_text()
                                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                    if email_match:
                                        value = email_match.group(0)
                            
                            # Special handling for phone
                            elif 'phone' in field_name.lower():
                                href = get_element_attr(elem, 'href')
                                if href and href.startswith('tel:'):
                                    value = href.replace('tel:', '').strip()
                                else:
                                    value = get_element_text(elem)
                                # Clean phone number but preserve formatting
                                if value:
                                    value = re.sub(r'[^\d+\-() ]', '', value)
                                    value = re.sub(r'\s+', ' ', value).strip()
                                    # Take only first phone if multiple found
                                    parts = re.split(r'[,\n\r;]', value)
                                    if parts:
                                        value = parts[0].strip()
                            
                            # Special handling for URLs (homepage, contact, social media)
                            elif 'url' in field_name.lower() or 'social' in field_name.lower():
                                href = get_element_attr(elem, 'href')
                                if href:
                                    # Convert relative URLs to absolute
                                    if href.startswith('/'):
                                        value = urljoin(url, href)
                                    elif href.startswith('http'):
                                        value = href
                                    else:
                                        value = urljoin(url, href)
                                else:
                                    value = get_element_text(elem)
                            
                            # Default: get text or href/src
                            else:
                                value = get_element_text(elem) or get_element_attr(elem, 'href') or get_element_attr(elem, 'src')
                                # Convert relative URLs to absolute if it's a URL
                                if value and (value.startswith('/') or not value.startswith('http')):
                                    if 'url' in field_name.lower() or 'link' in field_name.lower():
                                        if value.startswith('/') or not value.startswith('http'):
                                            value = urljoin(url, value)
                            
                            # Always return as array for Social Media URLs
                            if 'social' in field_name.lower() and 'url' in field_name.lower():
                                extracted_data[field_name] = [value] if value else []
                                found_value = [value] if value else []
                            else:
                                extracted_data[field_name] = value
                                found_value = value
                            
                            results.append({
                                'field_name': field_name,
                                'value': found_value,
                                'selector': selector
                            })
                        else:
                            # Multiple elements - return as list
                            values = []
                            for elem in elements:
                                value = None
                                
                                # Special handling for email
                                if 'email' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href.startswith('mailto:'):
                                        value = href.replace('mailto:', '').strip()
                                    else:
                                        value = elem.get_text(strip=True)
                                    # Also check for email pattern in text
                                    if not value or '@' not in value:
                                        text = elem.get_text()
                                        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                        if email_match:
                                            value = email_match.group(0)
                                
                                # Special handling for phone
                                elif 'phone' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href.startswith('tel:'):
                                        value = href.replace('tel:', '').strip()
                                    else:
                                        value = elem.get_text(strip=True)
                                    # Clean phone number but preserve formatting
                                    if value:
                                        value = re.sub(r'[^\d+\-() ]', '', value)
                                        value = re.sub(r'\s+', ' ', value).strip()
                                        # Take only first phone if multiple found
                                        parts = re.split(r'[,\n\r;]', value)
                                        if parts:
                                            value = parts[0].strip()
                                
                                # Special handling for URLs
                                elif 'url' in field_name.lower() or 'social' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href:
                                        if href.startswith('/'):
                                            value = urljoin(url, href)
                                        elif href.startswith('http'):
                                            value = href
                                        else:
                                            value = urljoin(url, href)
                                    else:
                                        value = elem.get_text(strip=True)
                                
                                # Default
                                else:
                                    value = elem.get_text(strip=True) or elem.get('href', '') or elem.get('src', '')
                                    # Convert relative URLs to absolute
                                    if value and (value.startswith('/') or not value.startswith('http')):
                                        if 'url' in field_name.lower() or 'link' in field_name.lower():
                                            value = urljoin(url, value)
                                
                                if value:
                                    values.append(value)
                            
                            # Remove duplicates while preserving order
                            seen = set()
                            unique_values = []
                            for v in values:
                                if v not in seen:
                                    seen.add(v)
                                    unique_values.append(v)
                            
                            # Always return as array for Social Media URLs
                            if 'social' in field_name.lower() and 'url' in field_name.lower():
                                extracted_data[field_name] = unique_values if unique_values else []
                                result_value = unique_values if unique_values else []
                            else:
                                extracted_data[field_name] = unique_values if len(unique_values) > 1 else (unique_values[0] if unique_values else None)
                                result_value = unique_values if len(unique_values) > 1 else (unique_values[0] if unique_values else None)
                            
                            results.append({
                                'field_name': field_name,
                                'value': result_value,
                                'selector': selector
                            })
                    elif found_value:
                        # Use value found by regex/fallback
                        # Always return as array for Social Media URLs
                        if 'social' in field_name.lower() and 'url' in field_name.lower():
                            if isinstance(found_value, list):
                                extracted_data[field_name] = found_value
                            else:
                                extracted_data[field_name] = [found_value] if found_value else []
                        else:
                            extracted_data[field_name] = found_value
                        
                        results.append({
                            'field_name': field_name,
                            'value': extracted_data[field_name],
                            'selector': 'regex/fallback'
                        })
                    else:
                        # If still not found, try regex extraction as last resort
                        if not found_value:
                            if 'email' in field_name.lower():
                                # Search entire page for email
                                page_text = soup.get_text()
                                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                                email_matches = re.findall(email_pattern, page_text)
                                if email_matches:
                                    found_value = email_matches[0]
                                    if settings.DEBUG:
                                        print(f"Found {field_name} using page-wide regex search")
                            
                            elif 'phone' in field_name.lower():
                                # First try tel: links
                                tel_links = soup.select('a[href^="tel:"], *[href^="tel:"]')
                                if tel_links:
                                    found_value = tel_links[0].get('href', '').replace('tel:', '').strip()
                                    if settings.DEBUG:
                                        print(f"Found {field_name} from tel: link: {found_value}")
                                else:
                                    # Try itemprop="telephone"
                                    tel_elem = soup.find(attrs={'itemprop': 'telephone'})
                                    if tel_elem:
                                        found_value = tel_elem.get_text(strip=True) or tel_elem.get('content', '')
                                        if found_value:
                                            found_value = re.sub(r'[^\d+\-() ]', '', found_value).strip()
                                            if settings.DEBUG:
                                                print(f"Found {field_name} from itemprop: {found_value}")
                                    
                                    # If still not found, search page text with improved patterns
                                    if not found_value:
                                        page_text = soup.get_text()
                                        phone_patterns = [
                                            r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format with optional country code
                                            r'\+?\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # International
                                            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
                                            r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # Simple format
                                            r'\+?[\d\s\-\(\)\.]{10,}',  # General pattern
                                        ]
                                        for pattern in phone_patterns:
                                            phone_matches = re.findall(pattern, page_text)
                                            if phone_matches:
                                                # Filter out false positives
                                                for match in phone_matches:
                                                    cleaned = re.sub(r'[^\d]', '', match)
                                                    if 10 <= len(cleaned) <= 15:
                                                        found_value = match.strip()
                                                        if settings.DEBUG:
                                                            print(f"Found {field_name} using regex: {found_value}")
                                                        break
                                                if found_value:
                                                    break
                            
                            elif 'company name' in field_name.lower() or 'company' in field_name.lower():
                                # Try to get from title tag or meta tags
                                title_tag = soup.find('title')
                                if title_tag:
                                    title_text = title_tag.get_text(strip=True)
                                    # Remove common suffixes
                                    title_text = re.sub(r'\s*[-|]\s*(Home|Welcome|Official).*$', '', title_text, flags=re.IGNORECASE)
                                    if title_text:
                                        found_value = title_text
                                        if settings.DEBUG:
                                            print(f"Found {field_name} from title tag: {found_value}")
                                
                                # Try meta og:site_name
                                if not found_value:
                                    og_site = soup.find('meta', property='og:site_name')
                                    if og_site:
                                        found_value = og_site.get('content', '').strip()
                                        if settings.DEBUG:
                                            print(f"Found {field_name} from og:site_name: {found_value}")
                                
                                # Try h1 tag as last resort
                                if not found_value:
                                    h1_tag = soup.find('h1')
                                    if h1_tag:
                                        h1_text = h1_tag.get_text(strip=True)
                                        if h1_text and len(h1_text) < 100:  # Reasonable length
                                            found_value = h1_text
                                            if settings.DEBUG:
                                                print(f"Found {field_name} from h1 tag: {found_value}")
                            
                            elif 'homepage' in field_name.lower() or ('homepage' in field_name.lower() and 'url' in field_name.lower()):
                                # Try to find homepage link
                                homepage_links = soup.select('a[href="/"], a.logo[href], .homepage-link[href], a.brand[href], header a[href="/"], nav a[href="/"]')
                                if homepage_links:
                                    href = homepage_links[0].get('href', '')
                                    if href:
                                        found_value = urljoin(url, href) if not href.startswith('http') else href
                                        if settings.DEBUG:
                                            print(f"Found {field_name} from homepage link: {found_value}")
                                # If no link found, use the base URL of the website
                                if not found_value:
                                    from urllib.parse import urlparse
                                    parsed_url = urlparse(url)
                                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    found_value = base_url
                                    if settings.DEBUG:
                                        print(f"Using base URL for {field_name}: {found_value}")
                            
                            elif 'contact' in field_name.lower() and 'url' in field_name.lower():
                                # Try to find contact page link
                                contact_links = soup.select('a[href*="contact"]')
                                if contact_links:
                                    href = contact_links[0].get('href', '')
                                    if href:
                                        found_value = urljoin(url, href) if not href.startswith('http') else href
                                        if settings.DEBUG:
                                            print(f"Found {field_name} from contact link: {found_value}")
                            
                            elif 'social' in field_name.lower():
                                # Comprehensive list of social media domains
                                social_domains = [
                                    'facebook.com', 'fb.com', 'm.facebook.com',
                                    'twitter.com', 'x.com', 'mobile.twitter.com',
                                    'linkedin.com', 'linkedin.com/company',
                                    'instagram.com',
                                    'youtube.com', 'youtu.be',
                                    'tiktok.com',
                                    'pinterest.com',
                                    'snapchat.com',
                                    'reddit.com',
                                    'tumblr.com',
                                    'flickr.com',
                                    'vimeo.com',
                                    'github.com',
                                    'medium.com',
                                    'behance.net',
                                    'dribbble.com'
                                ]
                                social_links = []
                                # Try multiple selector patterns
                                for domain in social_domains:
                                    links = soup.select(f'a[href*="{domain}"]')
                                    social_links.extend(links)
                                    domain_short = domain.split('.')[0]
                                    links_by_class = soup.select(f'a[class*="{domain_short}"], a[class*="social"]')
                                    for link in links_by_class:
                                        href = link.get('href', '')
                                        if domain in href.lower() and link not in social_links:
                                            social_links.append(link)
                                
                                # Also check social containers
                                social_containers = soup.select('.social, .social-media, .social-links, .social-icons, [class*="social"], footer a, .footer a')
                                for container in social_containers:
                                    if container.name == 'a':
                                        href = container.get('href', '')
                                        if any(domain in href.lower() for domain in social_domains):
                                            if container not in social_links:
                                                social_links.append(container)
                                    else:
                                        links = container.select('a[href]')
                                        for link in links:
                                            href = link.get('href', '')
                                            if any(domain in href.lower() for domain in social_domains):
                                                if link not in social_links:
                                                    social_links.append(link)
                                
                                if social_links:
                                    social_urls = []
                                    seen_urls = set()
                                    for link in social_links[:20]:
                                        href = link.get('href', '')
                                        if href:
                                            if '?' in href:
                                                href = href.split('?')[0]
                                            full_url = urljoin(url, href) if not href.startswith('http') else href
                                            full_url = full_url.rstrip('/')
                                            if full_url not in seen_urls:
                                                seen_urls.add(full_url)
                                                social_urls.append(full_url)
                                    
                                    if social_urls:
                                        # Always return as array for Social Media URLs
                                        found_value = social_urls
                                        if settings.DEBUG:
                                            print(f"Found {field_name}: {found_value}")
                        
                        if found_value:
                            # Always return as array for Social Media URLs
                            if 'social' in field_name.lower() and 'url' in field_name.lower():
                                if isinstance(found_value, list):
                                    extracted_data[field_name] = found_value
                                else:
                                    extracted_data[field_name] = [found_value] if found_value else []
                            else:
                                extracted_data[field_name] = found_value
                            
                            results.append({
                                'field_name': field_name,
                                'value': extracted_data[field_name],
                                'selector': 'regex/fallback'
                            })
                        else:
                            extracted_data[field_name] = None
                            results.append({
                                'field_name': field_name,
                                'value': None,
                                'selector': selector
                            })
                except Exception as e:
                    extracted_data[field_name] = None
                    if settings.DEBUG:
                        print(f"Error extracting {field_name} with selector {selector}: {str(e)}")
            
            # Helper function to extract all social media URLs by platform
            def extract_social_media_by_platform(soup, url):
                """Extract social media URLs and categorize by platform."""
                social_platforms = {
                    'LinkedIn': ['linkedin.com'],
                    'Facebook': ['facebook.com', 'fb.com', 'm.facebook.com'],
                    'Twitter/X': ['twitter.com', 'x.com', 'mobile.twitter.com'],
                    'Instagram': ['instagram.com'],
                    'YouTube': ['youtube.com', 'youtu.be'],
                    'TikTok': ['tiktok.com'],
                    'Pinterest': ['pinterest.com'],
                    'Snapchat': ['snapchat.com'],
                    'Reddit': ['reddit.com'],
                    'Tumblr': ['tumblr.com'],
                    'Flickr': ['flickr.com'],
                    'Vimeo': ['vimeo.com'],
                    'GitHub': ['github.com'],
                    'Medium': ['medium.com'],
                    'Behance': ['behance.net'],
                    'Dribbble': ['dribbble.com']
                }
                
                platform_urls = {}
                all_social_links = []
                
                # Collect all social media links
                for platform, domains in social_platforms.items():
                    platform_links = []
                    for domain in domains:
                        # Direct href contains domain
                        links = soup.select(f'a[href*="{domain}"]')
                        platform_links.extend(links)
                        
                        # Also check class names
                        domain_short = domain.split('.')[0]
                        links_by_class = soup.select(f'a[class*="{domain_short}"], a[class*="social"]')
                        for link in links_by_class:
                            href = link.get('href', '')
                            if domain in href.lower() and link not in platform_links:
                                platform_links.append(link)
                    
                    # Also check social containers
                    social_containers = soup.select('.social, .social-media, .social-links, .social-icons, [class*="social"], footer a, .footer a')
                    for container in social_containers:
                        if container.name == 'a':
                            href = container.get('href', '')
                            if any(domain in href.lower() for domain in domains):
                                if container not in platform_links:
                                    platform_links.append(container)
                        else:
                            links = container.select('a[href]')
                            for link in links:
                                href = link.get('href', '')
                                if any(domain in href.lower() for domain in domains):
                                    if link not in platform_links:
                                        platform_links.append(link)
                    
                    # Extract URLs for this platform
                    seen_urls = set()
                    for link in platform_links[:5]:  # Limit to 5 per platform
                        href = link.get('href', '')
                        if href:
                            # Clean up href
                            if '?' in href:
                                href = href.split('?')[0]
                            full_url = urljoin(url, href) if not href.startswith('http') else href
                            full_url = full_url.rstrip('/')
                            if full_url not in seen_urls:
                                seen_urls.add(full_url)
                                if platform not in platform_urls:
                                    platform_urls[platform] = []
                                platform_urls[platform].append(full_url)
                    
                    # Take first URL for each platform (or None if none found)
                    if platform in platform_urls and platform_urls[platform]:
                        platform_urls[platform] = platform_urls[platform][0]
                    else:
                        platform_urls[platform] = None
                
                return platform_urls
            
            # Automatically extract predefined fields (if not already extracted by user selectors)
            predefined_fields = ['Company Name', 'Homepage URL', 'Email', 'Phone', 'Contact Page URL']
            for field_name in predefined_fields:
                if field_name not in extracted_data or extracted_data[field_name] is None:
                    auto_value = extract_predefined_field(field_name, soup, url)
                    if auto_value:
                        extracted_data[field_name] = auto_value
                        results.append({
                            'field_name': field_name,
                            'value': extracted_data[field_name],
                            'selector': 'auto-extracted'
                        })
                    else:
                        extracted_data[field_name] = None
                        results.append({
                            'field_name': field_name,
                            'value': None,
                            'selector': 'auto-extracted'
                        })
            
            # Extract social media URLs by platform (always extract, even if user provided selectors)
            social_platforms = extract_social_media_by_platform(soup, url)
            for platform, platform_url in social_platforms.items():
                extracted_data[platform] = platform_url
                results.append({
                    'field_name': platform,
                    'value': platform_url,
                    'selector': 'auto-extracted'
                })
            
            # Extract tables if requested or automatically
            # Check if user requested table extraction
            if selectors and any('table' in field_name.lower() for field_name in selectors.keys()):
                tables = extract_tables(soup)
                if tables:
                    extracted_data['Tables'] = tables
                    results.append({
                        'field_name': 'Tables',
                        'value': tables,
                        'selector': 'auto-extracted'
                    })
            # Also extract tables automatically (can be disabled if needed)
            elif 'Tables' not in extracted_data:
                tables = extract_tables(soup)
                if tables:
                    extracted_data['Tables'] = tables
                    results.append({
                        'field_name': 'Tables',
                        'value': tables,
                        'selector': 'auto-extracted'
                    })
            
            # Save extracted data
            scraping_request.extracted_data = extracted_data
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            
            # Save individual results
            for result in results:
                WebScrapingResult.objects.create(
                    request=scraping_request,
                    field_name=result['field_name'],
                    field_value=json.dumps(result['value']) if isinstance(result['value'], (list, dict)) else str(result['value']),
                    selector=result['selector']
                )
            
            return JsonResponse({
                'success': True,
                'url': url,
                'extracted_data': extracted_data,
                'results': results,
                'request_id': scraping_request.id,
                'status_code': response.status_code
            })
            
        except requests.exceptions.RequestException as e:
            scraping_request.error_message = str(e)
            scraping_request.completed_at = timezone.now()
            scraping_request.save()
            return JsonResponse({
                'error': f'Request failed: {str(e)}',
                'request_id': scraping_request.id
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


def process_bulk_urls(request_id, normalized_urls, selectors, method, headers, user_agent, wait_time, delay_between_urls):
    """
    Background function to process bulk URLs.
    This runs in a separate thread to avoid blocking the HTTP request.
    """
    # Initialize variables BEFORE try block so they're available in exception handler
    all_results = []
    completed = 0
    failed = 0
    
    try:
        # Import Django components
        from django.db import connections
        from django.core.cache import cache
        from django.conf import settings
        from .models import BulkWebScrapingRequest
        from django.utils import timezone
        
        # Close any existing database connections in this thread
        connections.close_all()
        
        print(f"[Bulk Scrape Thread] Thread started for request ID {request_id}", flush=True)
        print(f"[Bulk Scrape Thread] About to query database for request ID {request_id}", flush=True)
        
        # Update cache immediately to show thread is running
        request_id_str = str(request_id)
        cache.set(f'bulk_scrape_progress_{request_id_str}', {
            'total': len(normalized_urls),
            'completed': 0,
            'failed': 0,
            'current_url': normalized_urls[0] if normalized_urls else None,
            'current_index': 0,
            'status': 'processing',
            'message': f'Thread started. Processing {len(normalized_urls)} URLs...'
        }, timeout=7200)
        
        print(f"[Bulk Scrape Thread] Cache initialized for request ID {request_id} (key: bulk_scrape_progress_{request_id_str})", flush=True)
        # Verify it was set
        verify = cache.get(f'bulk_scrape_progress_{request_id_str}')
        print(f"[Bulk Scrape Thread] Cache verification: {verify}", flush=True)
        
        # Get the bulk request object
        bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
        
        print(f"[Bulk Scrape Thread] Successfully retrieved bulk request object", flush=True)
        
        # Get headers and user_agent from the bulk request object
        stored_headers = bulk_request.headers if hasattr(bulk_request, 'headers') and bulk_request.headers else {}
        stored_user_agent = bulk_request.user_agent if hasattr(bulk_request, 'user_agent') else ''
        
        # Also get selectors, method, wait_time, delay_between_urls from the bulk request
        if not selectors and hasattr(bulk_request, 'selectors') and bulk_request.selectors:
            selectors = bulk_request.selectors
        if not method and hasattr(bulk_request, 'method') and bulk_request.method:
            method = bulk_request.method
        if not wait_time and hasattr(bulk_request, 'wait_time'):
            wait_time = bulk_request.wait_time
        if not delay_between_urls and hasattr(bulk_request, 'delay_between_urls'):
            delay_between_urls = getattr(bulk_request, 'delay_between_urls', 0)
        
        # Prepare request headers
        request_headers = {
            'User-Agent': user_agent or stored_user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        request_headers.update(stored_headers)
        request_headers.update(headers)  # Allow override
        
        print(f"[Bulk Scrape Thread] Starting processing for request ID {request_id} with {len(normalized_urls)} URLs", flush=True)
        print(f"[Bulk Scrape Thread] About to start loop with {len(normalized_urls)} URLs", flush=True)
        
        for idx, url in enumerate(normalized_urls):
            # Initialize variables at the start of each iteration
            html_content = None
            response_text = None
            response_status = None
            response = None  # Initialize response variable BEFORE try block
            
            try:
                # Update progress BEFORE processing
                request_id_str = str(request_id)
                cache.set(f'bulk_scrape_progress_{request_id_str}', {
                    'total': len(normalized_urls),
                    'completed': completed,
                    'failed': failed,
                    'current_url': url,
                    'current_index': idx + 1,
                    'status': 'processing',
                    'message': f'Processing URL {idx + 1} of {len(normalized_urls)}: {url[:50]}...'
                }, timeout=7200)
                
                print(f"[Bulk Scrape Thread] Starting URL {idx + 1}/{len(normalized_urls)}: {url}", flush=True)
                
                # Wait if specified (before scraping)
                if wait_time > 0:
                    time.sleep(wait_time)
                
                # Check if JavaScript rendering is needed
                use_js_rendering = method in ['selenium', 'playwright']
                
                if use_js_rendering:
                    # Use Selenium or Playwright for JavaScript rendering
                    try:
                        if method == 'selenium':
                            try:
                                from selenium import webdriver
                                from selenium.webdriver.chrome.options import Options
                                from selenium.webdriver.chrome.service import Service
                                
                                chrome_options = Options()
                                chrome_options.add_argument('--headless')
                                chrome_options.add_argument('--no-sandbox')
                                chrome_options.add_argument('--disable-dev-shm-usage')
                                chrome_options.add_argument('--disable-gpu')
                                chrome_options.add_argument(f'user-agent={stored_user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}')
                                
                                # Try Chrome first, then Chromium
                                try:
                                    driver = webdriver.Chrome(options=chrome_options)
                                except Exception:
                                    # Fallback to Chromium if Chrome is not available
                                    chrome_options.binary_location = '/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else '/usr/bin/chromium-browser'
                                    driver = webdriver.Chrome(options=chrome_options)
                                try:
                                    driver.get(url)
                                    if wait_time > 0:
                                        time.sleep(wait_time)
                                    html_content = driver.page_source
                                    response_status = 200
                                finally:
                                    driver.quit()
                            except ImportError as import_err:
                                error_msg = f'Selenium not installed. Install with: pip install selenium. Error: {str(import_err)}'
                                if settings.DEBUG:
                                    print(f"[Bulk Scrape] Selenium ImportError: {import_err}", flush=True)
                                all_results.append({
                                    'url': url,
                                    'success': False,
                                    'error': error_msg,
                                    'status_code': None
                                })
                                failed += 1
                                if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                                    time.sleep(delay_between_urls)
                                continue
                            except Exception as selenium_err:
                                # Handle other Selenium errors (like ChromeDriver not found)
                                error_msg = f'Selenium error: {str(selenium_err)}'
                                if settings.DEBUG:
                                    print(f"[Bulk Scrape] Selenium error for {url}: {selenium_err}", flush=True)
                                all_results.append({
                                    'url': url,
                                    'success': False,
                                    'error': error_msg,
                                    'status_code': None
                                })
                                failed += 1
                                if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                                    time.sleep(delay_between_urls)
                                continue
                        
                        elif method == 'playwright':
                            try:
                                from playwright.sync_api import sync_playwright
                                
                                with sync_playwright() as p:
                                    browser = p.chromium.launch(headless=True)
                                    context = browser.new_context(user_agent=stored_user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                                    page = context.new_page()
                                    page.goto(url)
                                    if wait_time > 0:
                                        page.wait_for_timeout(int(wait_time * 1000))
                                    html_content = page.content()
                                    response_status = 200
                                    browser.close()
                            except ImportError:
                                all_results.append({
                                    'url': url,
                                    'success': False,
                                    'error': 'Playwright not installed. Install with: pip install playwright && playwright install chromium',
                                    'status_code': None
                                })
                                failed += 1
                                if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                                    time.sleep(delay_between_urls)
                                continue
                            except Exception as e:
                                all_results.append({
                                    'url': url,
                                    'success': False,
                                    'error': f'Playwright error: {str(e)}. Make sure browsers are installed: playwright install chromium',
                                    'status_code': None
                                })
                                failed += 1
                                if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                                    time.sleep(delay_between_urls)
                                continue
                    
                    except Exception as e:
                        all_results.append({
                            'url': url,
                            'success': False,
                            'error': f'JavaScript rendering failed: {str(e)}',
                            'status_code': None
                        })
                        failed += 1
                        if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                            time.sleep(delay_between_urls)
                        continue
                
                # Get HTML content
                if html_content:
                    response_text = html_content
                    response_status = 200
                else:
                    # Use retry logic with SSL handling
                    print(f"[Bulk Scrape Thread] Making request for URL {idx + 1}: {url}", flush=True)
                    
                    response = make_request_with_retry(url, headers=request_headers, timeout=30, max_retries=3, verify_ssl=False)
                    
                    print(f"[Bulk Scrape Thread] Got response for URL {idx + 1}: {url} - Status: {response.status_code if response else 'None'}", flush=True)
                    
                    if response is None:
                        all_results.append({
                            'url': url,
                            'success': False,
                            'error': 'Connection failed after multiple retries',
                            'status_code': None
                        })
                        failed += 1
                        # Wait between URLs (processing delay)
                        if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                            time.sleep(delay_between_urls)
                        continue
                    
                    response_text = response.text
                    response_status = response.status_code
                
                if response_status == 200:
                    print(f"[Bulk Scrape Thread] Processing URL {idx + 1}/{len(normalized_urls)}: {url}", flush=True)
                    
                    soup = BeautifulSoup(response_text, 'lxml')
                    lxml_tree = html.fromstring(response_text.encode('utf-8'))
                    
                    # Extract data - reuse full logic from web_scrape
                    extracted_data = {}
                    
                    # Define fallback selectors (same as in web_scrape)
                    fallback_selectors = {
                        'Company Name': ['h1', '.company-name', '.brand', '.site-title', 'title'],
                        'Homepage URL': ['a[href="/"]', 'a.logo[href]', '.homepage-link[href]'],
                        'Email': ['a[href^="mailto:"]', '[itemprop="email"]', '.email', 'a.email'],
                        'Phone': ['a[href^="tel:"]', '[itemprop="telephone"]', '.phone', '.tel'],
                        'Contact Page URL': ['a[href*="contact"]', 'a.contact[href]', 'nav a[href*="contact"]']
                    }
                    
                    # Helper function to extract predefined field (inline version for bulk)
                    def extract_predefined_field_bulk(field_name, soup, url):
                        """Extract a predefined field using fallback selectors and regex."""
                        elements = []
                        found_value = None
                        
                        if field_name in fallback_selectors:
                            for fallback_selector in fallback_selectors[field_name]:
                                try:
                                    elements = soup.select(fallback_selector)
                                    if elements:
                                        break
                                except Exception:
                                    continue
                        
                        if elements:
                            if len(elements) == 1:
                                elem = elements[0]
                                if 'email' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href.startswith('mailto:'):
                                        found_value = href.replace('mailto:', '').strip()
                                    else:
                                        text = elem.get_text()
                                        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                        if email_match:
                                            found_value = email_match.group(0)
                                elif 'phone' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href.startswith('tel:'):
                                        found_value = href.replace('tel:', '').strip()
                                    else:
                                        found_value = elem.get_text(strip=True)
                                    if found_value:
                                        # Clean phone number but preserve spaces and formatting
                                        # Remove only unwanted characters, keep digits, +, -, (), spaces
                                        found_value = re.sub(r'[^\d+\-() ]', '', found_value)
                                        # Normalize multiple spaces to single space
                                        found_value = re.sub(r'\s+', ' ', found_value).strip()
                                        # Take only the first phone number if multiple are found
                                        # Split by common separators and take first valid one
                                        parts = re.split(r'[,\n\r;]', found_value)
                                        if parts:
                                            found_value = parts[0].strip()
                                elif 'url' in field_name.lower():
                                    href = elem.get('href', '')
                                    if href:
                                        found_value = urljoin(url, href) if not href.startswith('http') else href
                                    else:
                                        found_value = elem.get_text(strip=True)
                                else:
                                    found_value = elem.get_text(strip=True) or elem.get('href', '') or elem.get('src', '')
                            else:
                                values = []
                                for elem in elements:
                                    if 'email' in field_name.lower():
                                        href = elem.get('href', '')
                                        if href.startswith('mailto:'):
                                            values.append(href.replace('mailto:', '').strip())
                                        else:
                                            text = elem.get_text()
                                            email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
                                            if email_match:
                                                values.append(email_match.group(0))
                                    elif 'phone' in field_name.lower():
                                        href = elem.get('href', '')
                                        if href.startswith('tel:'):
                                            phone_val = href.replace('tel:', '').strip()
                                            # Clean but preserve formatting
                                            phone_val = re.sub(r'[^\d+\-() ]', '', phone_val)
                                            phone_val = re.sub(r'\s+', ' ', phone_val).strip()
                                            values.append(phone_val)
                                        else:
                                            val = elem.get_text(strip=True)
                                            if val:
                                                # Clean but preserve formatting
                                                phone_val = re.sub(r'[^\d+\-() ]', '', val)
                                                phone_val = re.sub(r'\s+', ' ', phone_val).strip()
                                                # Take only first phone if multiple
                                                parts = re.split(r'[,\n\r;]', phone_val)
                                                if parts:
                                                    values.append(parts[0].strip())
                                    elif 'url' in field_name.lower():
                                        href = elem.get('href', '')
                                        if href:
                                            values.append(urljoin(url, href) if not href.startswith('http') else href)
                                    else:
                                        val = elem.get_text(strip=True) or elem.get('href', '') or elem.get('src', '')
                                        if val:
                                            values.append(val)
                                
                                seen = set()
                                unique_values = [v for v in values if v and v not in seen and not seen.add(v)]
                                found_value = unique_values if len(unique_values) > 1 else (unique_values[0] if unique_values else None)
                        
                        # Regex fallbacks
                        if not found_value:
                            if 'email' in field_name.lower():
                                page_text = soup.get_text()
                                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                                email_matches = re.findall(email_pattern, page_text)
                                if email_matches:
                                    found_value = email_matches[0]
                            elif 'phone' in field_name.lower():
                                tel_links = soup.select('a[href^="tel:"], *[href^="tel:"]')
                                if tel_links:
                                    found_value = tel_links[0].get('href', '').replace('tel:', '').strip()
                                else:
                                    tel_elem = soup.find(attrs={'itemprop': 'telephone'})
                                    if tel_elem:
                                        found_value = tel_elem.get_text(strip=True) or tel_elem.get('content', '')
                                        if found_value:
                                            found_value = re.sub(r'[^\d+\-() ]', '', found_value)
                                            found_value = re.sub(r'\s+', ' ', found_value).strip()
                                            # Take only first phone if multiple found
                                            parts = re.split(r'[,\n\r;]', found_value)
                                            if parts:
                                                found_value = parts[0].strip()
                            elif 'company name' in field_name.lower() or 'company' in field_name.lower():
                                title_tag = soup.find('title')
                                if title_tag:
                                    title_text = title_tag.get_text(strip=True)
                                    title_text = re.sub(r'\s*[-|]\s*(Home|Welcome|Official).*$', '', title_text, flags=re.IGNORECASE)
                                    if title_text:
                                        found_value = title_text
                                if not found_value:
                                    og_site = soup.find('meta', property='og:site_name')
                                    if og_site:
                                        found_value = og_site.get('content', '').strip()
                                if not found_value:
                                    h1_tag = soup.find('h1')
                                    if h1_tag:
                                        h1_text = h1_tag.get_text(strip=True)
                                        if h1_text and len(h1_text) < 100:
                                            found_value = h1_text
                            elif 'homepage' in field_name.lower() and 'url' in field_name.lower():
                                homepage_links = soup.select('a[href="/"], a.logo[href], .homepage-link[href]')
                                if homepage_links:
                                    href = homepage_links[0].get('href', '')
                                    if href:
                                        found_value = urljoin(url, href) if not href.startswith('http') else href
                                if not found_value:
                                    from urllib.parse import urlparse
                                    parsed_url = urlparse(url)
                                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    found_value = base_url
                            elif 'contact' in field_name.lower() and 'url' in field_name.lower():
                                contact_links = soup.select('a[href*="contact"]')
                                if contact_links:
                                    href = contact_links[0].get('href', '')
                                    if href:
                                        found_value = urljoin(url, href) if not href.startswith('http') else href
                        
                        return found_value
                    
                    # Helper function to extract social media (simplified version)
                    def extract_social_media_by_platform_bulk(soup, url):
                        """Extract social media URLs by platform."""
                        social_domains = {
                            'LinkedIn': ['linkedin.com'],
                            'Facebook': ['facebook.com', 'fb.com'],
                            'Twitter/X': ['twitter.com', 'x.com'],
                            'Instagram': ['instagram.com'],
                            'YouTube': ['youtube.com', 'youtu.be'],
                            'TikTok': ['tiktok.com'],
                            'Pinterest': ['pinterest.com']
                        }
                        
                        platform_urls = {}
                        for platform, domains in social_domains.items():
                            platform_links = []
                            for domain in domains:
                                links = soup.select(f'a[href*="{domain}"]')
                                for link in links[:3]:  # Limit to 3 per domain
                                    href = link.get('href', '')
                                    if href and any(d in href.lower() for d in domains):
                                        full_url = urljoin(url, href) if not href.startswith('http') else href
                                        if full_url not in platform_links:
                                            platform_links.append(full_url)
                            
                            platform_urls[platform] = platform_links[0] if platform_links else None
                        
                        return platform_urls
                    
                    # Process user-provided selectors
                    for field_name, selector in (selectors.items() if selectors else []):
                        try:
                            is_xpath_sel = (selector.startswith('/') or 
                                          selector.startswith('//') or 
                                          selector.startswith('xpath:') or
                                          selector.startswith('XPath:'))
                            
                            if is_xpath_sel:
                                if selector.startswith('xpath:') or selector.startswith('XPath:'):
                                    selector = selector.split(':', 1)[1].strip()
                                elements = lxml_tree.xpath(selector)
                                if elements:
                                    if len(elements) == 1:
                                        elem = elements[0]
                                        if hasattr(elem, 'text_content'):
                                            extracted_data[field_name] = elem.text_content().strip()
                                        else:
                                            extracted_data[field_name] = str(elem).strip()
                                    else:
                                        extracted_data[field_name] = [elem.text_content().strip() if hasattr(elem, 'text_content') else str(elem).strip() for elem in elements]
                            else:
                                elements = soup.select(selector)
                                if elements:
                                    if len(elements) == 1:
                                        extracted_data[field_name] = elements[0].get_text(strip=True)
                                    else:
                                        extracted_data[field_name] = [elem.get_text(strip=True) for elem in elements]
                        except Exception as e:
                            if settings.DEBUG:
                                print(f"Error extracting {field_name}: {e}")
                    
                    # Automatically extract predefined fields
                    predefined_fields = ['Company Name', 'Homepage URL', 'Email', 'Phone', 'Contact Page URL']
                    for field_name in predefined_fields:
                        if field_name not in extracted_data or extracted_data[field_name] is None:
                            auto_value = extract_predefined_field_bulk(field_name, soup, url)
                            extracted_data[field_name] = auto_value
                    
                    # Extract social media URLs by platform
                    social_platforms = extract_social_media_by_platform_bulk(soup, url)
                    for platform, platform_url in social_platforms.items():
                        extracted_data[platform] = platform_url
                    
                    # Add URL to results
                    extracted_data['_url'] = url
                    
                    if settings.DEBUG:
                        print(f"[Bulk Scrape] Completed URL {idx + 1}/{len(normalized_urls)}: {url} - Success")
                    all_results.append({
                        'url': url,
                        'success': True,
                        'data': extracted_data,
                        'status_code': response_status
                    })
                    completed += 1
                else:
                    all_results.append({
                        'url': url,
                        'success': False,
                        'error': f'HTTP {response_status}' if response_status else 'Unknown error',
                        'status_code': response_status
                    })
                    failed += 1
                
                # Update progress after each URL
                request_id_str = str(request_id)
                progress_data = {
                    'total': len(normalized_urls),
                    'completed': completed,
                    'failed': failed,
                    'current_url': None if idx == len(normalized_urls) - 1 else normalized_urls[idx + 1] if idx + 1 < len(normalized_urls) else None,
                    'current_index': idx + 1,
                    'status': 'processing',
                    'message': f'Processed {idx + 1}/{len(normalized_urls)} URLs'
                }
                try:
                    cache.set(f'bulk_scrape_progress_{request_id_str}', progress_data, timeout=7200)
                    # Verify cache was set
                    verify = cache.get(f'bulk_scrape_progress_{request_id_str}')
                    if not verify and (idx + 1) % 10 == 0:
                        print(f"[Bulk Scrape Thread] WARNING: Cache not persisting for request {request_id}", flush=True)
                except Exception as cache_err:
                    print(f"[Bulk Scrape Thread] Cache error: {cache_err}", flush=True)
                
                # Update database after every URL for real-time progress
                # Use bulk update to avoid loading the object each time
                try:
                    BulkWebScrapingRequest.objects.filter(id=request_id).update(
                        completed_urls=completed,
                        failed_urls=failed
                    )
                    if (idx + 1) % 10 == 0:  # Only log every 10th update to reduce noise
                        print(f"[Bulk Scrape Thread] Updated DB: completed={completed}, failed={failed}", flush=True)
                except Exception as db_error:
                    print(f"[Bulk Scrape Thread] Error updating DB: {db_error}", flush=True)
                
                # Wait between URLs (processing delay)
                if delay_between_urls > 0 and idx < len(normalized_urls) - 1:
                    time.sleep(delay_between_urls)
                    
            except Exception as e:
                all_results.append({
                    'url': url,
                    'success': False,
                    'error': str(e)
                })
                failed += 1
                # Update database immediately when URL fails
                try:
                    BulkWebScrapingRequest.objects.filter(id=request_id).update(
                        completed_urls=completed,
                        failed_urls=failed
                    )
                except Exception as db_error:
                    print(f"[Bulk Scrape Thread] Error updating DB after exception: {db_error}", flush=True)
                if settings.DEBUG:
                    print(f"[Bulk Scrape] Error scraping URL {idx + 1}/{len(normalized_urls)}: {url} - {e}")
                    import traceback
                    traceback.print_exc()
        
        # Update bulk request with final results
        print(f"[Bulk Scrape Thread] Saving final results: completed={completed}, failed={failed}, total_results={len(all_results)}", flush=True)
        bulk_request.completed_urls = completed
        bulk_request.failed_urls = failed
        bulk_request.results = all_results
        bulk_request.status = 'completed' if completed > 0 else 'failed'
        bulk_request.completed_at = timezone.now()
        bulk_request.save()
        print(f"[Bulk Scrape Thread] Final results saved to database", flush=True)
        
        # Update final progress
        request_id_str = str(request_id)
        cache.set(f'bulk_scrape_progress_{request_id_str}', {
            'total': len(normalized_urls),
            'completed': completed,
            'failed': failed,
            'current_url': None,
            'status': 'completed',
            'message': f'Completed: {completed} successful, {failed} failed'
        }, timeout=7200)
        
        if settings.DEBUG:
            print(f"[Bulk Scrape Thread] Completed request ID {request_id}: {completed} successful, {failed} failed", flush=True)
            
    except Exception as e:
        # Try to import Django components for error handling
        try:
            from django.db import connections
            from django.core.cache import cache
            from django.conf import settings
            from .models import BulkWebScrapingRequest
            from django.utils import timezone
            
            connections.close_all()
            
            print(f"[Bulk Scrape Thread] Error in request ID {request_id}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            
            # Update status to failed
            try:
                bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
                bulk_request.status = 'failed'
                bulk_request.error_message = str(e)
                bulk_request.completed_at = timezone.now()
                bulk_request.save()
                
                request_id_str = str(request_id)
                cache.set(f'bulk_scrape_progress_{request_id_str}', {
                    'total': len(normalized_urls) if normalized_urls else 0,
                    'completed': completed,
                    'failed': failed,
                    'current_url': None,
                    'status': 'failed',
                    'message': f'Error: {str(e)}'
                }, timeout=7200)
            except Exception as save_error:
                print(f"[Bulk Scrape Thread] Error saving failed status: {save_error}", flush=True)
                import traceback
                traceback.print_exc()
        except Exception as import_error:
            # If we can't even import Django, just print to stderr
            import sys
            print(f"[Bulk Scrape Thread] CRITICAL: Cannot import Django. Error: {e}, Import error: {import_error}", file=sys.stderr, flush=True)


@csrf_exempt
@require_http_methods(["POST"])
def web_scrape_bulk(request):
    """
    Bulk web scraping endpoint.
    Accepts JSON or multipart/form-data with:
    - urls: List of URLs to scrape (JSON only, legacy)
    - urls_text: Text area with URLs (one per line)
    - urls_file: File upload (CSV/TXT with URLs, one per line)
    - name: Optional name for the request
    - selectors: Dict of field_name -> CSS selector/XPath
    - method: 'beautifulsoup', 'css', 'xpath', 'selenium'
    - headers: Optional custom headers
    - user_agent: Optional custom user agent
    - wait_time: Optional wait time in seconds before scraping each page
    - delay_between_urls: Optional delay in seconds between processing URLs
    - get_results: Optional boolean - if True, return results for existing request_id
    - request_id: Optional - if get_results is True, return results for this request
    """
    try:
        # Check content type to handle both JSON and multipart/form-data
        content_type = request.content_type or ''
        
        if 'multipart/form-data' in content_type or 'application/x-www-form-urlencoded' in content_type:
            # Handle file upload
            urls_text = request.POST.get('urls_text', '')
            urls_file = request.FILES.get('urls_file', None)
            name = request.POST.get('name', '')
            selectors_str = request.POST.get('selectors', '{}')
            method = request.POST.get('method', 'beautifulsoup')
            headers_str = request.POST.get('headers', '{}')
            user_agent = request.POST.get('user_agent', '')
            wait_time = float(request.POST.get('wait_time', 0))
            delay_between_urls = float(request.POST.get('delay_between_urls', 0))
            
            # Parse JSON fields
            try:
                selectors = json.loads(selectors_str) if selectors_str else {}
            except json.JSONDecodeError:
                selectors = {}
            
            try:
                headers = json.loads(headers_str) if headers_str else {}
            except json.JSONDecodeError:
                headers = {}
            
            # Check if this is a request to get results
            get_results = request.POST.get('get_results', '').lower() == 'true'
            if get_results:
                request_id = request.POST.get('request_id')
                if not request_id:
                    return JsonResponse({'error': 'request_id is required when get_results is True'}, status=400)
                
                try:
                    bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
                    return JsonResponse({
                        'success': True,
                        'request_id': bulk_request.id,
                        'total_urls': bulk_request.total_urls,
                        'completed': bulk_request.completed_urls,
                        'failed': bulk_request.failed_urls,
                        'status': bulk_request.status,
                        'results': bulk_request.results if bulk_request.results else []
                    })
                except BulkWebScrapingRequest.DoesNotExist:
                    return JsonResponse({'error': 'Request not found'}, status=404)
            
            # Create bulk scraping request with file/text input
            bulk_request = BulkWebScrapingRequest.objects.create(
                urls_text=urls_text,
                urls_file=urls_file,
                name=name,
                selectors=selectors,
                method=method,
                headers=headers,
                user_agent=user_agent,
                wait_time=wait_time,
                status='pending'
            )
            
            # Extract URLs from text/file
            urls = bulk_request.get_url_list()
            
        else:
            # Handle JSON request (legacy format)
            body = json.loads(request.body)
            
            # Check if this is a request to get results
            if body.get('get_results'):
                request_id = body.get('request_id')
                if not request_id:
                    return JsonResponse({'error': 'request_id is required when get_results is True'}, status=400)
                
                try:
                    bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
                    return JsonResponse({
                        'success': True,
                        'request_id': bulk_request.id,
                        'total_urls': bulk_request.total_urls,
                        'completed': bulk_request.completed_urls,
                        'failed': bulk_request.failed_urls,
                        'status': bulk_request.status,
                        'results': bulk_request.results if bulk_request.results else []
                    })
                except BulkWebScrapingRequest.DoesNotExist:
                    return JsonResponse({'error': 'Request not found'}, status=404)
            
            # Legacy JSON format
            urls = body.get('urls', [])
            urls_text = body.get('urls_text', '')
            name = body.get('name', '')
            selectors = body.get('selectors', {})
            method = body.get('method', 'beautifulsoup')
            headers = body.get('headers', {})
            user_agent = body.get('user_agent', '')
            wait_time = body.get('wait_time', 0)
            delay_between_urls = body.get('delay_between_urls', 0)
            
            # Create bulk scraping request
            bulk_request = BulkWebScrapingRequest.objects.create(
                urls=urls if urls else None,  # Legacy field
                urls_text=urls_text,
                name=name,
                selectors=selectors,
                method=method,
                headers=headers,
                user_agent=user_agent,
                wait_time=wait_time,
                status='pending'
            )
            
            # Extract URLs from all sources
            urls = bulk_request.get_url_list()
        
        # Validate URLs
        if not urls:
            bulk_request.status = 'failed'
            bulk_request.error_message = 'No valid URLs found in text or file'
            bulk_request.save()
            return JsonResponse({'error': 'No valid URLs found in text or file'}, status=400)
        
        # Normalize all URLs
        normalized_urls = []
        for url in urls:
            normalized = normalize_url(url)
            if normalized:
                normalized_urls.append(normalized)
            elif settings.DEBUG:
                print(f"Skipping invalid URL: {url}")
        
        if not normalized_urls:
            bulk_request.status = 'failed'
            bulk_request.error_message = 'No valid URLs found after normalization'
            bulk_request.save()
            return JsonResponse({'error': 'No valid URLs found after normalization'}, status=400)
        
        # Update bulk request with normalized URLs and total count
        bulk_request.total_urls = len(normalized_urls)
        bulk_request.status = 'processing'
        bulk_request.save()
        
        # Store request ID in cache for progress tracking (use integer for consistency)
        request_id = bulk_request.id
        request_id_str = str(request_id)
        
        # Initialize cache immediately
        cache.set(f'bulk_scrape_progress_{request_id_str}', {
            'total': len(normalized_urls),
            'completed': 0,
            'failed': 0,
            'current_url': None,
            'status': 'processing',
            'message': 'Starting bulk scraping...'
        }, timeout=7200)  # 2 hour timeout
        
        if settings.DEBUG:
            print(f"[Bulk Scrape] Starting bulk request ID {request_id} with {len(normalized_urls)} URLs", flush=True)
        
        # Start background thread to process URLs
        try:
            print(f"[Bulk Scrape] About to start thread for request ID {request_id}", flush=True)
            
            thread = threading.Thread(
                target=process_bulk_urls,
                args=(request_id, normalized_urls, selectors, method, headers, user_agent, wait_time, delay_between_urls),
                daemon=False,  # Changed to False so thread doesn't die when main thread exits
                name=f"BulkScrape-{request_id}"
            )
            thread.start()
            
            print(f"[Bulk Scrape] Background thread started for request ID {request_id} (thread name: {thread.name}, alive: {thread.is_alive()})", flush=True)
            
            # Wait a bit longer to ensure thread starts and initializes cache
            import time
            time.sleep(1.0)  # Increased wait time
            
            # Verify cache was set by thread
            progress_check = cache.get(f'bulk_scrape_progress_{request_id_str}')
            print(f"[Bulk Scrape] Cache check after thread start: {progress_check}", flush=True)
            print(f"[Bulk Scrape] Thread still alive: {thread.is_alive()}", flush=True)
            
        except Exception as e:
            if settings.DEBUG:
                print(f"[Bulk Scrape] Error starting thread: {e}", flush=True)
                import traceback
                traceback.print_exc()
            # Update status to failed
            bulk_request.status = 'failed'
            bulk_request.error_message = f"Failed to start background thread: {str(e)}"
            bulk_request.save()
            return JsonResponse({
                'error': f'Failed to start background processing: {str(e)}'
            }, status=500)
        
        # Return immediately with request_id (as string for JSON)
        return JsonResponse({
            'success': True,
            'request_id': request_id_str,
            'total_urls': len(normalized_urls),
            'message': 'Bulk scraping started. Use request_id to poll for progress.'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
def web_scrape_progress(request):
    """Get progress of bulk scraping request"""
    # Handle CORS preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = HttpResponse()
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        response['Access-Control-Max-Age'] = '86400'
        return response
    
    # Only allow GET requests for actual data
    if request.method != 'GET':
        response = JsonResponse({'error': 'Method not allowed'}, status=405)
        response['Access-Control-Allow-Origin'] = '*'
        return response
    
    try:
        request_id = request.GET.get('request_id')
        if not request_id:
            response = JsonResponse({'error': 'request_id is required'}, status=400)
            response['Access-Control-Allow-Origin'] = '*'
            return response
        
        # Convert to integer
        try:
            request_id = int(request_id)
        except (ValueError, TypeError):
            response = JsonResponse({'error': 'Invalid request_id format'}, status=400)
            response['Access-Control-Allow-Origin'] = '*'
            return response
        
        # Always use database as source of truth (cache doesn't work across threads with LocMemCache)
        try:
            bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
            total_processed = bulk_request.completed_urls + bulk_request.failed_urls
            progress = {
                'total': bulk_request.total_urls,
                'completed': bulk_request.completed_urls,
                'failed': bulk_request.failed_urls,
                'status': bulk_request.status,
                'current_url': None,
                'current_index': total_processed,
                'message': f'Processing: {total_processed}/{bulk_request.total_urls} URLs'
            }
            
            # If completed, include results
            if bulk_request.status in ['completed', 'failed']:
                if bulk_request.results:
                    progress['results_available'] = True
                progress['message'] = f'Completed: {bulk_request.completed_urls} successful, {bulk_request.failed_urls} failed'
            
            response_data = {
                'success': True,
                'progress': progress
            }
            response = JsonResponse(response_data)
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type'
            return response
        except BulkWebScrapingRequest.DoesNotExist:
            response = JsonResponse({'error': 'Request not found'}, status=404)
            response['Access-Control-Allow-Origin'] = '*'
            return response
        except Exception as e:
            if settings.DEBUG:
                import traceback
                traceback.print_exc()
            response = JsonResponse({'error': f'Database error: {str(e)}'}, status=500)
            response['Access-Control-Allow-Origin'] = '*'
            return response
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        response = JsonResponse({'error': f'Server error: {str(e)}'}, status=500)
        response['Access-Control-Allow-Origin'] = '*'
        return response


@csrf_exempt
@require_http_methods(["GET"])
def web_scrape_bulk_results(request):
    """Get results of a completed bulk scraping request"""
    request_id = request.GET.get('request_id')
    if not request_id:
        return JsonResponse({'error': 'request_id is required'}, status=400)
    
    try:
        bulk_request = BulkWebScrapingRequest.objects.get(id=request_id)
        
        return JsonResponse({
            'success': True,
            'request_id': bulk_request.id,
            'total_urls': bulk_request.total_urls,
            'completed': bulk_request.completed_urls,
            'failed': bulk_request.failed_urls,
            'status': bulk_request.status,
            'results': bulk_request.results if bulk_request.results else []
        })
    except BulkWebScrapingRequest.DoesNotExist:
        return JsonResponse({'error': 'Request not found'}, status=404)


def get_scraping_history(request):
    """Get scraping request history"""
    limit = int(request.GET.get('limit', 10))
    requests = ScrapingRequest.objects.all()[:limit]
    
    data = []
    for req in requests:
        data.append({
            'id': req.id,
            'url': req.url,
            'method': req.method,
            'status_code': req.status_code,
            'created_at': req.created_at.isoformat(),
            'completed_at': req.completed_at.isoformat() if req.completed_at else None,
            'has_error': bool(req.error_message),
        })
    
    return JsonResponse({
        'requests': data
    })


@csrf_exempt
@require_http_methods(["GET"])
def get_scraping_progress(request):
    """
    Get real-time progress of a scraping job.
    """
    job_id = request.GET.get('job_id')
    if not job_id:
        return JsonResponse({'error': 'job_id is required'}, status=400)
    
    progress = cache.get(f'scraping_progress_{job_id}')
    if progress is None:
        return JsonResponse({'error': 'Job not found or expired'}, status=404)
    
    return JsonResponse(progress)


@csrf_exempt
@require_http_methods(["POST"])
def scrape_paginated(request):
    """
    Scrape multiple pages automatically.
    Detects pagination from response and scrapes all pages.
    """
    try:
        body = json.loads(request.body)
        
        api_url = body.get('url')
        method = body.get('method', 'POST').upper()
        request_data = body.get('data', {})
        headers = body.get('headers', {})
        fields = body.get('fields')  # Optional list of fields to keep
        
        # Validate and normalize fields
        if fields is None:
            fields = []
        elif isinstance(fields, str):
            # If fields is a string, split it
            fields = [f.strip() for f in fields.split(',') if f.strip()]
        elif not isinstance(fields, list):
            fields = []
        else:
            # Ensure all fields are strings and trimmed, filter out empty strings
            fields = [f.strip() if isinstance(f, str) else str(f).strip() for f in fields if f and str(f).strip()]
        
        if settings.DEBUG:
            print(f"[scrape_paginated] Fields received (raw): {body.get('fields')}")
            print(f"[scrape_paginated] Fields after normalization: {fields}")
            print(f"[scrape_paginated] Fields type: {type(fields)}, length: {len(fields) if isinstance(fields, list) else 'N/A'}")
        
        # Always scrape all pages - no limit
        max_pages = None
        
        if not api_url:
            return JsonResponse({'error': 'URL is required'}, status=400)
        
        # Generate unique job ID for progress tracking
        job_id = str(uuid.uuid4())
        
        # Initialize progress tracking
        progress = {
            'job_id': job_id,
            'status': 'running',
            'current_page': 0,
            'total_pages': None,
            'records_collected': 0,
            'message': 'Starting scraping...',
            'start_time': timezone.now().isoformat()
        }
        cache.set(f'scraping_progress_{job_id}', progress, timeout=3600)  # 1 hour timeout
        
        # Default headers
        default_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        default_headers.update(headers)
        
        all_records = []
        # Track seen record IDs/hashes to prevent duplicates
        seen_record_ids = set()
        total_duplicates = 0
        
        # Helper function to get unique identifier for a record
        def get_record_id(record):
            """Get a unique identifier for a record, using ID field or hash of the record."""
            if isinstance(record, dict):
                # Try common ID field names
                for id_field in ['id', 'exhibitorId', 'exhibitor_id', 'recordId', 'record_id', '_id']:
                    if id_field in record and record[id_field] is not None:
                        return str(record[id_field])
                # If no ID field, create a hash of the sorted record items
                # This ensures same records have same hash
                record_str = json.dumps(record, sort_keys=True, default=str)
                return str(hash(record_str))
            else:
                # For non-dict records, use hash of the string representation
                return str(hash(str(record)))
        
        # Detect pagination parameter names (support both 'current'/'size' and 'pageNumber'/'pageSize')
        if 'pageNumber' in request_data:
            page_param = 'pageNumber'
            size_param = 'pageSize'
        else:
            page_param = 'current'
            size_param = 'size'
        
        # Get initial page number from request data, default to 1
        # Convert to int in case it comes as a string from JSON
        try:
            current_page = int(request_data.get(page_param, request_data.get('current', 1)))
        except (ValueError, TypeError):
            current_page = 1
        
        # Ensure we start from page 1 for pagination
        if current_page < 1:
            current_page = 1
        
        total_pages = None
        # Convert to int in case it comes as a string from JSON
        try:
            page_size = int(request_data.get(size_param, request_data.get('size', 10)))
        except (ValueError, TypeError):
            page_size = 10
        delay_between_requests = body.get('delay', 1.0)  # Increased default to 1 second to avoid rate limiting
        max_retries = 3  # Number of retries for failed requests
        retry_delay = 2.0  # Delay between retries
        
        # Create a deep copy of request_data to preserve all fields (mainProductList, keyword, etc.)
        base_request_data = copy.deepcopy(request_data)
        
        # Safety limit to prevent infinite loops (max 1000 pages)
        max_safety_pages = 1000
        
        while True:
            try:
                # Create a fresh copy for each page to preserve all original fields
                page_data = copy.deepcopy(base_request_data)
                # Update only the page number - preserve all other fields including size
                page_data[page_param] = current_page
                # Ensure size is always set (use from original request or default)
                page_data[size_param] = page_size
                
                # Retry logic for failed requests
                response = None
                last_error = None
                for attempt in range(max_retries):
                    try:
                        if method == 'POST':
                            response = requests.post(
                                api_url,
                                json=page_data,
                                headers=default_headers,
                                timeout=60  # Increased timeout to 60 seconds
                            )
                            break  # Success, exit retry loop
                        elif method == 'GET':
                            response = requests.get(
                                api_url,
                                params=page_data,
                                headers=default_headers,
                                timeout=60  # Increased timeout to 60 seconds
                            )
                            break  # Success, exit retry loop
                        else:
                            return JsonResponse({'error': f'Method {method} not supported for pagination. Use GET or POST.'}, status=400)
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, 
                            requests.exceptions.RequestException) as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            if settings.DEBUG:
                                print(f"Attempt {attempt + 1} failed for page {current_page}: {str(e)}. Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            retry_delay *= 1.5  # Exponential backoff
                        else:
                            # All retries failed
                            if settings.DEBUG:
                                print(f"All {max_retries} attempts failed for page {current_page}")
                            raise
                
                # If we still don't have a response after retries, skip this page and continue
                if response is None:
                    if settings.DEBUG:
                        print(f"Failed to get response for page {current_page} after {max_retries} attempts, skipping...")
                    # Skip this page and continue to next
                    current_page += 1
                    # Reset retry delay for next page
                    retry_delay = 2.0
                    continue
                
                # Process the response
                if response.status_code != 200:
                    if settings.DEBUG:
                        print(f"Non-200 status code {response.status_code} for page {current_page}, skipping...")
                    # Skip this page and continue
                    current_page += 1
                    retry_delay = 2.0
                    continue
                
                try:
                    response_data = response.json()
                except ValueError:
                    return JsonResponse({
                        'error': f'Invalid JSON response from API on page {current_page}',
                        'records_collected': len(all_records),
                        'pages_scraped': current_page - 1
                    }, status=500)
                
                # Check if API returned an error
                # Handle APIs with 'code' field (e.g., Eastfair) or 'success' field (e.g., Messe Frankfurt)
                has_code = 'code' in response_data
                has_success = 'success' in response_data
                
                if (has_code and response_data.get('code') != 200) or (has_success and not response_data.get('success')):
                    # If it's not a success response, break but don't error (might be end of data)
                    if settings.DEBUG:
                        print(f"API returned non-success on page {current_page}: {response_data.get('msg', 'Unknown error')}")
                    break
                
                # Extract records based on common response structures
                records = []
                data_section = response_data.get('data', {})
                result_section = response_data.get('result', {})
                
                # Handle different response structures
                # First check for result.hits (Messe Frankfurt API structure)
                if isinstance(result_section, dict):
                    if 'hits' in result_section:
                        hits = result_section['hits']
                        # Extract exhibitor objects from hits (Messe Frankfurt API structure)
                        # Each hit contains an 'exhibitor' object with the actual data
                        records = []
                        for hit in hits:
                            if isinstance(hit, dict) and 'exhibitor' in hit:
                                # Extract exhibitor object and optionally merge with hit metadata
                                exhibitor = hit['exhibitor'].copy()
                                # Optionally add hit-level metadata if needed
                                # exhibitor['_hit_score'] = hit.get('score')
                                # exhibitor['_hit_jumpLabelId'] = hit.get('jumpLabelId')
                                records.append(exhibitor)
                            else:
                                # If no exhibitor key, use the hit itself
                                records.append(hit)
                        
                        # Get pagination info from metaData
                        meta_data = result_section.get('metaData', {})
                        if total_pages is None and meta_data:
                            try:
                                hits_total = int(meta_data.get('hitsTotal', 0))
                            except (ValueError, TypeError):
                                hits_total = 0
                            try:
                                hits_per_page = int(meta_data.get('hitsPerPage', page_size))
                            except (ValueError, TypeError):
                                hits_per_page = page_size
                            if hits_total > 0 and hits_per_page > 0:
                                total_pages = (hits_total + hits_per_page - 1) // hits_per_page
                            elif hits_total > 0:
                                total_pages = (hits_total + page_size - 1) // page_size
                
                # Then check data section (standard structure)
                if not records and isinstance(data_section, dict):
                    # Check for records in various locations
                    if 'records' in data_section:
                        records = data_section['records']
                    elif 'items' in data_section:
                        records = data_section['items']
                    elif 'results' in data_section:
                        records = data_section['results']
                    elif isinstance(data_section.get('data'), list):
                        records = data_section['data']
                    elif isinstance(data_section.get('content'), list):
                        records = data_section['content']
                    
                    # Get total pages if available (check multiple possible field names)
                    if total_pages is None:
                        if 'totalPages' in data_section:
                            try:
                                total_pages = int(data_section['totalPages'])
                            except (ValueError, TypeError):
                                total_pages = None
                        elif 'total_pages' in data_section:
                            try:
                                total_pages = int(data_section['total_pages'])
                            except (ValueError, TypeError):
                                total_pages = None
                        elif 'pages' in data_section:
                            try:
                                total_pages = int(data_section['pages'])
                            except (ValueError, TypeError):
                                total_pages = None
                        elif 'total' in data_section:
                            try:
                                total = int(data_section['total'])
                            except (ValueError, TypeError):
                                total = 0
                            if total > 0 and page_size > 0:
                                total_pages = (total + page_size - 1) // page_size
                            else:
                                total_pages = 1
                        elif 'totalElements' in data_section:
                            try:
                                total = int(data_section['totalElements'])
                            except (ValueError, TypeError):
                                total = 0
                            if total > 0 and page_size > 0:
                                total_pages = (total + page_size - 1) // page_size
                            else:
                                total_pages = 1
                elif not records and isinstance(data_section, list):
                    records = data_section
                elif not records and isinstance(response_data, list):
                    # Response is directly a list
                    records = response_data
                
                # If no records found, break
                if not records:
                    if settings.DEBUG:
                        print(f"No records found on page {current_page}, stopping pagination")
                    break
                
                # Safety check - if we've processed too many pages without finding total_pages, break
                if current_page > 100 and total_pages is None:
                    if settings.DEBUG:
                        print(f"Processed {current_page} pages without detecting total_pages, stopping for safety")
                    break
                
                # Safety limit - prevent infinite loops
                if current_page > max_safety_pages:
                    if settings.DEBUG:
                        print(f"Reached safety limit of {max_safety_pages} pages")
                    break
                
                # Deduplicate records before adding to all_records
                unique_records = []
                duplicates_count = 0
                for record in records:
                    record_id = get_record_id(record)
                    if record_id not in seen_record_ids:
                        seen_record_ids.add(record_id)
                        unique_records.append(record)
                    else:
                        duplicates_count += 1
                
                total_duplicates += duplicates_count
                
                if duplicates_count > 0 and settings.DEBUG:
                    print(f"Page {current_page}: Skipped {duplicates_count} duplicate records (Total duplicates so far: {total_duplicates})")
                
                # If all records on this page are duplicates, we've likely reached the end
                if len(records) > 0 and duplicates_count == len(records):
                    if settings.DEBUG:
                        print(f"Page {current_page}: All records are duplicates, stopping pagination")
                    break
                
                all_records.extend(unique_records)
                
                # Update progress
                progress['current_page'] = current_page
                progress['total_pages'] = total_pages
                progress['records_collected'] = len(all_records)
                if total_pages:
                    progress['message'] = f'Scraping page {current_page} of {total_pages}... ({len(all_records)} records collected)'
                else:
                    progress['message'] = f'Scraping page {current_page}... ({len(all_records)} records collected)'
                cache.set(f'scraping_progress_{job_id}', progress, timeout=3600)
                
                if settings.DEBUG:
                    print(f"Page {current_page}: Collected {len(records)} records (Total so far: {len(all_records)})")
                    if total_pages:
                        print(f"Total pages detected: {total_pages}")
                
                # Check if we should continue
                if total_pages is not None and current_page >= total_pages:
                    if settings.DEBUG:
                        print(f"Reached total_pages: {total_pages}")
                    break
                if len(records) < page_size:
                    if settings.DEBUG:
                        print(f"Received fewer records than page_size ({len(records)} < {page_size}), last page reached")
                    break
                
                current_page += 1
                
                # Add delay between requests to avoid overwhelming the API
                if delay_between_requests > 0:
                    time.sleep(delay_between_requests)
                
                # Reset retry delay for next page
                retry_delay = 2.0
                
            except Exception as e:
                error_msg = f'Unexpected error on page {current_page}: {str(e)}'
                if settings.DEBUG:
                    import traceback
                    print(f"Exception: {error_msg}")
                    print(traceback.format_exc())
                
                # Update progress with error
                progress['status'] = 'error'
                progress['message'] = f'Error: {error_msg}'
                progress['end_time'] = timezone.now().isoformat()
                cache.set(f'scraping_progress_{job_id}', progress, timeout=3600)
                
                # If we have collected some records, return partial results
                if len(all_records) > 0:
                    pages_scraped = current_page - 1
                    # Filter fields if specified
                    if isinstance(fields, list) and len(fields) > 0:
                        # Normalize fields: if records are exhibitor objects, strip 'exhibitor.' prefix
                        normalized_fields = fields
                        if all_records:
                            first_record = all_records[0] if all_records else {}
                            if isinstance(first_record, dict) and 'id' in first_record and 'name' in first_record and 'exhibitor' not in first_record:
                                normalized_fields = []
                                for field in fields:
                                    field_str = str(field).strip()
                                    if field_str.startswith('exhibitor.'):
                                        normalized_fields.append(field_str[10:])
                                    else:
                                        normalized_fields.append(field_str)
                        all_records = [filter_record_fields(record, normalized_fields) for record in all_records]
                    return JsonResponse({
                        'success': True,
                        'job_id': job_id,
                        'total_records': len(all_records),
                        'duplicates_removed': total_duplicates,
                        'pages_scraped': pages_scraped,
                        'total_pages_detected': total_pages,
                        'records': all_records,
                        'warning': f'Scraping stopped at page {current_page} due to error. Partial results returned.',
                        'last_error': error_msg
                    })
                else:
                    return JsonResponse({
                        'error': error_msg,
                        'job_id': job_id,
                        'records_collected': 0,
                        'pages_scraped': 0
                    }, status=500)
        
        # Calculate pages_scraped correctly
        pages_scraped = current_page - 1 if current_page > 1 else (1 if all_records else 0)
        
        # Filter fields if specified
        if isinstance(fields, list) and len(fields) > 0:
            # Normalize fields: if records are exhibitor objects (extracted from hits),
            # strip 'exhibitor.' prefix from field paths
            normalized_fields = fields
            if all_records:
                first_record = all_records[0] if all_records else {}
                # Check if records are exhibitor objects (have 'id', 'name' but not 'exhibitor' key)
                # This means we extracted exhibitor from hits
                if isinstance(first_record, dict) and 'id' in first_record and 'name' in first_record and 'exhibitor' not in first_record:
                    # Strip 'exhibitor.' prefix from field paths
                    normalized_fields = []
                    for field in fields:
                        field_str = str(field).strip()
                        if field_str.startswith('exhibitor.'):
                            normalized_fields.append(field_str[10:])  # Remove 'exhibitor.' prefix
                        else:
                            normalized_fields.append(field_str)
                    if settings.DEBUG and normalized_fields != fields:
                        print(f"[scrape_paginated] Normalized fields from {fields} to {normalized_fields}")
            
            if settings.DEBUG:
                print(f"[scrape_paginated] Filtering {len(all_records)} records with fields: {normalized_fields}")
                if all_records:
                    sample_keys = list(all_records[0].keys())[:10] if isinstance(all_records[0], dict) else []
                    print(f"[scrape_paginated] Sample record keys (first 10): {sample_keys}")
            all_records = [filter_record_fields(record, normalized_fields) for record in all_records]
            if settings.DEBUG:
                print(f"[scrape_paginated] Filtered {len(all_records)} records to {len(normalized_fields)} fields")
                if all_records:
                    sample_filtered = all_records[0]
                    if isinstance(sample_filtered, dict):
                        filtered_keys = list(sample_filtered.keys())
                        print(f"[scrape_paginated] Sample record after filtering has {len(filtered_keys)} keys: {filtered_keys[:10]}")
        else:
            if settings.DEBUG:
                print(f"[scrape_paginated] No fields specified, returning all data")
        
        # Check if we have too many records (might cause memory issues)
        if len(all_records) > 20000:
            if settings.DEBUG:
                print(f"Warning: Large dataset ({len(all_records)} records)")
        
        result = {
            'success': True,
            'total_records': len(all_records),
            'duplicates_removed': total_duplicates,
            'pages_scraped': pages_scraped,
            'total_pages_detected': total_pages,
            'records': all_records
        }
        
        if settings.DEBUG:
            print(f"Scraping complete: {len(all_records)} unique records from {pages_scraped} pages ({total_duplicates} duplicates removed)")
            print(f"Response size will be approximately {len(json.dumps(result)) / 1024:.2f} KB")
        
        return JsonResponse(result)
        
    except json.JSONDecodeError as e:
        if settings.DEBUG:
            print(f"JSONDecodeError: {str(e)}")
            print(f"Request body: {request.body[:500]}")
        return JsonResponse({
            'error': f'Invalid JSON in request body: {str(e)}'
        }, status=400)
    except KeyError as e:
        if settings.DEBUG:
            import traceback
            print(f"KeyError in scrape_paginated: {str(e)}")
            print(traceback.format_exc())
        return JsonResponse({
            'error': f'Missing required field: {str(e)}'
        }, status=400)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        # Always log error for debugging
        print(f"ERROR in scrape_paginated: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print(error_trace)
        return JsonResponse({
            'error': f'Server error: {str(e)}',
            'error_type': type(e).__name__,
            'traceback': error_trace if settings.DEBUG else None
        }, status=500)


@require_http_methods(["GET"])
def export_data(request):
    """Export scraped data to CSV"""
    request_id = request.GET.get('request_id')
    format_type = request.GET.get('format', 'csv')  # csv or json
    
    if not request_id:
        return JsonResponse({'error': 'request_id is required'}, status=400)
    
    try:
        scraping_request = ScrapingRequest.objects.get(id=request_id)
    except ScrapingRequest.DoesNotExist:
        return JsonResponse({'error': 'Request not found'}, status=404)
    
    if not scraping_request.response_data:
        return JsonResponse({'error': 'No data to export'}, status=400)
    
    response_data = scraping_request.response_data
    
    # Extract records
    records = []
    if 'data' in response_data:
        if 'records' in response_data['data']:
            records = response_data['data']['records']
        elif isinstance(response_data['data'], list):
            records = response_data['data']
    
    if not records:
        return JsonResponse({'error': 'No records found in response'}, status=400)
    
    if format_type == 'json':
        response = HttpResponse(
            json.dumps(records, indent=2, ensure_ascii=False),
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename="scraped_data_{request_id}.json"'
        return response
    
    # CSV export
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="scraped_data_{request_id}.csv"'
    
    if records:
        # Flatten all records and collect all field names
        flattened_records = []
        fieldnames = set()
        
        for record in records:
            flattened = flatten_dict(record)
            flattened_records.append(flattened)
            fieldnames.update(flattened.keys())
        
        fieldnames = sorted(list(fieldnames))
        
        writer = csv.DictWriter(response, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for flattened_record in flattened_records:
            # Ensure all fields are present (fill missing with empty string)
            row = {field: flattened_record.get(field, '') for field in fieldnames}
            writer.writerow(row)
    
    return response


@csrf_exempt
@require_http_methods(["POST"])
def get_available_fields(request):
    """
    Extract all available field paths from a response.
    Accepts JSON with response data or request_id to fetch from database.
    """
    try:
        body = json.loads(request.body)
        
        response_data = body.get('response_data')
        request_id = body.get('request_id')
        
        # If request_id provided, fetch from database
        if request_id:
            try:
                scraping_request = ScrapingRequest.objects.get(id=request_id)
                if scraping_request.response_data:
                    response_data = scraping_request.response_data
                else:
                    return JsonResponse({'error': 'No response data found for this request'}, status=404)
            except ScrapingRequest.DoesNotExist:
                return JsonResponse({'error': 'Request not found'}, status=404)
        
        if not response_data:
            return JsonResponse({'error': 'No response data provided'}, status=400)
        
        # Ensure response_data is a dictionary
        if not isinstance(response_data, dict):
            if settings.DEBUG:
                print(f"response_data is not a dict: {type(response_data)}")
            return JsonResponse({
                'error': 'Response data must be a dictionary',
                'debug': {'response_data_type': type(response_data).__name__}
            }, status=400)
        
        # Extract records from response
        records = []
        data_section = response_data.get('data', {})
        result_section = response_data.get('result', {})
        summary_section = response_data.get('summary', {})
        
        # Handle paginated response structure (summary.all_records or summary.sample_records)
        if isinstance(summary_section, dict):
            if 'all_records' in summary_section and isinstance(summary_section['all_records'], list):
                records = summary_section['all_records']
            elif 'sample_records' in summary_section and isinstance(summary_section['sample_records'], list):
                records = summary_section['sample_records']
        # Handle Messe Frankfurt API structure (result.hits)
        elif isinstance(result_section, dict) and 'hits' in result_section:
            hits = result_section['hits']
            if isinstance(hits, list):
                # Extract exhibitor objects from hits
                for hit in hits:
                    if isinstance(hit, dict) and 'exhibitor' in hit:
                        records.append(hit['exhibitor'])
                    elif isinstance(hit, dict):
                        records.append(hit)
        # Handle nested data.result.hits (if response is wrapped)
        elif isinstance(data_section, dict) and 'result' in data_section:
            nested_result = data_section.get('result', {})
            if isinstance(nested_result, dict) and 'hits' in nested_result:
                hits = nested_result['hits']
                if isinstance(hits, list):
                    for hit in hits:
                        if isinstance(hit, dict) and 'exhibitor' in hit:
                            records.append(hit['exhibitor'])
                        elif isinstance(hit, dict):
                            records.append(hit)
        # Handle standard structure (data.records)
        elif isinstance(data_section, dict) and 'records' in data_section:
            if isinstance(data_section['records'], list):
                records = data_section['records']
        elif isinstance(data_section, list):
            records = data_section
        elif isinstance(response_data, list):
            records = response_data
        
        if not records:
            return JsonResponse({'error': 'No records found in response', 'debug': {
                'has_data_section': bool(data_section),
                'has_result_section': bool(result_section),
                'has_summary_section': bool(summary_section),
                'response_data_type': type(response_data).__name__
            }}, status=400)
        
        # Extract field paths from all records
        all_field_paths = set()
        sample_record = records[0] if records else {}
        
        try:
            if isinstance(sample_record, dict):
                all_field_paths = extract_field_paths(sample_record)
            else:
                if settings.DEBUG:
                    print(f"Sample record is not a dict: {type(sample_record)}")
                return JsonResponse({
                    'error': 'Sample record is not a dictionary',
                    'debug': {
                        'sample_record_type': type(sample_record).__name__,
                        'sample_record': str(sample_record)[:200] if sample_record else None
                    }
                }, status=400)
        except Exception as e:
            if settings.DEBUG:
                import traceback
                print(f"Error extracting field paths: {str(e)}")
                print(traceback.format_exc())
            return JsonResponse({
                'error': f'Error extracting field paths: {str(e)}',
                'debug': {
                    'sample_record_type': type(sample_record).__name__,
                    'error_type': type(e).__name__
                }
            }, status=500)
        
        # Sort fields for better UX
        sorted_fields = sorted(list(all_field_paths))
        
        # Group fields by top-level key for better organization
        field_groups = {}
        for field in sorted_fields:
            top_level = field.split('.')[0] if '.' in field else field
            if top_level not in field_groups:
                field_groups[top_level] = []
            field_groups[top_level].append(field)
        
        return JsonResponse({
            'success': True,
            'total_fields': len(sorted_fields),
            'fields': sorted_fields,
            'field_groups': field_groups,
            'sample_record_keys': list(sample_record.keys())[:20] if isinstance(sample_record, dict) else []
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            print(f"Error in get_available_fields: {str(e)}")
            print(traceback.format_exc())
        return JsonResponse({
            'error': f'Server error: {str(e)}'
        }, status=500)


# ============================================================================
# E-commerce Scraper Endpoints
# ============================================================================

@csrf_exempt
@require_http_methods(["POST"])
def ecommerce_scrape(request):
    """
    Generic e-commerce scraping endpoint.
    Accepts JSON with:
    - urls: List of product URLs or single URL string
    - platform: 'amazon', 'ebay', 'shopify', 'aliexpress', 'etsy', 'other'
    - track_price: Optional boolean to track price history
    """
    try:
        body = json.loads(request.body)
        
        urls_input = body.get('urls')
        platform = body.get('platform', 'other').lower()
        track_price = body.get('track_price', False)
        
        # Validate platform
        if platform not in [choice[0] for choice in EcommercePlatform.choices]:
            return JsonResponse({'error': f'Invalid platform: {platform}'}, status=400)
        
        # Normalize URLs
        if isinstance(urls_input, str):
            urls = [urls_input]
        elif isinstance(urls_input, list):
            urls = urls_input
        else:
            return JsonResponse({'error': 'URLs must be a string or list'}, status=400)
        
        normalized_urls = []
        for url in urls:
            normalized = normalize_url(url)
            if normalized:
                normalized_urls.append(normalized)
        
        if not normalized_urls:
            return JsonResponse({'error': 'No valid URLs found'}, status=400)
        
        # Get custom selectors from request (if provided)
        custom_selectors = body.get('custom_selectors')
        
        # Get listing page options
        max_listing_pages = body.get('max_listing_pages', 1)  # How many pages of listings to scrape
        scrape_individual_products = body.get('scrape_individual_products', False)  # Scrape detail pages too
        
        # Create scraping request
        scraping_request = EcommerceScrapingRequest.objects.create(
            urls='\n'.join(normalized_urls),
            platform=platform,
            custom_selectors=custom_selectors,
            status='processing'
        )
        
        # Scrape products
        products_data = []
        products_created = []
        errors = []
        
        for url in normalized_urls:
            try:
                # Auto-detect platform if not specified (for metadata only)
                detected_platform = get_platform_from_url(url) if platform == 'other' else platform
                
                # Detect if this is a listing page (category, search, tags, collection) or product page
                is_listing = is_listing_page(url)
                
                if is_listing:
                    # This is a listing page - extract multiple products
                    listing_products = scrape_product_listing(
                        url,
                        platform=detected_platform,
                        custom_selectors=custom_selectors,
                        max_pages=max_listing_pages,
                        scrape_individual_products=scrape_individual_products
                    )
                    
                    # Process each product from the listing
                    for product_data in listing_products:
                        if 'error' in product_data:
                            errors.append({'url': url, 'error': product_data['error']})
                            continue
                        
                        # Get product URL (from listing card or detail page)
                        product_url = product_data.get('url') or url
                        
                        # Create or update product in database
                        product, created = Product.objects.update_or_create(
                            product_url=product_url,
                            defaults={
                                'platform': detected_platform,
                                'title': product_data.get('title', 'Unknown Product'),
                                'description': product_data.get('description', ''),
                                'image_url': product_data.get('image_url', ''),
                                'external_id': product_data.get('external_id', ''),
                                'rating': product_data.get('rating'),
                                'review_count': product_data.get('review_count', 0),
                                'specifications': product_data.get('specifications', {}),
                            }
                        )
                        products_created.append(product)
                        
                        # Track price if requested and price is available
                        if track_price and product_data.get('price'):
                            price = product_data['price']
                            if isinstance(price, (int, float, str)):
                                try:
                                    from decimal import Decimal
                                    price_decimal = Decimal(str(price))
                                    PriceHistory.objects.create(
                                        product=product,
                                        price=price_decimal,
                                        currency=product_data.get('currency', 'USD'),
                                        availability=product_data.get('availability', True)
                                    )
                                except Exception as e:
                                    if settings.DEBUG:
                                        print(f"Error creating price history: {e}")
                        
                        products_data.append({
                            'product_id': product.id,
                            'url': product_url,
                            'title': product.title,
                            'price': float(product_data.get('price', 0)) if product_data.get('price') else None,
                            'rating': product_data.get('rating'),
                            'review_count': product_data.get('review_count', 0),
                            'image_url': product_data.get('image_url'),
                        })
                else:
                    # This is a single product page
                    # Use generic scraper for ALL sites (works with any e-commerce site)
                    # Platform-specific functions are optional optimizations
                    # Custom selectors take priority if provided
                    if custom_selectors:
                        # Use custom selectors - works with ANY site
                        product_data = scrape_product_generic(
                            url, 
                            platform=detected_platform,
                            custom_selectors=custom_selectors
                        )
                    elif detected_platform == 'amazon':
                        # Optional: Use optimized Amazon scraper if available
                        product_data = scrape_product_amazon(url)
                    elif detected_platform == 'ebay':
                        # Optional: Use optimized eBay scraper if available
                        product_data = scrape_product_ebay(url)
                    elif detected_platform == 'shopify':
                        # Optional: Use optimized Shopify scraper if available
                        product_data = scrape_product_shopify(url)
                    elif detected_platform == 'aliexpress':
                        # Optional: Use optimized AliExpress scraper if available
                        product_data = scrape_product_aliexpress(url)
                    elif detected_platform == 'etsy':
                        # Optional: Use optimized Etsy scraper if available
                        product_data = scrape_product_etsy(url)
                    elif detected_platform == 'daraz':
                        # Optional: Use optimized Daraz scraper if available
                        product_data = scrape_product_daraz(url)
                    else:
                        # Generic scraper - works with ANY e-commerce site
                        product_data = scrape_product_generic(url, platform=detected_platform)
                    
                    # Check for errors
                    if 'error' in product_data:
                        errors.append({'url': url, 'error': product_data['error']})
                        continue
                    
                    # Create or update product in database
                    product, created = Product.objects.update_or_create(
                        product_url=url,
                        defaults={
                            'platform': detected_platform,
                            'title': product_data.get('title', 'Unknown Product'),
                            'description': product_data.get('description', ''),
                            'image_url': product_data.get('image_url', ''),
                            'external_id': product_data.get('external_id', ''),
                            'rating': product_data.get('rating'),
                            'review_count': product_data.get('review_count', 0),
                            'specifications': product_data.get('specifications', {}),
                        }
                    )
                    products_created.append(product)
                    
                    # Track price if requested and price is available
                    if track_price and product_data.get('price'):
                        price = product_data['price']
                        if isinstance(price, (int, float, str)):
                            try:
                                from decimal import Decimal
                                price_decimal = Decimal(str(price))
                                PriceHistory.objects.create(
                                    product=product,
                                    price=price_decimal,
                                    currency=product_data.get('currency', 'USD'),
                                    availability=product_data.get('availability', True)
                                )
                            except Exception as e:
                                if settings.DEBUG:
                                    print(f"Error creating price history: {e}")
                    
                    products_data.append({
                        'product_id': product.id,
                        'url': url,
                        'title': product.title,
                        'price': float(product_data.get('price', 0)) if product_data.get('price') else None,
                        'rating': product_data.get('rating'),
                        'review_count': product_data.get('review_count', 0),
                        'image_url': product_data.get('image_url'),
                    })
                
            except Exception as e:
                errors.append({'url': url, 'error': str(e)})
                if settings.DEBUG:
                    import traceback
                    print(f"Error scraping {url}: {e}")
                    traceback.print_exc()
        
        # Update scraping request with results
        scraping_request.status = 'completed' if not errors or products_data else 'failed'
        scraping_request.results = {
            'products': products_data,
            'products_count': len(products_data),
            'errors': errors,
            'errors_count': len(errors),
        }
        scraping_request.error_message = f"{len(errors)} errors occurred" if errors else None
        scraping_request.completed_at = timezone.now()
        scraping_request.save()
        
        return JsonResponse({
            'success': True,
            'request_id': scraping_request.id,
            'platform': platform,
            'urls_count': len(normalized_urls),
            'products_scraped': len(products_data),
            'errors_count': len(errors),
            'products': products_data[:10],  # Return first 10 for preview
            'errors': errors[:10] if errors else [],
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ecommerce_scrape_amazon(request):
    """
    Amazon-specific e-commerce scraping endpoint.
    Accepts JSON with:
    - urls: List of Amazon product URLs or single URL string
    - track_price: Optional boolean to track price history
    """
    try:
        # Create a new request object with platform forced to Amazon
        request_body = json.loads(request.body)
        request_body['platform'] = 'amazon'
        request._body = json.dumps(request_body).encode('utf-8')
        return ecommerce_scrape(request)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ecommerce_scrape_ebay(request):
    """
    eBay-specific e-commerce scraping endpoint.
    Accepts JSON with:
    - urls: List of eBay product URLs or single URL string
    - track_price: Optional boolean to track price history
    """
    try:
        # Create a new request object with platform forced to eBay
        request_body = json.loads(request.body)
        request_body['platform'] = 'ebay'
        request._body = json.dumps(request_body).encode('utf-8')
        return ecommerce_scrape(request)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def ecommerce_scrape_progress(request):
    """
    Get progress of e-commerce scraping request.
    Query params:
    - request_id: ID of the scraping request
    """
    try:
        request_id = request.GET.get('request_id')
        if not request_id:
            return JsonResponse({'error': 'request_id is required'}, status=400)
        
        try:
            scraping_request = EcommerceScrapingRequest.objects.get(id=request_id)
            return JsonResponse({
                'success': True,
                'request_id': scraping_request.id,
                'platform': scraping_request.platform,
                'status': scraping_request.status,
                'created_at': scraping_request.created_at.isoformat(),
                'completed_at': scraping_request.completed_at.isoformat() if scraping_request.completed_at else None,
                'error_message': scraping_request.error_message
            })
        except EcommerceScrapingRequest.DoesNotExist:
            return JsonResponse({'error': 'Request not found'}, status=404)
            
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ecommerce_price_track(request):
    """
    Track price for a product.
    Accepts JSON with:
    - product_id: ID of the product to track
    - url: Product URL (if product doesn't exist, will create it)
    - platform: Platform name
    """
    try:
        body = json.loads(request.body)
        
        product_id = body.get('product_id')
        url = body.get('url')
        platform = body.get('platform', 'other').lower()
        
        if not product_id and not url:
            return JsonResponse({'error': 'Either product_id or url is required'}, status=400)
        
        # Get or create product
        if product_id:
            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                return JsonResponse({'error': 'Product not found'}, status=404)
        else:
            # Create product from URL
            url = normalize_url(url)
            if not url:
                return JsonResponse({'error': 'Invalid URL'}, status=400)
            
            product, created = Product.objects.get_or_create(
                product_url=url,
                defaults={
                    'platform': platform,
                    'title': 'Product (to be scraped)',
                }
            )
        
        # Scrape current price
        platform = product.platform or get_platform_from_url(product.product_url)
        
        # Get custom selectors from request if provided
        custom_selectors = body.get('custom_selectors')
        
        # Use generic scraper (works with any site)
        # Platform-specific functions are optional optimizations
        if custom_selectors:
            # Use custom selectors - works with ANY site
            product_data = scrape_product_generic(
                product.product_url,
                platform=platform,
                custom_selectors=custom_selectors
            )
        elif platform == 'amazon':
            product_data = scrape_product_amazon(product.product_url)
        elif platform == 'ebay':
            product_data = scrape_product_ebay(product.product_url)
        elif platform == 'shopify':
            product_data = scrape_product_shopify(product.product_url)
        elif platform == 'aliexpress':
            product_data = scrape_product_aliexpress(product.product_url)
        elif platform == 'etsy':
            product_data = scrape_product_etsy(product.product_url)
        elif platform == 'daraz':
            product_data = scrape_product_daraz(product.product_url)
        else:
            # Generic scraper - works with ANY e-commerce site
            product_data = scrape_product_generic(product.product_url, platform=platform)
        
        # Extract price
        if 'error' in product_data:
            return JsonResponse({
                'error': f'Failed to scrape price: {product_data["error"]}'
            }, status=500)
        
        price = product_data.get('price')
        if not price:
            return JsonResponse({
                'error': 'Price not found on product page'
            }, status=404)
        
        # Convert price to Decimal
        from decimal import Decimal
        try:
            price_decimal = Decimal(str(price))
        except:
            return JsonResponse({
                'error': f'Invalid price format: {price}'
            }, status=400)
        
        # Create price history entry
        price_entry = PriceHistory.objects.create(
            product=product,
            price=price_decimal,
            currency=product_data.get('currency', 'USD'),
            availability=product_data.get('availability', True)
        )
        
        # Update product with latest price info
        if product_data.get('rating'):
            product.rating = product_data.get('rating')
        if product_data.get('review_count'):
            product.review_count = product_data.get('review_count', 0)
        product.save()
        
        return JsonResponse({
            'success': True,
            'product_id': product.id,
            'price_entry_id': price_entry.id,
            'price': float(price_decimal),
            'currency': price_entry.currency,
            'availability': price_entry.availability,
            'scraped_at': price_entry.scraped_at.isoformat()
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        if settings.DEBUG:
            import traceback
            traceback.print_exc()
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def ecommerce_price_history(request):
    """
    Get price history for a product.
    Query params:
    - product_id: ID of the product
    - limit: Optional limit on number of records (default: 100)
    """
    try:
        product_id = request.GET.get('product_id')
        if not product_id:
            return JsonResponse({'error': 'product_id is required'}, status=400)
        
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return JsonResponse({'error': 'Product not found'}, status=404)
        
        limit = int(request.GET.get('limit', 100))
        price_history = PriceHistory.objects.filter(product=product).order_by('-scraped_at')[:limit]
        
        history_data = [{
            'id': entry.id,
            'price': float(entry.price),
            'currency': entry.currency,
            'availability': entry.availability,
            'scraped_at': entry.scraped_at.isoformat()
        } for entry in price_history]
        
        return JsonResponse({
            'success': True,
            'product_id': product.id,
            'product_title': product.title,
            'platform': product.platform,
            'price_history': history_data,
            'count': len(history_data)
        })
        
    except ValueError:
        return JsonResponse({'error': 'Invalid limit parameter'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


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
        from urllib.parse import urljoin, urlparse, quote
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Replace relative URLs with absolute URLs
        import re
        
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
        from django.http import HttpResponse
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

