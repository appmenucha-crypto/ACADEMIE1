from django.core.management.base import BaseCommand
from django.utils import timezone

from traning.models import ServiteurFormation


class Command(BaseCommand):
    help = "Marque en Échoué les ServiteurFormation en 'En cours' depuis plus de 1 jour sans soumission."

    def handle(self, *args, **options):
        now = timezone.now()

        qs = ServiteurFormation.objects.filter(
            statut=2,  # En cours
            date_limite__isnull=False,
            date_limite__lte=now,
            date_soumission__isnull=True,
        )

        updated = qs.update(statut=0)  # Échoué

        self.stdout.write(self.style.SUCCESS(f"Mise à jour effectuée: {updated} enregistrement(s) marqués Échoué."))

