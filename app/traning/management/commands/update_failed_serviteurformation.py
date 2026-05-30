from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from traning.models import ServiteurFormation


class Command(BaseCommand):
    help = "Marque en Échoué les formations 'En cours' après 1 jour sans soumission."

    def handle(self, *args, **options):
        now = timezone.now()

        # 1) Si date_limite est NULL mais que date_debut existe, on la recalculera.
        formations = ServiteurFormation.objects.filter(
            statut=2,
            date_soumission__isnull=True,
            date_limite__isnull=True,
            date_debut__isnull=False,
        )

        for sf in formations.only("id", "date_debut"):
            sf.date_limite = sf.date_debut + timedelta(days=1)
            sf.save(update_fields=["date_limite"])

        # 2) Passe en échec toutes les formations expirées (date_limite recalculee ou existante)
        expired_qs = ServiteurFormation.objects.filter(
            statut=2,
            date_soumission__isnull=True,
            date_limite__lte=now,
        )

        # update en DB
        updated = expired_qs.update(statut=0)

        self.stdout.write(
            self.style.SUCCESS(
                f"Mise à jour effectuée : {updated} enregistrement(s) marqués Échoué."
            )
        )

