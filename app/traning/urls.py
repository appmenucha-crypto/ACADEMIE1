from django.urls import path
from django.contrib.auth import views as auth_views
from . import views, views_api

app_name = 'traning'

urlpatterns = [
    path('api/serviteur/<int:pk>/', views_api.api_serviteur_detail, name='api_serviteur_detail'),

    path('', views.login_view, name='login'),

    path('logout/', views.logout_view, name='logout'),
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/serviteurs/', views.admin_serviteurs, name='admin_serviteurs'),
path('admin/courses/', views.admin_courses, name='admin_courses'),
    path('admin/formations/<int:pk>/', views.admin_formation_detail, name='admin_formation_detail'),
    path('admin/questionnaires/', views.admin_questionnaires, name='admin_questionnaires'),
    path('admin/results/', views.admin_results, name='admin_results'),
    path('admin/vertumetres/', views.admin_vertumetres, name='admin_vertumetres'),
    path('serviteur/dashboard/', views.serviteur_dashboard, name='serviteur_dashboard'),
    path('serviteur/formations/', views.serviteur_formations, name='serviteur_formations'),
    path('serviteur/formation/<int:pk>/', views.serviteur_formation_detail, name='serviteur_formation_detail'),
    path('serviteur/formation/<int:pk>/questionnaire/', views.serviteur_questionnaire, name='serviteur_questionnaire'),
    path('serviteur/vertumetre/', views.serviteur_vertumetre, name='serviteur_vertumetre'),
]
