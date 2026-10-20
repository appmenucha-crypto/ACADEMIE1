from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def configure_sqlite(sender, connection, **kwargs):
    """Configure SQLite pour supporter la concurrence (Django < 5.1 n'a pas
    d'option `init_command`).

    - journal_mode=WAL : les lectures ne sont plus bloquées pendant une
      écriture (uploads de médias, sessions, messages).
    - synchronous=NORMAL : compromisperf/durabilité adapté à SQLite en WAL.
    - busy_timeout : une écriture en attente attend au lieu d'échouer
      immédiatement avec « database is locked ».
    """
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        try:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA busy_timeout=15000;')
        except Exception:
            # La base peut être verrouillée par un autre processus : on
            # conserve les réglages par défaut plutôt que de casser la requête.
            pass


class TraningConfig(AppConfig):
    name = 'traning'
