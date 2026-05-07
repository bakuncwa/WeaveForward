from django.urls import path, include
from . import views
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # --- AUTHENTICATION ---
    path('login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout/', views.LogoutView.as_view(), name='token_blacklist'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),

    # --- USER MANAGEMENT ---
    path('users/', views.UserViewSet.as_view({'get': 'list'}), name='user-list'),
    path('users/me/', views.UserViewSet.as_view({'get': 'me'}), name='user-me'),
    path('users/<int:pk>/', views.UserViewSet.as_view({'get': 'retrieve'}), name='user-detail'),

    # --- REGISTRATION & ONBOARDING ---
    path('register/', views.RegisterView.as_view(), name='register'),
    path('location/lookup/', views.lookup_location, name='location_lookup'),

    # --- DONATION MANAGEMENT ---
    path('donations/', views.DonationViewSet.as_view({'get': 'list'}), name='donation-list'),
    path('donations/me/', views.DonationViewSet.as_view({'get': 'me'}), name='donation-me'),
    path('donations/<int:pk>/', views.DonationViewSet.as_view({'get': 'retrieve'}), name='donation-detail'),
]
