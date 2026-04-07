from django import template

register = template.Library()

@register.filter
def get_choice_label(value, question_key):
    from traning.forms import VertumetreForm
    
    CHOICES = {
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
    
    if question_key in CHOICES:
        for key, label in CHOICES[question_key]:
            if str(key) == str(value):
                return label
    return str(value)
