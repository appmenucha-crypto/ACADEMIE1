from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import json

class Departement(models.Model):
    name = models.CharField(max_length=120, unique=True, verbose_name=_("Département"))

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Administrateur'),
        ('serviteur', 'Serviteur'),
        ('referant', 'Référent'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='serviteur')

    departement = models.ForeignKey(
        Departement,
        on_delete=models.SET_NULL,
        related_name='serviteurs',
        blank=True,
        null=True,
        verbose_name=_("Département"),
    )

    phone_number = models.CharField(max_length=15, blank=True, null=True, verbose_name=_("Numéro de téléphone"))
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, verbose_name=_("Photo de profil"))
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))

    referant = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='serviteurs_assignes',
        limit_choices_to={'role': 'referant'},
        verbose_name=_("Référent"),
    )


    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.role})"

class Formation(models.Model):
    name = models.CharField(max_length=200, verbose_name=_("Nom de la formation"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"), help_text=_("Une formation inactive reste visible par l'administration (questionnaires, contenus) mais n'apparaît pas chez les serviteurs."))
    questionnaire_json = models.JSONField(default=list, verbose_name=_("Questionnaire (JSON)"), help_text=_("Liste [{'question': '..', 'options': ['a','b'], 'correct': 0}]"))
    questionnaire_html = models.TextField(blank=True, default='', verbose_name=_("Questionnaire (HTML)"), help_text=_("Contenu HTML d'un questionnaire importé. Prend le pas sur le questionnaire JSON lorsqu'il est renseigné."))
    questionnaire_date = models.DateTimeField(blank=True, null=True, verbose_name=_("Date de mise à disposition (HTML)"))
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

from datetime import timedelta
from django.db import models
from django.utils import timezone


class ServiteurFormation(models.Model):
    STATUT_CHOICES = [
        (0, 'Échoué'),
        (1, 'Validé'),
        (2, 'En cours'),
        (3, 'Non transmis'),
    ]

    serviteur = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'serviteur'}
    )

    formation = models.ForeignKey(Formation, on_delete=models.CASCADE)

    date_debut = models.DateTimeField(null=True, blank=True)
    date_limite = models.DateTimeField(null=True, blank=True)
    date_soumission = models.DateTimeField(null=True, blank=True)

    score = models.IntegerField(default=0, help_text="Pourcentage /100")
    statut = models.IntegerField(choices=STATUT_CHOICES, default=2)
    html_responses = models.JSONField(blank=True, null=True, verbose_name=_("Réponses du questionnaire HTML"))

    class Meta:
        unique_together = ['serviteur', 'formation']

    def save(self, *args, **kwargs):
        # Définit la date limite à la création
        if self.date_debut and not self.date_limite:
            self.date_limite = self.date_debut + timedelta(days=3)

        # Si le questionnaire est soumis
        if self.date_soumission:
            self.statut = 1 if self.score >= 50 else 0

        super().save(*args, **kwargs)

    @property
    def display_status(self):
        """Statut d'affichage unifié.

        - 'valid' : questionnaire soumis et validé
        - 'failed' : questionnaire soumis mais non validé (échec réel)
        - 'not_transmitted' : formation commencée, questionnaire jamais transmis
        - 'progress' : formation en cours, délai encore ouvert
        """
        if self.date_soumission is not None:
            return 'valid' if self.statut == 1 else 'failed'
        if self.statut in (0, 3):
            return 'not_transmitted'
        return 'progress'

    @property
    def statut_label(self):
        """Libellé lisible du statut d'affichage."""
        return {
            'valid': 'Validé',
            'failed': 'Échoué',
            'not_transmitted': 'Non transmis',
            'progress': 'En cours',
        }.get(self.display_status, 'En cours')

    def __str__(self):
        return (
            f"{self.serviteur} - {self.formation} "
            f"(Statut: {self.get_statut_display()})"
        )


class ReferentMessage(models.Model):
    """Message échangé entre un référent et l'un de ses serviteurs."""

    sender = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='messages_envoyes',
        verbose_name=_("Expéditeur"),
    )
    recipient = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='messages_recus',
        verbose_name=_("Destinataire"),
    )
    subject = models.CharField(max_length=200, verbose_name=_("Objet"))
    body = models.TextField(verbose_name=_("Message"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Envové le"))
    read_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Lu le"))
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='reponses',
        null=True,
        blank=True,
        verbose_name=_("Réponse à"),
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Message référent")
        verbose_name_plural = _("Messages référent")

    def __str__(self):
        return f"{self.subject} → {self.recipient} ({self.created_at:%d/%m/%Y})"

    @property
    def is_read(self):
        return self.read_at is not None
