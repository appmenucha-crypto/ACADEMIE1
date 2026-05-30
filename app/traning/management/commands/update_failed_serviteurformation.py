from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from traning.models import ServiteurFormation


class Command(BaseCommand):
    help = "Passe en Échoué les formations expirées sans soumission."

    def handle(self, *args, **options):
        now = timezone.now()

        # Met à jour les date_limite manquantes (cas où date_limite est NULL en DB)
        formations = ServiteurFormation.objects.filter(
            statut=2,  # En cours
            date_soumission__isnull=True,
            date_limite__isnull=True,
            date_debut__isnull=False,
        )

        for sf in formations.only("id", "date_debut"):
            sf.date_limite = sf.date_debut + timedelta(days=1)
            sf.save(update_fields=["date_limite"])

        # Passe en échec les formations expirées
        updated = ServiteurFormation.objects.filter(
            statut=2,
            date_soumission__isnull=True,
            date_limite__lte=now,
        ).update(statut=0)

        self.stdout.write(
            self.style.SUCCESS(f"{updated} formation(s) marquée(s) Échoué.")
        )

