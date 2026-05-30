from django.core.management.base import BaseCommand
from django.utils import timezone

from traning.models import ServiteurFormation


class Command(BaseCommand):
    help = "Marque en Échoué les ServiteurFormation en 'En cours' depuis plus de 1 jour sans soumission."

    def handle(self, *args, **options):
        now = timezone.now()

        # Important : certains enregistrements peuvent avoir date_limite NULL.
        # On considère alors que la limite doit être recalculée depuis date_debut.
        qs = ServiteurFormation.objects.filter(
            statut=2,  # En cours
            date_soumission__isnull=True,
        )

        updated = 0
        for sf in qs.only("id", "date_debut", "date_limite"):
            # recalculer date_limite si nécessaire
            if sf.date_limite is None and sf.date_debut is not None:
                sf.date_limite = sf.date_debut + timezone.timedelta(days=1)
                sf.save(update_fields=["date_limite"])

            if sf.date_limite is not None and sf.date_limite <= now:
                sf.statut = 0
                sf.save(update_fields=["statut"])
                updated += 1


        self.stdout.write(self.style.SUCCESS(f"Mise à jour effectuée: {updated} enregistrement(s) marqués Échoué."))

