from django import template

register = template.Library()


@register.filter
def get_choice_label(value, question_key):
    """
    Retourne le label correspondant à une valeur stockée.
    Exemple :
        "1" => "Oui"
    """

    try:
        from traning.forms import VertumetreForm
    except Exception:
        return str(value)

    # Récupération sécurisée du champ
    field = VertumetreForm.base_fields.get(question_key)

    # Champ inexistant
    if not field:
        return str(value)

    # Champ sans choices
    if not hasattr(field, 'choices'):
        return str(value)

    target = str(value)

    # Recherche du label
    for key, label in field.choices:
        if str(key) == target:
            return label

    return str(value)