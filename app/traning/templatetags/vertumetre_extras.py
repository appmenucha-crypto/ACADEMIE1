import re

from django import template

register = template.Library()


@register.filter
def get_question_label(question_key):
    """Retourne l'intitulé de la question correspondant à une clé de réponse.

    Le numéro initial (« 1- », « 8. ») est retiré : il est déjà affiché
    à côté du libellé.
    """
    try:
        from traning.forms import VertumetreForm
    except Exception:
        return ''

    field = VertumetreForm.base_fields.get(question_key)
    if not field:
        return ''

    label = str(getattr(field, 'label', '') or '').strip()
    return re.sub(r'^\s*\d+\s*[.\-–:]\s*', '', label).strip()


@register.filter
def get_choice_label(value, question_key):
    """Retourne le label correspondant à une valeur stockée.

    Gère aussi les champs multi-choix (ex: q7) où value peut être une liste.
    """

    try:
        from traning.forms import VertumetreForm
    except Exception:
        return str(value)

    field = VertumetreForm.base_fields.get(question_key)
    if not field:
        return str(value)

    # Cas multi-choix (ex: CheckboxSelectMultiple)
    if isinstance(value, (list, tuple)):
        labels = []
        for v in value:
            labels.append(get_choice_label(v, question_key))
        # Déjà filtré via récursion; on évite d'afficher des doublons simples.
        deduped = []
        seen = set()
        for l in labels:
            if l not in seen:
                seen.add(l)
                deduped.append(l)
        return ", ".join(deduped)

    # Champ sans choices
    if not hasattr(field, 'choices'):
        return str(value)

    target = str(value)

    for key, label in field.choices:
        if str(key) == target:
            return label

    return str(value)

