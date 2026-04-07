from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings

class ServiteurVertumetre(models.Model):
    serviteur = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, limit_choices_to={'role': 'serviteur'}, verbose_name=_("Serviteur"))
    answers = models.JSONField(default=dict, blank=True, verbose_name=_("Réponses"))
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date de soumission"))

    class Meta:
        verbose_name = _("Vertumètre Serviteur")
        verbose_name_plural = _("Vertumètres Serviteurs")

    def __str__(self):
        return f"Vertumètre - {self.serviteur.get_full_name()} ({self.serviteur.username})"

    @property
    def is_submitted_recently(self):
        if not self.submitted_at:
            return False
        return timezone.now() - self.submitted_at < timezone.timedelta(days=7)

    def can_submit(self):
        return not self.is_submitted_recently
