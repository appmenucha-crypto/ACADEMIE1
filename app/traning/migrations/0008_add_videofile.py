from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('traning', '0007_rename_date_fin_serviteurformation_date_limite_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='VideoFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='videos/', verbose_name='Fichier vidéo')),
                ('order', models.PositiveIntegerField(default=0)),
                ('bloc', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='videos', to='traning.bloc')),
            ],
            options={
                'ordering': ['order'],
            },
        ),
    ]
