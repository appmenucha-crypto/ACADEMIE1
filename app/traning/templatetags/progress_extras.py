from django import template

register = template.Library()

@register.filter
def dict_get(d, k):
    """Récupère d[k] ou None"""
    if not d:
        return None
    try:
        return d.get(int(k))
    except (ValueError, TypeError):
        return d.get(k)

@register.simple_tag
def progress_status(formation, progress_info):
    if not progress_info or formation.pk not in progress_info:
        return 'not_started'
    p = progress_info[formation.pk]
    return p.get('status', 'not_started')
