# writing/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('generate/', views.generate, name='generate'),
    path('generation_history/', views.generation_history, name='generation_history'),
    path('generation_detail/<str:generation_id>/', views.generation_detail, name='generation_detail'),
]