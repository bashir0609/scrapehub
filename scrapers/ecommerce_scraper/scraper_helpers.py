"""
Helper functions for E-commerce scraping
Handles platform-specific scraping logic, anti-bot measures, and data extraction
"""

import time
import random
import re
from decimal import Decimal
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import requests
from django.conf import settings

try:
    from fake_useragent import UserAgent
    FAKE_USERAGENT_AVAILABLE = True
except ImportError:
    FAKE_USERAGENT_AVAILABLE = False

from .scraper_config import ANTI_BOT_CONFIG, PLATFORM_CONFIGS, USER_AGENTS


def get_random_user_agent():
    """Get a random user agent"""
    if FAKE_USERAGENT_AVAILABLE:
        try:
            ua = UserAgent()
            return ua.random
        except:
            pass
    return random.choice(USER_AGENTS)


def get_platform_from_url(url):
    """Detect platform from URL"""
    url_lower = url.lower()
    if 'amazon.com' in url_lower or 'amazon.' in url_lower:
        return 'amazon'
    elif 'ebay.com' in url_lower or 'ebay.' in url_lower:
        return 'ebay'
    elif 'shopify' in url_lower:
        return 'shopify'
    elif 'aliexpress.com' in url_lower:
        return 'aliexpress'
    elif 'etsy.com' in url_lower:
        return 'etsy'
    elif 'daraz.com' in url_lower or 'daraz.' in url_lower:
        return 'daraz'
    return 'other'


def extract_amazon_asin(url):
    """Extract ASIN from Amazon URL"""
    # Amazon URLs can have ASIN in different formats
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
        r'ASIN=([A-Z0-9]{10})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_ebay_item_id(url):
    """Extract item ID from eBay URL"""
    # eBay URLs can have item ID in different formats
    patterns = [
        r'/itm/(\d+)',
        r'item=(\d+)',
        r'p=(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_daraz_item_id(url):
    """Extract item ID from Daraz URL"""
    # Daraz URLs typically have item ID in format: -i{ID}-s{SKU}
    patterns = [
        r'-i(\d+)-',
        r'/products/.*-i(\d+)-',
        r'itemId=(\d+)',
        r'item_id=(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def normalize_price(price_text):
    """Extract numeric price from text"""
    if not price_text:
        return None
    
    # Remove currency symbols and extract numbers
    price_text = str(price_text).strip()
    # Remove common currency symbols
    price_text = re.sub(r'[^\d.,]', '', price_text)
    # Replace comma with dot if it's a decimal separator
    if ',' in price_text and '.' in price_text:
        # Determine which is decimal separator
        if price_text.rindex(',') > price_text.rindex('.'):
            price_text = price_text.replace('.', '').replace(',', '.')
        else:
            price_text = price_text.replace(',', '')
    elif ',' in price_text:
        # Could be thousands separator or decimal
        price_text = price_text.replace(',', '.')
    
    try:
        return Decimal(price_text)
    except:
        return None


def extract_rating(rating_text):
    """Extract numeric rating from text"""
    if not rating_text:
        return None
    
    # Look for patterns like "4.5 out of 5", "4.5/5", "4.5 stars", etc.
    patterns = [
        r'(\d+\.?\d*)\s*(?:out of|/)\s*5',
        r'(\d+\.?\d*)\s*stars?',
        r'rating[:\s]*(\d+\.?\d*)',
        r'(\d+\.?\d*)',
    ]
    
    rating_text = str(rating_text).strip()
    for pattern in patterns:
        match = re.search(pattern, rating_text, re.IGNORECASE)
        if match:
            try:
                rating = float(match.group(1))
                if 0 <= rating <= 5:
                    return rating
            except:
                continue
    return None


def extract_review_count(count_text):
    """Extract review count from text"""
    if not count_text:
        return 0
    
    # Look for numbers in text like "1,234 reviews", "5.2K reviews", etc.
    count_text = str(count_text).strip()
    
    # Remove common words
    count_text = re.sub(r'reviews?|ratings?|customers?', '', count_text, flags=re.IGNORECASE)
    count_text = count_text.strip()
    
    # Handle K, M suffixes
    multiplier = 1
    if 'k' in count_text.lower():
        multiplier = 1000
        count_text = count_text.lower().replace('k', '')
    elif 'm' in count_text.lower():
        multiplier = 1000000
        count_text = count_text.lower().replace('m', '')
    
    # Extract numbers
    numbers = re.findall(r'\d+', count_text.replace(',', ''))
    if numbers:
        try:
            return int(float(numbers[0]) * multiplier)
        except:
            return 0
    return 0


def scrape_product_generic(url, platform='other', custom_selectors=None):
    """
    Generic product scraping function using BeautifulSoup.
    Works for ANY e-commerce site - no platform-specific code required.
    
    Args:
        url: Product URL to scrape
        platform: Platform name (for metadata/analytics only)
        custom_selectors: Optional dict of CSS selectors {'title': '...', 'price': '...', etc.}
                         If provided, overrides platform defaults
    """
    try:
        # Use custom selectors if provided, otherwise fall back to platform config
        if custom_selectors:
            selectors = custom_selectors
        else:
            # Get platform config (optional - just for convenience)
            config = PLATFORM_CONFIGS.get(platform, {})
            selectors = config.get('selectors', {})
        
        # Get headers from platform config (if available)
        config = PLATFORM_CONFIGS.get(platform, {})
        headers = config.get('headers', {})
        
        # Prepare headers
        request_headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        request_headers.update(headers)
        
        # Add random delay if configured
        if ANTI_BOT_CONFIG.get('random_delays'):
            delay = random.uniform(
                ANTI_BOT_CONFIG.get('min_delay', 2),
                ANTI_BOT_CONFIG.get('max_delay', 5)
            )
            time.sleep(delay)
        
        # Make request
        response = requests.get(url, headers=request_headers, timeout=30, verify=False)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Extract data using selectors
        product_data = {
            'url': url,
            'platform': platform,
        }
        
        # Title
        if selectors.get('title'):
            title_elem = soup.select_one(selectors['title'])
            if title_elem:
                product_data['title'] = title_elem.get_text(strip=True)
        
        # Price
        if selectors.get('price'):
            price_elem = soup.select_one(selectors['price'])
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                product_data['price'] = normalize_price(price_text)
                product_data['price_text'] = price_text
        
        # Rating
        if selectors.get('rating'):
            rating_elem = soup.select_one(selectors['rating'])
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True)
                product_data['rating'] = extract_rating(rating_text)
        
        # Review count
        if selectors.get('review_count'):
            review_elem = soup.select_one(selectors['review_count'])
            if review_elem:
                review_text = review_elem.get_text(strip=True)
                product_data['review_count'] = extract_review_count(review_text)
        
        # Description
        if selectors.get('description'):
            desc_elem = soup.select_one(selectors['description'])
            if desc_elem:
                product_data['description'] = desc_elem.get_text(strip=True)
        
        # Images
        if selectors.get('images'):
            img_elems = soup.select(selectors['images'])
            images = []
            for img in img_elems:
                img_url = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if img_url:
                    # Make absolute URL
                    if img_url.startswith('//'):
                        img_url = 'https:' + img_url
                    elif img_url.startswith('/'):
                        parsed = urlparse(url)
                        img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
                    images.append(img_url)
            if images:
                product_data['image_url'] = images[0]
                product_data['images'] = images
        
        # Extract external ID
        if platform == 'amazon':
            product_data['external_id'] = extract_amazon_asin(url)
        elif platform == 'ebay':
            product_data['external_id'] = extract_ebay_item_id(url)
        elif platform == 'daraz':
            product_data['external_id'] = extract_daraz_item_id(url)
        
        return product_data
        
    except requests.exceptions.RequestException as e:
        return {'error': f'Request failed: {str(e)}', 'url': url}
    except Exception as e:
        return {'error': f'Scraping failed: {str(e)}', 'url': url}


def scrape_product_amazon(url):
    """Amazon-specific scraping (requires more sophisticated approach)"""
    # For now, use generic scraping
    # TODO: Implement with undetected-chromedriver or playwright-stealth
    return scrape_product_generic(url, platform='amazon')


def scrape_product_ebay(url):
    """eBay-specific scraping"""
    return scrape_product_generic(url, platform='ebay')


def scrape_product_shopify(url):
    """Shopify-specific scraping"""
    return scrape_product_generic(url, platform='shopify')


def scrape_product_aliexpress(url):
    """AliExpress-specific scraping"""
    # AliExpress often requires JavaScript, but try generic first
    return scrape_product_generic(url, platform='aliexpress')


def scrape_product_etsy(url):
    """Etsy-specific scraping"""
    return scrape_product_generic(url, platform='etsy')


def scrape_product_daraz(url):
    """Daraz-specific scraping"""
    return scrape_product_generic(url, platform='daraz')


def is_listing_page(url, soup=None):
    """
    Detect if a URL is a product listing page (category, search, tags, collection)
    vs a single product page.
    
    Args:
        url: URL to check
        soup: Optional BeautifulSoup object (if already parsed)
    
    Returns:
        bool: True if appears to be a listing page
    """
    # Check URL patterns
    listing_patterns = [
        '/category/', '/categories/', '/c/', '/cat/',
        '/search', '/s/', '/q=', '?q=', '&q=',
        '/tag/', '/tags/', '/collection/', '/collections/',
        '/shop/', '/products/', '/browse/',
        '/filter', '/filters', '?page=', '&page=',
    ]
    
    url_lower = url.lower()
    for pattern in listing_patterns:
        if pattern in url_lower:
            return True
    
    # If soup provided, check for multiple product cards
    if soup:
        # Look for common listing page indicators
        listing_indicators = [
            soup.select('[class*="product-card"]'),
            soup.select('[class*="product-item"]'),
            soup.select('[class*="product-grid"]'),
            soup.select('[class*="search-result"]'),
            soup.select('[class*="listing"]'),
        ]
        
        # If we find multiple product cards, it's likely a listing page
        for indicators in listing_indicators:
            if len(indicators) > 1:
                return True
    
    return False


def scrape_product_listing(url, platform='other', custom_selectors=None, max_pages=1, scrape_individual_products=False):
    """
    Scrape product listing page (category, search, tags, collection).
    Extracts multiple products from a single listing URL.
    
    Args:
        url: Listing page URL (category, search, tags, collection, etc.)
        platform: Platform name (for metadata only)
        custom_selectors: Optional dict of CSS selectors
        max_pages: Maximum number of listing pages to scrape (default: 1)
        scrape_individual_products: If True, also scrape each product's detail page
    
    Returns:
        list: List of product data dictionaries
    """
    try:
        # Use custom selectors if provided
        if custom_selectors:
            selectors = custom_selectors
        else:
            config = PLATFORM_CONFIGS.get(platform, {})
            selectors = config.get('selectors', {})
        
        # Get headers
        config = PLATFORM_CONFIGS.get(platform, {})
        headers = config.get('headers', {})
        
        # Prepare headers
        request_headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        request_headers.update(headers)
        
        all_products = []
        current_page = 1
        current_url = url
        
        while current_page <= max_pages:
            # Add random delay between pages
            if ANTI_BOT_CONFIG.get('random_delays') and current_page > 1:
                delay = random.uniform(
                    ANTI_BOT_CONFIG.get('min_delay', 2),
                    ANTI_BOT_CONFIG.get('max_delay', 5)
                )
                time.sleep(delay)
            
            # Make request
            response = requests.get(current_url, headers=request_headers, timeout=30, verify=False)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Get product card selector
            product_card_selector = selectors.get('product_card') or '[class*="product"], [class*="item"]'
            product_cards = soup.select(product_card_selector)
            
            if not product_cards:
                # No products found on this page
                break
            
            # Extract products from cards
            for card in product_cards:
                product_data = {
                    'platform': platform,
                    'source_url': current_url,
                }
                
                # Extract product link
                link_selector = selectors.get('product_link') or 'a'
                link_elem = card.select_one(link_selector)
                if link_elem:
                    product_url = link_elem.get('href') or ''
                    # Make absolute URL
                    if product_url:
                        if product_url.startswith('//'):
                            product_url = 'https:' + product_url
                        elif product_url.startswith('/'):
                            parsed = urlparse(url)
                            product_url = f"{parsed.scheme}://{parsed.netloc}{product_url}"
                        product_data['url'] = product_url
                
                # Extract title from listing card
                title_selector = selectors.get('product_title_listing') or selectors.get('title') or 'h2, h3, [class*="title"]'
                title_elem = card.select_one(title_selector)
                if title_elem:
                    product_data['title'] = title_elem.get_text(strip=True)
                
                # Extract price from listing card
                price_selector = selectors.get('product_price_listing') or selectors.get('price') or '[class*="price"]'
                price_elem = card.select_one(price_selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    product_data['price'] = normalize_price(price_text)
                    product_data['price_text'] = price_text
                
                # Extract image from listing card
                image_selector = selectors.get('product_image_listing') or selectors.get('images') or 'img'
                image_elem = card.select_one(image_selector)
                if image_elem:
                    img_url = image_elem.get('src') or image_elem.get('data-src') or image_elem.get('data-lazy-src')
                    if img_url:
                        # Make absolute URL
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        elif img_url.startswith('/'):
                            parsed = urlparse(url)
                            img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
                        product_data['image_url'] = img_url
                
                # If scrape_individual_products and we have a product URL, scrape the detail page
                if scrape_individual_products and product_data.get('url'):
                    try:
                        detail_data = scrape_product_generic(
                            product_data['url'],
                            platform=platform,
                            custom_selectors=custom_selectors
                        )
                        # Merge detail page data (overwrites listing card data)
                        if 'error' not in detail_data:
                            product_data.update(detail_data)
                    except Exception as e:
                        # Continue with listing card data if detail page fails
                        if settings.DEBUG:
                            print(f"Error scraping product detail {product_data.get('url')}: {e}")
                
                # Only add if we have at least a title or URL
                if product_data.get('title') or product_data.get('url'):
                    all_products.append(product_data)
            
            # Check for next page
            if current_page < max_pages:
                next_selector = selectors.get('pagination_next') or 'a[rel="next"], .pagination .next, .next-page'
                next_link = soup.select_one(next_selector)
                if next_link:
                    next_url = next_link.get('href')
                    if next_url:
                        # Make absolute URL
                        if next_url.startswith('//'):
                            next_url = 'https:' + next_url
                        elif next_url.startswith('/'):
                            parsed = urlparse(url)
                            next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                        current_url = next_url
                        current_page += 1
                    else:
                        break
                else:
                    # No next page found
                    break
            else:
                break
        
        return all_products
        
    except requests.exceptions.RequestException as e:
        return [{'error': f'Request failed: {str(e)}', 'url': url}]
    except Exception as e:
        return [{'error': f'Scraping failed: {str(e)}', 'url': url}]

