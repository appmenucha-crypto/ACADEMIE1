import csv
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from .models import CustomUser

@login_required(login_url='/')
def admin_dashboard(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    from .models import CustomUser, Formation, ServiteurFormation
    from .models_vertumetre import ServiteurVertumetre
    from django.db.models import Count, Avg, Q
    from datetime import timedelta
    
    serviteurs_count = CustomUser.objects.filter(role='serviteur').count()
    formations_count = Formation.objects.count()
    pending_actions = ServiteurFormation.objects.filter(statut=2).count()
    vertumetre_count = ServiteurVertumetre.objects.count()
    
    # Graph data
    sf_stats = {
        'total': ServiteurFormation.objects.filter(date_soumission__isnull=False).count(),
        'avg_score': round((ServiteurFormation.objects.filter(date_soumission__isnull=False).aggregate(avg=Avg('score'))['avg'] or 0) * 0.2, 1),
        'validated': ServiteurFormation.objects.filter(statut=1).count(),
        'failed': ServiteurFormation.objects.filter(statut=0).count(),
        'pending': ServiteurFormation.objects.filter(statut=2).count()
    }
    
    recent_formations = ServiteurFormation.objects.filter(date_soumission__gte=timezone.now()-timedelta(days=30)).values('date_soumission__date').annotate(count=Count('id'), avg=Avg('score')).order_by('date_soumission__date')
    recent_labels = [item['date_soumission__date'] for item in recent_formations]
    recent_data = [round(item['avg'],1) if item['avg'] else 0 for item in recent_formations]
    
    top_serviteurs = ServiteurFormation.objects.filter(date_soumission__isnull=False).values('serviteur__username').annotate(avg_score=Avg('score')/5, count=Count('id')).order_by('-avg_score')[:5]
    
    return render(request, 'admin/dashboard.html', {
        'students_count': serviteurs_count,
        'formations_count': formations_count,
        'pending_actions': pending_actions,
        'sf_stats': sf_stats,
        'recent_labels': recent_labels,
        'recent_data': recent_data,
        'top_serviteurs': top_serviteurs,
        'vertumetre_count': vertumetre_count
    })

@login_required(login_url='/')
def admin_serviteurs(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    from .forms import ServiteurForm
    serviteurs = CustomUser.objects.filter(role='serviteur').order_by('-date_joined')
    
    serviteur_form = ServiteurForm()
    success_message = None
    
    if request.method == 'POST':
        if 'create' in request.POST:
            serviteur_form = ServiteurForm(request.POST, request.FILES)
            if serviteur_form.is_valid():
                serviteur = serviteur_form.save()
                temp_pass = getattr(serviteur, '_temp_password', 'généré')
                success_message = f"Serviteur '{serviteur.username}' créé avec succès ! Mot de passe temporaire : **{temp_pass}** (changez-le au prochain login)"
                serviteur_form = ServiteurForm()
            # else: errors in form
        elif 'update' in request.POST:
            pk = request.POST.get('pk')
            try:
                serviteur = CustomUser.objects.get(id=pk, role='serviteur')
                form = ServiteurForm(request.POST, request.FILES, instance=serviteur)
                if form.is_valid():
                    form.save()
                    success_message = f"Serviteur '{serviteur.username}' mis à jour !"
                serviteur_form = ServiteurForm()
            except CustomUser.DoesNotExist:
                pass
            # else: errors in form
    
    return render(request, 'admin/serviteurs.html', {
        'serviteurs': serviteurs,
        'serviteur_form': serviteur_form,
        'success_message': success_message
    })

@login_required(login_url='/')
def api_get_serviteur(request, pk):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        serviteur = CustomUser.objects.get(id=pk, role='serviteur')
        return JsonResponse({
            'username': serviteur.username,
            'first_name': serviteur.first_name,
            'last_name': serviteur.last_name,
            'email': serviteur.email,
            'phone_number': serviteur.phone_number,
            'profile_photo': serviteur.profile_photo.url if serviteur.profile_photo else None,
        })
    except CustomUser.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

@login_required(login_url='/')
def admin_vertumetres(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    from .models_vertumetre import ServiteurVertumetre
    submissions = ServiteurVertumetre.objects.select_related('serviteur').order_by('-submitted_at')
    return render(request, 'admin/vertumetres.html', {
        'submissions': submissions
    })

@login_required(login_url='/')
def admin_courses(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    from .forms import FormationCreationForm
    from .models import Formation, Bloc, AudioFile
    
    formations = Formation.objects.prefetch_related('blocs__audios').all().order_by('-created_at')
    formation_form = FormationCreationForm()
    success_message = None
    
    if request.method == 'POST':
        if 'create' in request.POST:
            form = FormationCreationForm(request.POST, request.FILES)
            if form.is_valid():
                formation = form.save()
                
                # Gestion des audios multiples
                audio_files = request.FILES.getlist('audio_files')
                if audio_files:
                    # Création d'un bloc par défaut pour contenir les audios initiaux
                    bloc = Bloc.objects.create(formation=formation, name="Contenu Principal", order=1)
                    for i, audio_file in enumerate(audio_files):
                        AudioFile.objects.create(bloc=bloc, file=audio_file, order=i+1)
                
                success_message = "Formation et audios créés avec succès !"
                formation_form = FormationCreationForm()
                formations = Formation.objects.prefetch_related('blocs__audios').all().order_by('-created_at')
        
        elif 'delete_pk' in request.POST:
            pk = request.POST.get('delete_pk')
            try:
                Formation.objects.get(pk=pk).delete()
                success_message = "Formation supprimée avec succès."
                formations = Formation.objects.prefetch_related('blocs__audios').all().order_by('-created_at')
            except Formation.DoesNotExist:
                pass
    
    return render(request, 'admin/courses.html', {
        'formations': formations,
        'formation_form': formation_form,
        'success_message': success_message
    })

@login_required(login_url='/')
def admin_questionnaires(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    from .models import Formation
    import json
    
    formations = Formation.objects.all().order_by('name')
    success_message = None
    
    if request.method == 'POST':
        formation_id = request.POST.get('formation_id')
        questions_json = request.POST.get('questions_json')
        
        if formation_id and questions_json:
            try:
                formation = Formation.objects.get(pk=formation_id)
                formation.questionnaire_json = json.loads(questions_json)
                formation.save()
                success_message = f"Questionnaire enregistré pour {formation.name} !"
            except Exception:
                pass

    return render(request, 'admin/questionnaires.html', {
        'formations': formations,
        'success_message': success_message
    })

@login_required(login_url='/')
def admin_formation_detail(request, pk):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    from .models import Formation, Bloc, AudioFile
    
    formation = Formation.objects.prefetch_related('blocs__audios').get(pk=pk)
    
    success_message = None
    
    if request.method == 'POST':
        if 'add_audios' in request.POST:
            # On utilise ou crée un bloc unique par défaut pour simplifier
            bloc, created = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
            audio_files = request.FILES.getlist('audio_files')
            current_count = AudioFile.objects.filter(bloc__formation=formation).count()
            
            for i, file in enumerate(audio_files):
                AudioFile.objects.create(bloc=bloc, file=file, order=current_count + i + 1)
            
            success_message = f"{len(audio_files)} audio(s) ajouté(s) avec succès !"
            formation = Formation.objects.prefetch_related('blocs__audios').get(pk=pk)
        elif 'delete_question' in request.POST:
            q_index = int(request.POST['delete_question'])
            if 0 <= q_index < len(formation.questionnaire_json):
                del formation.questionnaire_json[q_index]
                formation.save()
                success_message = "Question supprimée !"
    
    return render(request, 'admin/formation_detail.html', {
        'formation': formation,
        'success_message': success_message
    })

def admin_results(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    from .models import ServiteurFormation
    from django.db.models import Count

    # Logique d'exportation CSV
    if request.GET.get('export') == 'pdf':
        from weasyprint import HTML, CSS
        all_results = ServiteurFormation.objects.select_related('serviteur', 'formation').order_by('-date_fin')[:100]
        for res in all_results:
            res.score_20 = round(res.score * 0.2, 1)
        
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Résultats Formations - Formation VH</title>
            <style>
                @page {
                    size: A4;
                    margin: 2cm;
                }
                body { 
                    font-family: 'Helvetica', Arial, sans-serif;
                    font-size: 12pt;
                    line-height: 1.4;
                    color: #333;
                }
                h1 { 
                    text-align: center;
                    color: #10B981;
                    font-size: 24pt;
                    margin-bottom: 10pt;
                    border-bottom: 3px solid #10B981;
                    padding-bottom: 10pt;
                }
                .header {
                    text-align: center;
                    margin-bottom: 20pt;
                }
                .date {
                    font-size: 10pt;
                    color: #666;
                    margin-bottom: 20pt;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20pt;
                }
                th {
                    background-color: #10B981;
                    color: white;
                    font-weight: bold;
                    padding: 12pt 8pt;
                    text-align: left;
                    border-bottom: 3px solid #059669;
                }
                td {
                    padding: 10pt 8pt;
                    border-bottom: 1pt solid #eee;
                }
                tr:nth-child(even) {
                    background-color: #f9f9f9;
                }
                tr:hover {
                    background-color: #f0f9f4;
                }
                .score {
                    font-weight: bold;
                    font-family: monospace;
                    font-size: 11pt;
                }
                .valide {
                    color: #059669;
                    font-weight: bold;
                }
                .echec {
                    color: #dc2626;
                    font-weight: bold;
                }
                .footer {
                    margin-top: 30pt;
                    text-align: center;
                    font-size: 9pt;
                    color: #999;
                    border-top: 1pt solid #eee;
                    padding-top: 10pt;
                }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 Rapport des Résultats Formations</h1>
                <p class="date">Généré le {{ timezone.now|date:"d/m/Y à H:i" }}</p>
            </div>
            <table>
                <tr>
                    <th>Étudiant</th>
                    <th>Formation</th>
                    <th>Score</th>
                    <th>Date Fin</th>
                    <th>Statut</th>
                </tr>
        """
        
        for res in all_results:
            statut = "✅ Validé" if res.score >= 50 else "❌ Échec"
            html_template += f"""
                <tr>
                    <td>{res.serviteur.username}</td>
                    <td>{res.formation.name}</td>
                    <td class="score">{res.score_20}/20</td>
                    <td>{res.date_fin.strftime('%d/%m/%Y %H:%M') if res.date_fin else '—'}</td>
                    <td class="{ 'valide' if res.score >= 50 else 'echec' }">{statut}</td>
                </tr>
            """
        
        html_template += """
            </table>
            <div class="footer">
                <p>Rapport généré par Formation VH - Système de suivi des formations</p>
            </div>
        </body>
        </html>
        """
        
        html = HTML(string=html_template)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="resultats_formations.pdf"'
        html.write_pdf(response, stylesheets=[CSS(string='@page { size: A4; margin: 1.5cm; }')])
        return response

    total_users = CustomUser.objects.filter(role='serviteur').count()

    stats = {
        'valide': ServiteurFormation.objects.filter(statut=1).count(),
        'echoue': ServiteurFormation.objects.filter(statut=0).count(),
        'en_cours': ServiteurFormation.objects.filter(statut=2).count(),
        'total': ServiteurFormation.objects.count()
    }

    recent_results = ServiteurFormation.objects.select_related('serviteur', 'formation').order_by('-date_debut')[:10]
    for result in recent_results:
        result.score_20 = round(result.score * 0.2, 1)
        result.display_statut = result.statut
    return render(request, 'admin/results.html', {
        'total_users': total_users,
        'stats': stats,
        'recent_results': recent_results
    })

from django.utils import timezone

@login_required(login_url='/')
def serviteur_dashboard(request):
    if request.user.role != 'serviteur':
        return redirect('/')
    from .models import ServiteurFormation, Formation
    now = timezone.now()
    formations = ServiteurFormation.objects.filter(serviteur=request.user).select_related('formation').order_by('formation__name')
    
    # Ajout d'un statut temporaire pour l'affichage
    for sf in formations:
        sf.score_20 = round(sf.score * 0.2, 1)
        if sf.statut == 1:
            sf.display_status = 'valid'
        elif sf.statut == 0:
            sf.display_status = 'expired'
        else:
            sf.display_status = 'progress'
    
    # Stats pour graphiques
    total_available = Formation.objects.count()
    total_my = len(formations)
    completed_count = sum(1 for sf in formations if sf.display_status == 'valid')
    in_progress_count = sum(1 for sf in formations if sf.display_status == 'progress')
    score_moyen = sum(sf.score_20 for sf in formations) / len(formations) if formations else 0
    
    stats = {
        'total_available': total_available,
        'total_my': total_my,
        'completed': completed_count,
        'in_progress': in_progress_count,
        'not_started': total_available - total_my,
        'score_moyen': round(score_moyen, 1)
    }
    
    return render(request, 'serviteur/dashboard.html', {
        'formations': formations,
        'stats': stats
    })

@login_required(login_url='/')
def serviteur_formations(request):
    if request.user.role != 'serviteur':
        return redirect('/')

    from .models import Formation, ServiteurFormation

    formations = Formation.objects.prefetch_related('blocs__audios').all()

    # Récupérer les progressions
    my_sfs = ServiteurFormation.objects.filter(serviteur=request.user).select_related('formation')

    # Transformer en dictionnaire simple
    progress_dict = {}
    for sf in my_sfs:
        progress_dict[sf.formation_id] = sf

    # 🔥 Préparer les données pour le template (IMPORTANT)
    formations_data = []

    for formation in formations:
        sf = progress_dict.get(formation.pk)

        if sf:
            if sf.score and sf.score > 0:
                status = 'completed'
                score20 = round(sf.score * 0.2, 1)
            elif sf.date_debut:
                status = 'in_progress'
                score20 = 0
            else:
                status = 'started'
                score20 = 0
        else:
            status = 'not_started'
            score20 = 0

        formations_data.append({
            'formation': formation,
            'status': status,
            'score20': score20
        })

    return render(request, 'serviteur/formations.html', {
        'formations_data': formations_data
    })

@login_required(login_url='/')
def serviteur_formation_detail(request, pk):
    if request.user.role != 'serviteur':
        return redirect('/')
    from .models import Formation, ServiteurFormation
    formation = Formation.objects.prefetch_related('blocs__audios').get(pk=pk)
    sf, created = ServiteurFormation.objects.get_or_create(
        serviteur=request.user,
        formation=formation,
        defaults={'date_debut': timezone.now()}
    )
    score_20 = round(sf.score * 0.2, 1) if sf.score else 0
    return render(request, 'serviteur/formation_detail.html', {'formation': formation, 'sf': sf, 'score_20': score_20})

@login_required(login_url='/')
def serviteur_questionnaire(request, pk):
    if request.user.role != 'serviteur':
        return redirect('/')
    from .models import Formation, ServiteurFormation
    formation = Formation.objects.get(pk=pk)
    sf = ServiteurFormation.objects.get(serviteur=request.user, formation=formation)
    
    if sf.score > 0:
        score_20 = round(sf.score * 0.2, 1)
        return render(request, 'serviteur/questionnaire.html', {
            'formation': formation, 
            'sf': sf, 
            'is_completed': True,
            'score_20': score_20
        })
    
    if request.method == 'POST':
        questionnaire = formation.questionnaire_json
        score = 0
        total = len(questionnaire)
        for i in range(total):
            q = questionnaire[i]
            q_type = q.get('type')
            user_answer_str = request.POST.get(f'question_{i}', '').strip().lower()
            
            # Détection automatique du type si manquant (pour compatibilité)
            if not q_type:
                q_type = 'qcm' if 'options' in q else 'text'

            if q_type == 'qcm':
                correct = q.get('correct', -1)
                user_answer = int(user_answer_str) if user_answer_str.isdigit() else -1
                if user_answer == correct:
                    score += 1
            elif q_type == 'text':
                expected = q.get('answer', '').strip().lower()
                if user_answer_str == expected:
                    score += 1
        sf.score = int((score / total) * 100)
        sf.date_soumission = timezone.now()
        sf.save()
        return redirect('traning:serviteur_dashboard')
    return render(request, 'serviteur/questionnaire.html', {'formation': formation, 'sf': sf})

from .models_vertumetre import ServiteurVertumetre
from .forms import VertumetreForm

@login_required(login_url='/')
def serviteur_vertumetre(request):
    if request.user.role != 'serviteur':
        return redirect('/')

    vert, created = ServiteurVertumetre.objects.get_or_create(serviteur=request.user)
    can_submit = vert.can_submit()
    is_submitted = not can_submit and vert.submitted_at is not None

    if request.method == 'POST' and can_submit:
        form = VertumetreForm(request.POST)
        if form.is_valid():
            form.save(request.user)
            return redirect('traning:serviteur_vertumetre')

    else:
        form = VertumetreForm()

    context = {
        'vert': vert,
        'form': form,
        'can_submit': can_submit,
        'is_submitted': is_submitted,
        'submitted_at': vert.submitted_at,
        'days_since_submit': (timezone.now() - vert.submitted_at).days if is_submitted else 0,
    }

    return render(request, 'serviteur/vertumetre.html', context)


def logout_view(request):
    logout(request)
    return redirect('traning:login')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # ✅ ADMIN
            if user.is_superuser or getattr(user, 'role', None) == 'admin':
                return redirect('traning:admin_dashboard')

            # ✅ ÉTUDIANT (SERVITEUR)
            elif getattr(user, 'role', None) == 'serviteur':
                return redirect('traning:serviteur_dashboard')

            return render(request, 'login.html', {'login_error': True})

    return render(request, 'login.html')
    return render(request, 'login.html')
