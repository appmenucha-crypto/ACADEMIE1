from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Les messages peuvent désormais circuler dans les deux sens
    (référent → serviteur et serviteur → référent) : on ne restreint
    donc plus l'expéditeur / le destinataire à un seul rôle."""

    dependencies = [
        ('traning', '0016_referentmessage_reply_to_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referentmessage',
            name='recipient',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages_recus', to=settings.AUTH_USER_MODEL, verbose_name='Destinataire'),
        ),
        migrations.AlterField(
            model_name='referentmessage',
            name='sender',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages_envoyes', to=settings.AUTH_USER_MODEL, verbose_name='Expéditeur'),
        ),
    ]
