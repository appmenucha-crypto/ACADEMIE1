from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import json

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Administrateur'),
        ('serviteur', 'Serviteur'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='serviteur')
    phone_number = models.CharField(max_length=15, blank=True, null=True, verbose_name=_("Numéro de téléphone"))
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, verbose_name=_("Photo de profil"))
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.role})"

class Formation(models.Model):
    name = models.CharField(max_length=200, verbose_name=_("Nom de la formation"))
    questionnaire_json = models.JSONField(default=list, verbose_name=_("Questionnaire (JSON)"), help_text=_("Liste [{'question': '..', 'options': ['a','b'], 'correct': 0}]"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Bloc(models.Model):
    formation = models.ForeignKey(Formation, on_delete=models.CASCADE, related_name='blocs')
    name = models.CharField(max_length=100, verbose_name=_("Nom du bloc"))
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.formation.name} - {self.name}"

class AudioFile(models.Model):
    bloc = models.ForeignKey(Bloc, on_delete=models.CASCADE, related_name='audios')
    file = models.FileField(upload_to='audios/', verbose_name=_("Fichier audio"))
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.bloc} - Audio {self.order}"

class VideoFile(models.Model):
    bloc = models.ForeignKey(Bloc, on_delete=models.CASCADE, related_name='videos')
    file = models.FileField(upload_to='videos/', verbose_name=_("Fichier vidéo"))
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.bloc} - Vidéo {self.order}"

class ServiteurFormation(models.Model):
    STATUT_CHOICES = [
        (0, 'Échoué'),
        (1, 'Validé'),
        (2, 'En cours'),
    ]
    serviteur = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'serviteur'})
    formation = models.ForeignKey(Formation, on_delete=models.CASCADE)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_limite = models.DateTimeField(null=True, blank=True)  # deadline = debut + 3j
    date_soumission = models.DateTimeField(null=True, blank=True)  # quand le serviteur soumet
    score = models.IntegerField(default=0, help_text=_("Pourcentage /100"))
    statut = models.IntegerField(choices=STATUT_CHOICES, default=2)

    class Meta:
        unique_together = ['serviteur', 'formation']

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.date_debut and not self.date_limite:
            self.date_limite = self.date_debut + timezone.timedelta(days=3)
        if self.date_soumission:  # questionnaire soumis
            self.statut = 1 if self.score >= 50 else 0
        elif self.date_limite and now > self.date_limite:  # délai dépassé sans soumission
            self.statut = 0
        else:
            self.statut = 2  # en cours
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.serviteur} - {self.formation} (Statut: {self.get_statut_display()})"
