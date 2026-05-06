from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('location/lookup/', views.lookup_location, name='location_lookup'),
]
