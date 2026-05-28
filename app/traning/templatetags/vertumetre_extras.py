from django import template

register = template.Library()


@register.filter
def get_choice_label(value, question_key):
    """Return the display label for a stored answer.

    value: stored answer (often a string like "0", "1", ... or a JSON value)
    question_key: e.g. "q1", "q2", ...
    """
    from traning.forms import VertumetreForm

    # Map only the fields that are real ChoiceFields in the form.
    choices_map = {
        'q1': VertumetreForm.base_fields['q1'].choices,
        'q2': VertumetreForm.base_fields['q2'].choices,
        'q3': VertumetreForm.base_fields['q3'].choices,
        'q4': VertumetreForm.base_fields['q4'].choices,
        'q5': VertumetreForm.base_fields['q5'].choices,
        'q7': VertumetreForm.base_fields['q7'].choices,
        'q8': VertumetreForm.base_fields['q8'].choices,
        'q9': VertumetreForm.base_fields['q9'].choices,
        'q10': VertumetreForm.base_fields['q10'].choices,
        'q11': VertumetreForm.base_fields['q11'].choices,
        'q12': VertumetreForm.base_fields['q12'].choices,
    }

    if question_key not in choices_map:
        return str(value)

    # Stored answers are JSON-serialized; normalize types to compare.
    target = str(value)

    for key, label in choices_map[question_key]:
        if str(key) == target:
            return label

    return str(value)

