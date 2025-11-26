"""
Configuration for E-commerce Scraper
Anti-bot measures and platform-specific settings
"""

# Anti-bot configuration
ANTI_BOT_CONFIG = {
    'use_stealth': True,  # Use undetected-chromedriver or playwright-stealth
    'use_proxy': False,  # Enable proxy rotation
    'proxy_list': [],  # List of proxy servers (format: 'http://user:pass@host:port')
    'user_agent_rotation': True,  # Rotate user agents
    'random_delays': True,  # Add random delays between requests
    'min_delay': 2,  # Minimum delay in seconds
    'max_delay': 5,  # Maximum delay in seconds
    'respect_robots_txt': True,  # Check robots.txt before scraping
}

# Platform-specific configurations
PLATFORM_CONFIGS = {
    'amazon': {
        'requires_stealth': True,
        'requires_proxy': True,  # Highly recommended
        'rate_limit': 1,  # Requests per second
        'headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'selectors': {
            # Single product page selectors
            'title': '#productTitle',
            'price': '.a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice',
            'rating': '#acrPopover .a-icon-alt',
            'review_count': '#acrCustomerReviewText',
            'description': '#productDescription, #feature-bullets',
            'images': '#landingImage, #imgBlkFront',
            # Listing page selectors (category, search, etc.)
            'product_card': '[data-component-type="s-search-result"], .s-result-item',
            'product_link': 'h2 a.a-link-normal, .s-result-item h2 a',
            'product_title_listing': 'h2 span, .s-result-item h2',
            'product_price_listing': '.a-price .a-offscreen, .a-price-whole',
            'product_image_listing': '.s-image',
            'pagination_next': '.a-pagination .a-last a',
        }
    },
    'ebay': {
        'requires_stealth': True,
        'requires_proxy': False,
        'rate_limit': 2,
        'headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
        'selectors': {
            'title': '#x-item-title-label',
            'price': '.notranslate',
            'rating': '.ebay-review-item-rating',
            'description': '#viTabs_0_is',
            'images': '#icImg',
        }
    },
    'shopify': {
        'requires_stealth': False,
        'requires_proxy': False,
        'rate_limit': 5,
        'selectors': {
            # Single product page selectors
            'title': 'h1.product-title',
            'price': '.product-price',
            'description': '.product-description',
            'images': '.product-image img',
            # Listing page selectors
            'product_card': '.product-item, .grid-product, [class*="product-card"]',
            'product_link': '.product-item a, .grid-product a, [class*="product-card"] a',
            'product_title_listing': '.product-title, .grid-product-title, [class*="product-title"]',
            'product_price_listing': '.product-price, .price, [class*="price"]',
            'product_image_listing': '.product-image img, .grid-product-image img',
            'pagination_next': '.pagination .next, .pagination-next, a[rel="next"]',
        }
    },
    'aliexpress': {
        'requires_stealth': True,
        'requires_proxy': True,
        'rate_limit': 1,
        'selectors': {
            'title': '.product-title-text',
            'price': '.notranslate',
            'rating': '.overview-rating-average',
            'description': '.product-description',
        }
    },
    'etsy': {
        'requires_stealth': False,
        'requires_proxy': False,
        'rate_limit': 3,
        'selectors': {
            'title': 'h1[data-buy-box-listing-title]',
            'price': '.currency-value',
            'rating': '.rating-num',
            'description': '#listing-page-cart .wt-text-body-01',
        }
    },
    'daraz': {
        'requires_stealth': True,
        'requires_proxy': False,
        'rate_limit': 2,
        'headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'selectors': {
            'title': 'h1, [class*="product-name"], [class*="title"]',
            'price': '[class*="price"], [class*="Price"], .price, .Price',
            'rating': '[class*="rating"], [class*="Rating"], .rating, .Rating',
            'review_count': '[class*="review"], [class*="Review"], .review-count',
            'description': '[class*="description"], [class*="Description"], .description',
            'images': 'img[src*="product"], img[src*="Product"], .product-image img, .gallery img',
        }
    },
}

# User-Agent rotation pool
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

