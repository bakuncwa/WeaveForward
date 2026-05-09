from django.urls import path
from . import views

urlpatterns = [
    # --- AUTH ---
    path('login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout/', views.LogoutView.as_view(), name='token_blacklist'),
    path('token/refresh/', views.CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('register/', views.RegisterView.as_view(), name='register'),

    # --- USERS ---
    path('users/', views.UserViewSet.as_view({'get': 'list', 'post': 'create'}), name='user-list'),
    path('users/me/', views.UserViewSet.as_view({'get': 'me'}), name='user-me'),
    path('users/me/2fa/setup/', views.TwoFactorSetupView.as_view(), name='user-2fa-setup'),
    path('users/<int:pk>/2fa/', views.TwoFactorView.as_view(), name='user-2fa-detail'),
    path('users/<int:pk>/', views.UserViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='user-detail'),

    # --- LOCATIONS ---
    path('location/lookup/', views.lookup_location, name='location_lookup'),

    # --- DONATIONS ---
    path('donations/', views.DonationViewSet.as_view({'get': 'list'}), name='donation-list'),
    path('donations/me/', views.DonationViewSet.as_view({'get': 'me'}), name='donation-me'),
    path('donations/<int:pk>/', views.DonationViewSet.as_view({'get': 'retrieve'}), name='donation-detail'),
]
