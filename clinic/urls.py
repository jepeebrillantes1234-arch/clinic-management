from django.urls import path
from . import views

urlpatterns = [
    # Pages / Dashboard
    path('', views.landing, name='landing'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('settings/', views.settings_page, name='settings'),
    path('settings/change-password/', views.CustomPasswordChangeView.as_view(), name='change_password'),
    path('reports/', views.reports, name='reports'),
    path('logout/', views.logout_view, name='logout'),

    # Auth / Password Reset
    path('accounts/forgot-password/', views.forgot_password_request, name='forgot_password_request'),
    path('accounts/forgot-password/verify/', views.forgot_password_verify, name='forgot_password_verify'),

    # Medicines
    path('medicines/', views.medicine_list, name='medicine_list'),
    path('medicines/add/', views.medicine_create, name='medicine_create'),
    path('medicines/<int:pk>/edit/', views.medicine_edit, name='medicine_edit'),
    path('medicines/<int:pk>/delete/', views.medicine_delete, name='medicine_delete'),

    # Students (Dito na dadaan ang pagdaragdag ng estudyante)
    path('students/', views.student_records, name='student_records'),
    path('students/add/', views.student_create, name='student_create'),
    path('students/<int:pk>/', views.student_views, name='student_views'),
    path('students/<int:pk>/edit/', views.student_edit, name='student_edit'),
    path('students/<int:pk>/delete/', views.student_delete, name='student_delete'),

    # Medicine Records (Dispensing History)
    path('students/<int:student_pk>/medicine-record/add/', views.medicine_record_create, name='medicine_record_create'),
    path('medicine-record/<int:pk>/edit/', views.medicine_record_edit, name='medicine_record_edit'),
    path('medicine-record/<int:pk>/delete/', views.medicine_record_delete, name='medicine_record_delete'),

    # Nurses & Login Activities
    path('nurses/', views.nurse_list, name='nurse_list'),
    path('nurses/add/', views.nurse_add, name='nurse_add'),
    path('nurses/<int:pk>/', views.nurse_views, name='nurse_views'),
    path('nurses/<int:pk>/edit/', views.nurse_edit, name='nurse_edit'),
    path('nurses/<int:pk>/delete/', views.nurse_delete, name='nurse_delete'),
    path('nurses/login-activity/', views.login_activity, name='login_activity'),

    # System Activity Logs
    path('activities/', views.activity_log_list, name='activity_log_list'),
    path('activities/delete-selected/', views.delete_selected_activities, name='delete_selected_activities'),
    path('activities/delete-all/', views.delete_all_activities, name='delete_all_activities'),
]