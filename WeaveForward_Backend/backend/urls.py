from django.urls import path
from . import views

urlpatterns = [
    # --- AUTH ---
    path('login', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('logout', views.LogoutView.as_view(), name='token_blacklist'),
    path('token/refresh', views.CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('password-reset', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('register', views.RegisterView.as_view(), name='register'),

    # --- USERS ---
    path('users', views.UserViewSet.as_view({'get': 'list', 'post': 'create'}), name='user-list'),
    path('users/me', views.UserViewSet.as_view({'get': 'me'}), name='user-me'),
    path('users/me/2fa/setup', views.UserViewSet.as_view({'post': 'two_factor_setup'}), name='user-2fa-setup'),
    path('users/me/2fa', views.UserViewSet.as_view({'post': 'my_two_factor', 'delete': 'my_two_factor'}), name='user-me-2fa'),
    path('users/<int:pk>/2fa', views.UserViewSet.as_view({'post': 'two_factor', 'delete': 'two_factor'}), name='user-2fa-detail'),
    path('users/<int:pk>/approve', views.UserViewSet.as_view({'post': 'approve'}), name='user-approve'),
    path('users/me/subscription', views.UserViewSet.as_view({'delete': 'cancel_my_subscription'}), name='user-me-subscription'),
    path('users/<int:pk>/subscription', views.UserViewSet.as_view({'post': 'create_subscription', 'delete': 'cancel_subscription'}), name='user-subscription'),
    path('users/<int:pk>', views.UserViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='user-detail'),
    path('webhooks', views.webhooks, name='webhooks'),

    # --- LOCATIONS ---
    path('location/lookup', views.lookup_location, name='location_lookup'),

    # --- DONATIONS ---
    path('donations', views.DonationViewSet.as_view({'get': 'list', 'post': 'create'}), name='donation-list'),
    path('donations/me', views.DonationViewSet.as_view({'get': 'me'}), name='donation-me'),
    path('donations/<int:pk>', views.DonationViewSet.as_view({'get': 'retrieve'}), name='donation-detail'),

    # --- MATERIALS ---
    path('brandfiberlookups', views.BrandFiberLookupViewset.as_view({'get': 'list'}), name='material-list'),
    path('brandfiberlookups/fibers', views.BrandFiberLookupViewset.as_view({'get': 'fibers'}), name='material-fibers'),
    path('brandfiberlookups/<int:pk>', views.BrandFiberLookupViewset.as_view({'get': 'retrieve'}), name='material-detail'),
]
