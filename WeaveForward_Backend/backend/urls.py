from django.urls import path
from django.http import HttpResponse
from rest_framework import permissions
from . import views

urlpatterns = [
    # --- AUTH ---
    path('auth/token', views.TokenViewSet.as_view({'post': 'create', 'delete': 'destroy'}), name='token_obtain'),
    path('auth/token/refresh', views.CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/password-reset', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('auth/password-reset/confirmation', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),

    # --- USERS ---
    path('users', views.UserViewSet.as_view({'get': 'list', 'post': 'create'}), name='user-list'),
    path('webhooks', views.webhooks, name='webhooks'),

    # --- ME ROUTES ---
    path('users/me', views.UserViewSet.as_view({'get': 'me', 'patch': 'partial_update_me'}), name='user-me'),
    path('users/me/subscription', views.UserViewSet.as_view({'post': 'create_my_subscription', 'delete': 'cancel_my_subscription'}), name='user-me-subscription'),
    path('users/me/2fa', views.UserViewSet.as_view({'post': 'my_two_factor', 'delete': 'my_two_factor'}), name='user-me-2fa'),
    path('users/me/2fa/setup', views.UserViewSet.as_view({'post': 'two_factor_setup'}), name='user-2fa-setup'),
    path('users/me/donations', views.DonationViewSet.as_view({'get': 'me'}), name='donation-me'),
    path('users/me/payments', views.PaymentMeView.as_view(), name='payment-me'),
    
    # --- PK ROUTES ---
    path('users/<int:pk>', views.UserViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='user-detail'),
    path('users/<int:pk>/approve', views.UserViewSet.as_view({'post': 'approve'}), name='user-approve'),
    path('users/<int:pk>/subscription', views.UserViewSet.as_view({'post': 'create_subscription', 'delete': 'cancel_subscription'}), name='user-subscription'),
    path('users/<int:pk>/2fa', views.UserViewSet.as_view({'post': 'two_factor', 'delete': 'two_factor'}), name='user-2fa-detail'),

    # --- LOCATIONS ---
    path('location/lookup', views.lookup_location, name='location_lookup'),

    # --- DONATIONS ---
    path('donations', views.DonationViewSet.as_view({'get': 'list', 'post': 'create'}), name='donation-list'),
    path('donations/<int:pk>/quotation', views.DonationViewSet.as_view({'post': 'quotation'}), name='donation-quotation'),
    path('donations/<int:pk>/claim', views.DonationViewSet.as_view({'post': 'claim'}), name='donation-claim'),
    path('donations/<int:pk>/transit', views.DonationViewSet.as_view({'post': 'transit'}), name='donation-transit'),
    path('donations/<int:pk>/resolve', views.DonationViewSet.as_view({'post': 'resolve'}), name='donation-resolve'),
    path('donations/<int:pk>/cancel', views.DonationViewSet.as_view({'post': 'cancel'}), name='donation-cancel'),
    path('donations/<int:pk>/archive', views.DonationViewSet.as_view({'post': 'archive'}), name='donation-archive'),
    path('donations/<int:pk>', views.DonationViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update'}), name='donation-detail'),
    
    # --- INVENTORY ---
    path('inventory', views.InventoryViewSet.as_view({'get': 'list'}), name='inventory-list'),
    path('inventory/snapshot', views.InventoryViewSet.as_view({'get': 'snapshot'}), name='inventory-snapshot'),
    path('inventory/<int:pk>', views.InventoryViewSet.as_view({'get': 'retrieve'}), name='inventory-detail'),
    path('inventory/<int:pk>/audit-history', views.InventoryViewSet.as_view({'get': 'audit_history'}), name='inventory-audit-history'),
    path('inventory/<int:pk>/update-usage', views.InventoryViewSet.as_view({'post': 'update_usage'}), name='inventory-update-usage'),
    path('inventory/<int:pk>/archive', views.InventoryViewSet.as_view({'post': 'archive'}), name='inventory-archive'),
    path('inventory/<int:pk>/restore', views.InventoryViewSet.as_view({'post': 'restore'}), name='inventory-restore'),
    path('inventory/export', views.InventoryViewSet.as_view({'get': 'export'}), name='inventory-export'),

    # --- MATCH RECOMMENDATIONS ---
    path('match-recommendations', views.MatchRecommendationViewSet.as_view({'get': 'list'}), name='match-recommendation-list'),
    path('match-recommendations/<int:pk>', views.MatchRecommendationViewSet.as_view({'get': 'retrieve'}), name='match-recommendation-detail'),
    path('match-recommendations/<int:pk>/accept', views.MatchRecommendationViewSet.as_view({'post': 'accept'}), name='match-recommendation-accept'),
    path('match-recommendations/<int:pk>/reject', views.MatchRecommendationViewSet.as_view({'post': 'reject'}), name='match-recommendation-reject'),

    # --- IMPACT DASHBOARD ---
    path('impact-dashboard', views.ImpactDashboardViewSet.as_view({'get': 'list'}), name='impact-dashboard'),
    path('tuab-circular-economy', views.TuabCircularEconomyViewSet.as_view({'get': 'list'}), name='tuab-circular-economy'),

    # --- PAYMENTS ---
    path('payments', views.PaymentListView.as_view(), name='payment-list'),

    # --- MATERIALS ---
    path('brandfiberlookups', views.BrandFiberLookupViewset.as_view({'get': 'list'}), name='material-list'),
    path('fibers', views.BrandFiberLookupViewset.as_view({'get': 'fibers'}), name='material-fibers'),
    path('clothing-types', views.BrandFiberLookupViewset.as_view({'get': 'clothing_types'}), name='material-clothing-types'),
    path('brands', views.BrandFiberLookupViewset.as_view({'get': 'brands'}), name='material-brands'),
]
