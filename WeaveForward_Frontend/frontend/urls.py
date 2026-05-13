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
    
    # --- Donor ---
    path('donor/browse-businesses/', views.donor_browse_businesses, name='donor_browse_businesses'),
    path('donor/my-donations/', views.donor_my_donations, name='donor_my_donations'),
    path('donor/my-donations/<int:donation_id>/', views.donor_view_donation, name='donor_view_donation'),
    path('donor/tuabs/<int:user_id>/', views.donor_view_tuab, name='donor_view_tuab'),
    
    # --- TUAB ---
    path('tuab/dashboard/', views.tuab_dashboard, name='tuab_dashboard'),
    path('tuab/subscribe/', views.tuab_subscribe, name='tuab_subscribe'),
    
    # --- Admin ---
    path('admin/donations/', views.admin_view_donations, name='admin_view_donations'),
    path('admin/donations/add/', views.admin_add_donation, name='admin_add_donation'),
    path('admin/donations/<int:donation_id>/', views.admin_view_donation, name='admin_view_donation'),
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
