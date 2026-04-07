from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.http import JsonResponse
from .models import Formation, Bloc, AudioFile
from .forms import BlocForm, AudioForm

@login_required(login_url='/')
def admin_formation_detail(request, pk):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    formation = get_object_or_404(Formation, pk=pk)
    
    success_message = None
    error_message = None
    
    if request.method == 'POST':
        if 'add_bloc' in request.POST:
            bloc = Bloc(
                formation=formation,
                name=request.POST['bloc_name'],
                order=request.POST.get('bloc_order', formation.blocs.count() + 1)
            )
            bloc.save()
            success_message = "Bloc créé !"
        
        if 'add_audio' in request.POST:
            bloc = get_object_or_404(Bloc, pk=request.POST['bloc_id'])
            audio = AudioFile(
                bloc=bloc,
                file=request.FILES['audio_file'],
                order=request.POST.get('audio_order', bloc.audios.count() + 1)
            )
            audio.save()
            success_message = "Audio ajouté !"
    
    return render(request, 'admin/formation_detail.html', {
        'formation': formation,
        'success_message': success_message,
        'error_message': error_message
    })
