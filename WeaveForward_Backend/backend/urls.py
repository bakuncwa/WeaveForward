from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('get-city-and-barangay/', views.get_city_and_barangay, name='get_city_and_barangay'),
]
