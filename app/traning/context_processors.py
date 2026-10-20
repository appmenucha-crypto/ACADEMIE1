from .models import CustomUser, ReferentMessage


def serviteur_list_for_referant(request):
    """Injecte la liste des serviteurs assignés au référent courant dans le contexte,
    afin que lebloc sidebar affiche la liste sur chaque page du référent."""
    if getattr(request.user, 'role', None) == 'referant':
        serviteurs = CustomUser.objects.filter(role='serviteur', referant=request.user).order_by('-date_joined')
        return {'serviteurs_list': serviteurs}
    return {}


def serviteur_unread_messages(request):
    """Nombre de messages non lus du serviteur (badge de la sidebar)."""
    if getattr(request.user, 'role', None) != 'serviteur':
        return {}
    count = ReferentMessage.objects.filter(
        recipient=request.user, read_at__isnull=True
    ).count()
    return {'serviteur_unread_messages': count}
