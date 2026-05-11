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
    path('donor/dashboard/', views.donor_dashboard, name='donor_dashboard'),
    
    # --- TUAB ---
    path('tuab/dashboard/', views.tuab_dashboard, name='tuab_dashboard'),
    
    # --- Admin ---
    path('admin/donations/', views.admin_view_donations, name='admin_view_donations'),
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
