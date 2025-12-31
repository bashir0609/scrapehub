import json
import requests
import csv
import time
import copy
import uuid
from urllib.parse import urljoin, urlparse, urlunparse
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from .models import ScrapingRequest

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


def index(request):
    """Home page with Universal API Client interface"""
    return render(request, 'index.html')


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


@csrf_exempt
@require_http_methods(["GET"])
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
