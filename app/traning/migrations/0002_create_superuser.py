from django.db import migrations
from django.contrib.auth.hashers import make_password

def create_superuser(apps, schema_editor):
    # On récupère le modèle CustomUser via le registre des apps de la migration
    # pour éviter les problèmes d'import direct
    User = apps.get_model('traning', 'CustomUser')
    
    if not User.objects.filter(username='admin').exists():
        User.objects.create(
            username='admin',
            email='admin@example.com',
            password=make_password('adminpass123'),  # Change ce mot de passe par la suite !
            is_staff=True,
            is_superuser=True,
            role='admin',
            is_active=True
        )

def remove_superuser(apps, schema_editor):
    User = apps.get_model('traning', 'CustomUser')
    User.objects.filter(username='admin').delete()

class Migration(migrations.Migration):

    dependencies = [
        # On dépend de la migration initiale qui crée la table CustomUser
        ('traning', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_superuser, remove_superuser),
    ]