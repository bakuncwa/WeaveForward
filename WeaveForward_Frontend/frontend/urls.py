from django.urls import path
from . import views

urlpatterns = [
    # --- Public ---
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('select-role/', views.role_select, name='role_select'),
    path('register/donor/', views.donor_registration, name='donor_registration'),
    path('register/tuab/', views.tuab_registration, name='tuab_registration'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password-confirm/', views.reset_password_confirm, name='reset_password_confirm'),
    path('api/location/lookup/', views.location_lookup_proxy, name='location_lookup_proxy'),
    path('api/materials/clothing-types/', views.material_clothing_types_proxy, name='material_clothing_types_proxy'),
    path('api/materials/brands/', views.material_brands_proxy, name='material_brands_proxy'),
    path('api/materials/search/', views.material_search_proxy, name='material_search_proxy'),
    path('api/donors/search/', views.donor_search_proxy, name='donor_search_proxy'),
    
    # --- Donor ---
    path('donor/browse-businesses/', views.donor_browse_businesses, name='donor_browse_businesses'),
    path('donor/my-donations/', views.donor_my_donations, name='donor_my_donations'),
    path('donor/my-donations/<int:donation_id>/', views.donor_view_donation, name='donor_view_donation'),
    path('donor/my-donations/<int:donation_id>/edit/', views.donor_edit_donation, name='donor_edit_donation'),
    path('donor/my-donations/<int:donation_id>/cancel/', views.donor_cancel_donation, name='donor_cancel_donation'),
    path('donor/tuabs/<int:user_id>/', views.donor_view_tuab, name='donor_view_tuab'),
    path('donor/create-donation/', views.donor_create_donation, name='donor_create_donation'),
    path('donor/profile/', views.donor_profile, name='donor_profile'),
    path('donor/edit-profile/', views.donor_edit_profile, name='edit_profile'),
    
    # --- Auth/2FA Proxies ---
    path('api/2fa/setup/', views.two_factor_setup_proxy, name='two_factor_setup_proxy'),
    path('api/2fa/verify/', views.two_factor_verify_proxy, name='two_factor_verify_proxy'),
    path('api/2fa/disable/', views.two_factor_disable_proxy, name='two_factor_disable_proxy'),
    
    # --- TUAB ---
    path('tuab/dashboard/', views.tuab_dashboard, name='tuab_dashboard'),
    path('tuab/donations/<int:donation_id>/', views.tuab_view_donation, name='tuab_view_donation'),
    path('tuab/donations/<int:donation_id>/edit/', views.tuab_update_incoming_donation, name='tuab_update_incoming_donation'),
    path('api/tuab/donations/<int:donation_id>/quotation/', views.tuab_quotation_proxy, name='tuab_quotation_proxy'),
    path('tuab/subscribe/', views.tuab_subscribe, name='tuab_subscribe'),
    
    # --- Admin ---
    path('admin/donations/', views.admin_view_donations, name='admin_view_donations'),
    path('admin/donations/add/', views.admin_add_donation, name='admin_add_donation'),
    path('admin/donations/<int:donation_id>/', views.admin_view_donation, name='admin_view_donation'),
    path('admin/donations/<int:donation_id>/edit/', views.admin_edit_donation, name='admin_edit_donation'),
    path('admin/donations/<int:donation_id>/cancel/', views.admin_cancel_donation, name='admin_cancel_donation'),
    path('admin/donations/<int:donation_id>/archive/', views.admin_archive_donation, name='admin_archive_donation'),
    path('admin/donors/', views.admin_view_donors, name='admin_view_donors'),
    path('admin/tuabs/', views.admin_view_tuabs, name='admin_view_tuabs'),
    path('admin/tuabs/add/', views.admin_add_tuab, name='admin_add_tuab'),
    path('admin/tuabs/<int:user_id>/', views.admin_view_tuab, name='admin_view_tuab'),
    path('admin/tuabs/<int:user_id>/edit/', views.admin_edit_tuab, name='admin_edit_tuab'),
    path('admin/donors/add/', views.admin_add_donor, name='admin_add_donor'),
    path('admin/donors/<int:user_id>/', views.admin_view_donor, name='admin_view_donor'),
    path('admin/donors/<int:user_id>/edit/', views.admin_edit_donor, name='admin_edit_donor'),
    path('admin/users/<int:user_id>/archive/', views.admin_archive_user_proxy, name='admin_archive_user_proxy'),
]
