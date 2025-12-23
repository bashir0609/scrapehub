from django.shortcuts import render

def index(request):
    """Render the others/directory page"""
    return render(request, 'others.html', {
        'page_title': 'All Scrapers & Tools',
        'page_description': 'Explore all available scraping tools'
    })
