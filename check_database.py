"""
Check database records created by tests
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scrapehub.settings')
django.setup()

from scrapers.ecommerce_scraper.models import Product, PriceHistory, EcommerceScrapingRequest

print("=" * 60)
print("Database Records Check")
print("=" * 60)

print(f"\nProducts: {Product.objects.count()}")
print(f"Price History Entries: {PriceHistory.objects.count()}")
print(f"Scraping Requests: {EcommerceScrapingRequest.objects.count()}")

if Product.objects.exists():
    print("\n" + "-" * 60)
    print("Products:")
    print("-" * 60)
    for product in Product.objects.all()[:5]:
        print(f"\nID: {product.id}")
        print(f"  Title: {product.title[:80]}")
        print(f"  Platform: {product.platform}")
        print(f"  URL: {product.product_url[:80]}")
        print(f"  Rating: {product.rating}")
        print(f"  Reviews: {product.review_count}")
        print(f"  Created: {product.created_at}")

if EcommerceScrapingRequest.objects.exists():
    print("\n" + "-" * 60)
    print("Scraping Requests:")
    print("-" * 60)
    for req in EcommerceScrapingRequest.objects.all()[:3]:
        print(f"\nID: {req.id}")
        print(f"  Platform: {req.platform}")
        print(f"  Status: {req.status}")
        print(f"  Created: {req.created_at}")
        if req.results:
            print(f"  Products Scraped: {req.results.get('products_count', 0)}")
            print(f"  Errors: {req.results.get('errors_count', 0)}")

if PriceHistory.objects.exists():
    print("\n" + "-" * 60)
    print("Price History:")
    print("-" * 60)
    for price in PriceHistory.objects.all()[:5]:
        print(f"\nID: {price.id}")
        print(f"  Product: {price.product.title[:50]}")
        print(f"  Price: ${price.price} {price.currency}")
        print(f"  Availability: {price.availability}")
        print(f"  Scraped: {price.scraped_at}")

print("\n" + "=" * 60)

