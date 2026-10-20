from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from traning.models import ServiteurFormation


class Command(BaseCommand):
    help = "Alias de update_failed_serviteurformation : marque « Non transmis » les formations expirées sans soumission."

    def handle(self, *args, **options):
        from django.core.management import call_command

        call_command('update_failed_serviteurformation')
