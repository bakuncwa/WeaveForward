from django.urls import path
from . import views

urlpatterns = [
    path('get-city-and-barangay/', views.get_city_and_barangay, name='get_city_and_barangay'),
]
