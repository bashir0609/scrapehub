from django.urls import path
from . import views

urlpatterns = [
    path('', views.jobs_list, name='jobs_list'),
    path('<str:job_id>/', views.job_detail, name='job_detail'),
    path('api/<str:job_id>/status/', views.job_status_api, name='job_status_api'),
    path('api/<str:job_id>/pause/', views.pause_job, name='pause_job'),
    path('api/<str:job_id>/resume/', views.resume_job, name='resume_job'),
    path('api/<str:job_id>/stop/', views.stop_job, name='stop_job'),
]
