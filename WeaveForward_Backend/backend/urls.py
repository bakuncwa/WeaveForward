from django.urls import path
from . import views
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout/', views.LogoutView.as_view(), name='token_blacklist'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('location/lookup/', views.lookup_location, name='location_lookup'),
]
