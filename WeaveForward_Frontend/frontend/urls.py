from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('select-role/', views.role_select, name='role_select'),
    path('register/donor/', views.donor_registration, name='donor_registration'),
    path('register/tuab/', views.tuab_registration, name='tuab_registration'),
    
    # Internal Proxy for Location Lookup
    path('api/location/lookup/', views.location_lookup_proxy, name='location_lookup_proxy'),
]
