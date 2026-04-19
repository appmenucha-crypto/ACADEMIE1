#!/bin/bash
set -e

# ------------------------------------------------------------
# Affichage de la configuration de la base
# ------------------------------------------------------------
echo "🔍 Connecting to database:"
echo "   NAME: formation_vh_db"
echo "   USER: esther"
echo "   HOST: 127.0.0.1"
echo "   PORT: 5433"

# Installation des dépendances de performance et PDF
echo "pip installing gevent and weasyprint..."
pip install gevent weasyprint

# ------------------------------------------------------------
# Appliquer les migrations Django
# ------------------------------------------------------------
echo "🔄 Running migrations..."
python manage.py migrate --noinput

# ------------------------------------------------------------
# Créer le superuser si inexistant
# ------------------------------------------------------------
echo "👤 Creating superuser if not exists..."
python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()

username = "admin"
email = "admin@example.com"
password = "admin123"

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password, role='admin')
    print("✅ Superuser created:", username)
else:
    print("ℹ️ Superuser already exists:", username)
END

# ------------------------------------------------------------
# Collecter les fichiers statiques
# ------------------------------------------------------------
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput

# ------------------------------------------------------------
# Lancer Gunicorn
# ------------------------------------------------------------
echo "🚀 Starting Gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --worker-class gevent --timeout 600