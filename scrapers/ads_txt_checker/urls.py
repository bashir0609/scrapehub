from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='ads_txt_checker_index'),
    path('check/', views.check_ads_txt, name='check_ads_txt'),
    path('submit/', views.submit_job, name='submit_job'),
]
