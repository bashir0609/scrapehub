from django.urls import path
from scrapers import others_views

urlpatterns = [
    path('', others_views.index, name='others'),
]
