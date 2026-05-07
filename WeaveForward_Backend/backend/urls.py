from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from rest_framework_simplejwt.views import TokenRefreshView

router = DefaultRouter()
router.register(r'donations', views.DonationViewSet, basename='donation')

urlpatterns = [
    path('', include(router.urls)),
    path('login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout/', views.LogoutView.as_view(), name='token_blacklist'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('location/lookup/', views.lookup_location, name='location_lookup'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]
