from django.urls import path
from django.contrib.auth import views as auth_views
from . import views, views_api
from .admin_account import admin_account


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
    path('admin/resultat/<int:pk>/', views.admin_resultat_detail, name='admin_resultat_detail'),
    path('admin/vertumetres/', views.admin_vertumetres, name='admin_vertumetres'),
    path('admin/vertumetres/<int:pk>/', views.admin_vertumetre_detail, name='admin_vertumetre_detail'),
    path('admin/referants/', views.admin_referants, name='admin_referants'),
    path('admin/compte/', admin_account, name='admin_account'),
    path('referant/', views.referant_dashboard, name='referant_dashboard'),
    path('referant/serviteurs/', views.referant_serviteurs, name='referant_serviteurs'),
    path('referant/vertumetres/', views.referant_vertumetres, name='referant_vertumetres'),
    path('referant/serviteur/<int:pk>/', views.referant_serviteur_detail, name='referant_serviteur_detail'),
    path('referant/serviteur/<int:pk>/formations/', views.referant_serviteur_formations, name='referant_serviteur_formations'),
    path('referant/serviteur/<int:pk>/questionnaire/<int:sf_pk>/', views.referant_serviteur_questionnaire, name='referant_serviteur_questionnaire'),
    path('referant/serviteur/<int:pk>/vertumetre/', views.referant_serviteur_vertumetre, name='referant_serviteur_vertumetre'),
    path('referant/serviteur/<int:pk>/message/', views.referant_serviteur_message, name='referant_serviteur_message'),
    path('referant/messages/', views.referant_messages, name='referant_messages'),
    # Ancienne orthographe (« referent ») : redirection permanente vers
    # « /referant/… » pour que les liens et onglets déjà ouverts fonctionnent.
    path('referent/', views.legacy_referent_redirect),
    path('referent/serviteurs/', views.legacy_referent_redirect),
    path('referent/vertumetres/', views.legacy_referent_redirect),
    path('referent/serviteur/<int:pk>/', views.legacy_referent_redirect),
    path('referent/serviteur/<int:pk>/formations/', views.legacy_referent_redirect),
    path('referent/serviteur/<int:pk>/questionnaire/<int:sf_pk>/', views.legacy_referent_redirect),
    path('referent/serviteur/<int:pk>/vertumetre/', views.legacy_referent_redirect),
    path('referent/serviteur/<int:pk>/message/', views.legacy_referent_redirect),
    path('referent/messages/', views.legacy_referent_redirect),
    path('serviteur/dashboard/', views.serviteur_dashboard, name='serviteur_dashboard'),
    path('serviteur/formations/', views.serviteur_formations, name='serviteur_formations'),
    path('serviteur/formation/<int:pk>/', views.serviteur_formation_detail, name='serviteur_formation_detail'),
    path('serviteur/formation/<int:pk>/questionnaire/', views.serviteur_questionnaire, name='serviteur_questionnaire'),
    path('serviteur/formation/<int:pk>/questionnaire/resultat/', views.serviteur_questionnaire_html_result, name='serviteur_questionnaire_html_result'),
    path('serviteur/vertumetre/', views.serviteur_vertumetre, name='serviteur_vertumetre'),
    path('serviteur/messages/', views.serviteur_messages, name='serviteur_messages'),
    path('serviteur/messages/<int:pk>/repondre/', views.serviteur_message_reply, name='serviteur_message_reply'),
]
