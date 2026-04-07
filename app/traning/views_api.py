from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from .models import CustomUser

@login_required
@require_http_methods(["GET"])
def api_serviteur_detail(request, pk):
    try:
        serviteur = CustomUser.objects.get(pk=pk, role='serviteur')
        data = {
            'username': serviteur.username,
            'first_name': serviteur.first_name,
            'last_name': serviteur.last_name,
            'email': serviteur.email,
            'phone_number': serviteur.phone_number,
            'profile_photo': serviteur.profile_photo.url if serviteur.profile_photo else None,
        }
        return JsonResponse(data)
    except CustomUser.DoesNotExist:
        return JsonResponse({'error': 'Serviteur not found'}, status=404)

