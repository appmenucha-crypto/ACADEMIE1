import csv
import json
from datetime import timedelta, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Avg, Q
from .models import CustomUser, Formation, ServiteurFormation, Bloc, AudioFile, VideoFile

from .forms import ServiteurForm, FormationCreationForm, VertumetreForm
from .models_vertumetre import ServiteurVertumetre

# Admin - Compte
from .admin_account import admin_account

from django.template.loader import render_to_string
from weasyprint import HTML


@login_required(login_url='/')
def admin_dashboard(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    serviteurs_count = CustomUser.objects.filter(role='serviteur').count()
    formations_count = Formation.objects.count()
    pending_actions = ServiteurFormation.objects.filter(statut=2).count()
    # Nombre de vertumètres réellement soumis (submitted_at rempli)
    vertumetre_count = ServiteurVertumetre.objects.filter(submitted_at__isnull=False).count()
    
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
    
    top_serviteurs = ServiteurFormation.objects.filter(date_soumission__isnull=False).values('serviteur__username').annotate(avg_score=Avg('score')/5, count=Count('id')).order_by('-avg_score')[:10]

    
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
    
    search_query = request.GET.get('q', '').strip()

    serviteurs = CustomUser.objects.filter(role='serviteur')

    if search_query:
        serviteurs = serviteurs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    serviteurs = serviteurs.order_by('-date_joined')

    
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
        elif 'delete_pk' in request.POST:
            pk = request.POST.get('delete_pk')
            try:
                serviteur = CustomUser.objects.get(id=pk, role='serviteur')
                username = serviteur.username
                serviteur.delete()
                success_message = f"Serviteur '{username}' supprimé avec succès."
            except CustomUser.DoesNotExist:
                pass

    if request.GET.get('export') == 'pdf':
        serviteurs_list = list(serviteurs)
        html_string = render_to_string(
            'admin/serviteurs_pdf.html',
            {
                'serviteurs': serviteurs_list,
                'generated_at': timezone.now(),
            },
            request=request,
        )
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="liste_serviteurs.pdf"'
        HTML(string=html_string).write_pdf(response)
        return response

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
    submissions = (
        ServiteurVertumetre.objects
        .select_related('serviteur')
        .filter(submitted_at__isnull=False)
        .order_by('-submitted_at')
    )
    
    # Stats pour graphes (7 derniers jours)
    now = timezone.now()
    start_7d = now - timedelta(days=7)
    weekly_qs = (
        ServiteurVertumetre.objects
        .filter(submitted_at__isnull=False, submitted_at__gte=start_7d)
        .extra(select={"day": "date(submitted_at)"})
    )
    submissions_per_day = {}
    for s in weekly_qs:
        day = s.submitted_at.date()
        submissions_per_day[day] = submissions_per_day.get(day, 0) + 1

    labels = []
    data = []
    for i in range(7):
        day = (start_7d + timedelta(days=i)).date()
        labels.append(day.strftime('%d/%m'))
        data.append(submissions_per_day.get(day, 0))

    submitted_count = submissions.count()

    return render(request, 'admin/vertumetres.html', {
        'submissions': submissions,
        'submitted_count': submitted_count,
        'vertumetre_labels': labels,
        'vertumetre_data': data,
    })


@login_required(login_url='/')
def admin_courses(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    success_message = None
    formation_form = FormationCreationForm()
    show_modal = False
    
    if request.method == 'POST':
        if 'create' in request.POST:
            formation_form = FormationCreationForm(request.POST, request.FILES)
            if formation_form.is_valid():
                with transaction.atomic():
                    formation = formation_form.save()
                    audio_files = request.FILES.getlist('audio_files')
                    video_files = request.FILES.getlist('video_files')
                    
                    if audio_files or video_files:
                        # Création systématique du bloc si au moins un fichier est présent
                        bloc, _ = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
                        for i, audio_file in enumerate(audio_files):
                            AudioFile.objects.create(bloc=bloc, file=audio_file, order=i+1)
                        for i, video_file in enumerate(video_files):
                            VideoFile.objects.create(bloc=bloc, file=video_file, order=i+1)
                
                success_message = "Formation créée avec succès !"
                formation_form = FormationCreationForm()
            else:
                show_modal = True
        
        elif 'delete_pk' in request.POST:
            pk = request.POST.get('delete_pk')
            try:
                Formation.objects.get(pk=pk).delete()
                success_message = "Formation supprimée avec succès."
            except Formation.DoesNotExist:
                pass

    formations = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').all().order_by('-created_at')
    
    return render(request, 'admin/courses.html', {
        'formations': formations,
        'formation_form': formation_form,
        'success_message': success_message,
        'show_modal': show_modal
    })

@login_required(login_url='/')
def admin_questionnaires(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
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
    
    formation = get_object_or_404(Formation.objects.prefetch_related('blocs__audios', 'blocs__videos'), pk=pk)
    
    success_message = None
    
    if request.method == 'POST':
        if 'add_audios' in request.POST:
            with transaction.atomic():
                bloc, created = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
                audio_files = request.FILES.getlist('audio_files')
                current_count = AudioFile.objects.filter(bloc__formation=formation).count()
                for i, file in enumerate(audio_files):
                    AudioFile.objects.create(bloc=bloc, file=file, order=current_count + i + 1)
            success_message = f"{len(audio_files)} audio(s) ajouté(s) avec succès !"
            formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
        elif 'add_videos' in request.POST:
            with transaction.atomic():
                bloc, created = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
                video_files = request.FILES.getlist('video_files')
                current_count = VideoFile.objects.filter(bloc__formation=formation).count()
                for i, file in enumerate(video_files):
                    VideoFile.objects.create(bloc=bloc, file=file, order=current_count + i + 1)
            success_message = f"{len(video_files)} vidéo(s) ajoutée(s) avec succès !"
            formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
        elif 'delete_audio' in request.POST:
            pk_audio = request.POST.get('delete_audio')
            try:
                AudioFile.objects.get(pk=pk_audio).delete()
                success_message = "Audio supprimé avec succès."
                formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
            except AudioFile.DoesNotExist:
                pass
        elif 'replace_audio' in request.POST:
            pk_audio = request.POST.get('replace_audio')
            new_file = request.FILES.get('new_audio_file')
            if new_file:
                try:
                    audio = AudioFile.objects.get(pk=pk_audio)
                    audio.file = new_file
                    audio.save()
                    success_message = "Audio remplacé avec succès."
                    formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
                except AudioFile.DoesNotExist:
                    pass
        elif 'replace_video' in request.POST:
            pk_video = request.POST.get('replace_video')
            new_file = request.FILES.get('new_video_file')
            if new_file:
                try:
                    video = VideoFile.objects.get(pk=pk_video)
                    video.file = new_file
                    video.save()
                    success_message = "Vidéo remplacée avec succès."
                    formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
                except VideoFile.DoesNotExist:
                    pass
        elif 'delete_video' in request.POST:
            pk_video = request.POST.get('delete_video')
            try:
                VideoFile.objects.get(pk=pk_video).delete()
                success_message = "Vidéo supprimée avec succès."
                formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
            except VideoFile.DoesNotExist:
                pass
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

@login_required(login_url='/')
def admin_results(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    from django.utils import timezone
    from django.db.models import Avg, Count
    from django.http import HttpResponse
    from weasyprint import HTML
    from django.template.loader import render_to_string

    # =========================
    # PARAMÈTRES
    # =========================

    filtre = request.GET.get('filtre', '')
    only_with_avg = request.GET.get('only_with_avg', 'all')
    show_averages = request.GET.get('show_averages', '0')

    selected_month = int(
        request.GET.get('month', timezone.now().month)
    )

    selected_semester = int(
        request.GET.get('semester', 1)
    )

    # =========================
    # DATES PERSONNALISÉES (PÉRIODE SEMESTRE)
    # =========================
    # Permet à l'admin de définir une période manuellement au lieu du semestre 1/2 figé.
    # Utilisation via GET : start_date=YYYY-MM-DD et end_date=YYYY-MM-DD
    period_start_str = request.GET.get('start_date', '').strip()
    period_end_str = request.GET.get('end_date', '').strip()

    period_start = None
    period_end = None

    if period_start_str:
        try:
            period_start = timezone.datetime.fromisoformat(period_start_str)
        except Exception:
            period_start = None

    if period_end_str:
        try:
            period_end = timezone.datetime.fromisoformat(period_end_str)
        except Exception:
            period_end = None


    # =========================
    # LISTE DES MOIS
    # =========================

    months = [
        {"value": 1, "label": "Janvier"},
        {"value": 2, "label": "Février"},
        {"value": 3, "label": "Mars"},
        {"value": 4, "label": "Avril"},
        {"value": 5, "label": "Mai"},
        {"value": 6, "label": "Juin"},
        {"value": 7, "label": "Juillet"},
        {"value": 8, "label": "Août"},
        {"value": 9, "label": "Septembre"},
        {"value": 10, "label": "Octobre"},
        {"value": 11, "label": "Novembre"},
        {"value": 12, "label": "Décembre"},
    ]

    # =========================
    # DATE ACTUELLE
    # =========================

    now = timezone.localtime(timezone.now())

    # =========================
    # MOIS CHOISI
    # =========================

    month_start = now.replace(
        month=selected_month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    if selected_month == 12:

        next_month_start = month_start.replace(
            year=month_start.year + 1,
            month=1
        )

    else:

        next_month_start = month_start.replace(
            month=selected_month + 1
        )

    # =========================
    # SEMESTRE / PÉRIODE
    # =========================

    semestre = selected_semester

    # Par défaut: calcul semestre 1/2 (figé comme avant)
    if semestre == 1:

        sem_start = now.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        sem_end = now.replace(
            month=7,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    else:

        sem_start = now.replace(
            month=7,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        sem_end = now.replace(
            year=now.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    # Si l'admin a fourni start_date/end_date, on remplace sem_start/sem_end.
    # end_date est considéré comme date de fin incluse -> on passe en borne exclusive (+1 jour).
    if period_start and period_end:
        sem_start = period_start
        sem_end = period_end + timezone.timedelta(days=1)
    elif period_start:
        sem_start = period_start
    elif period_end:
        sem_end = period_end + timezone.timedelta(days=1)

    # Normalisation: s'assurer que les bornes ont des tz-aware datetime
    # (si fromisoformat renvoie du naive, on suppose le fuseau courant).
    if sem_start and timezone.is_naive(sem_start):
        sem_start = timezone.make_aware(sem_start, timezone.get_current_timezone())

    if sem_end and timezone.is_naive(sem_end):
        sem_end = timezone.make_aware(sem_end, timezone.get_current_timezone())

    # Sécurité: si l'intervalle est inversé, on conserve l'ordre.
    if sem_start and sem_end and sem_end < sem_start:
        sem_start, sem_end = sem_end, sem_start




    # =========================
    # STATS
    # =========================

    stats = {
        'valide': ServiteurFormation.objects.filter(statut=1).count(),
        'echoue': ServiteurFormation.objects.filter(statut=0).count(),
        'en_cours': ServiteurFormation.objects.filter(statut=2).count(),
        'total': ServiteurFormation.objects.count()
    }

    # =========================
    # RÉSULTATS RÉCENTS
    # =========================

    recent_results = (
        ServiteurFormation.objects
        .select_related('serviteur', 'formation')
        .order_by('-date_debut')
    )

    if filtre == 'valide':
        recent_results = recent_results.filter(statut=1)

    elif filtre == 'echec':
        recent_results = recent_results.filter(statut=0)

    elif filtre == 'en_cours':
        recent_results = recent_results.filter(statut=2)

    recent_results = recent_results[:50]

    for result in recent_results:
        result.score_20 = round(result.score * 0.2, 1)
        result.display_statut = result.statut

    # =========================
    # BASE QUERYSET
    # =========================

    base_qs = ServiteurFormation.objects.select_related(
        'serviteur'
    ).all()

    if filtre == 'valide':
        base_qs = base_qs.filter(statut=1)

    elif filtre == 'echec':
        base_qs = base_qs.filter(statut=0)

    elif filtre == 'en_cours':
        base_qs = base_qs.filter(statut=2)

    # =========================
    # MOYENNES MENSUELLES
    # =========================

    monthly = (

        base_qs.filter(
            date_soumission__gte=month_start,
            date_soumission__lt=next_month_start
        )

        .values('serviteur_id')

        .annotate(
            avg_month=Avg('score')
        )

        .annotate(
            cnt_month=Count('id')
        )

    )

    # =========================
    # MOYENNES SEMESTRIELLES
    # =========================

    semestrial = (

        base_qs.filter(
            date_soumission__gte=sem_start,
            date_soumission__lt=sem_end
        )

        .values('serviteur_id')

        .annotate(
            avg_sem=Avg('score')
        )

        .annotate(
            cnt_sem=Count('id')
        )

    )

    monthly_map = {
        row['serviteur_id']: row
        for row in monthly
    }

    sem_map = {
        row['serviteur_id']: row
        for row in semestrial
    }

    # =========================
    # ÉTUDIANTS
    # =========================

    serviteurs = list(

        CustomUser.objects.filter(
            role='serviteur'
        ).order_by('-date_joined')

    )

    results_by_student = []

    for s in serviteurs:

        m = monthly_map.get(s.id)
        sem = sem_map.get(s.id)

        avg_month_score = (
            (m['avg_month'] or 0)
            if m else 0
        )

        avg_sem_score = (
            (sem['avg_sem'] or 0)
            if sem else 0
        )

        results_by_student.append({

            'serviteur': s,

            'avg_month_20':
                round(avg_month_score * 0.2, 1)
                if m else 0,

            'cnt_month':
                m['cnt_month']
                if m else 0,

            'avg_sem_20':
                round(avg_sem_score * 0.2, 1)
                if sem else 0,

            'cnt_sem':
                sem['cnt_sem']
                if sem else 0,

        })

    # =========================
    # TRI
    # =========================

    results_by_student.sort(

        key=lambda x: (

            x.get('avg_month_20', 0),

            x.get('avg_sem_20', 0),

            x['serviteur'].username

        ),

        reverse=True

    )

    # =========================
    # FILTRE MOYENNES
    # =========================

    if only_with_avg == 'month':

        results_by_student = [

            r for r in results_by_student

            if (
                (r.get('cnt_month', 0) or 0) > 0
                and
                (r.get('avg_month_20', 0) or 0) >= 10
            )

        ]

    elif only_with_avg == 'sem':

        results_by_student = [

            r for r in results_by_student

            if (
                (r.get('cnt_sem', 0) or 0) > 0
                and
                (r.get('avg_sem_20', 0) or 0) >= 10
            )

        ]

    # =========================
    # EXPORT PDF
    # =========================

    if request.GET.get('export') == 'pdf':

        # PDF MOYENNES
        if show_averages == '1':

            html_string = render_to_string(

                'admin/moyennes_pdf.html',

                {
                    'results_by_student':
                        results_by_student,

                    'selected_month':
                        selected_month,

                    'selected_semester':
                        selected_semester,

                    'generated_at':
                        timezone.now(),
                }

            )

            response = HttpResponse(
                content_type='application/pdf'
            )

            response['Content-Disposition'] = (
                'attachment; filename="moyennes_etudiants.pdf"'
            )

            HTML(
                string=html_string
            ).write_pdf(response)

            return response

        # PDF RESULTATS
        else:

            all_results = (

                ServiteurFormation.objects
                .select_related(
                    'serviteur',
                    'formation'
                )
                .order_by('-date_debut')

            )

            if filtre == 'valide':
                all_results = all_results.filter(statut=1)

            elif filtre == 'echec':
                all_results = all_results.filter(statut=0)

            elif filtre == 'en_cours':
                all_results = all_results.filter(statut=2)

            for res in all_results:
                res.score_20 = round(res.score * 0.2, 1)

            filtre_display = {

                'valide': 'Validés',

                'echec': 'Échecs',

                'en_cours': 'En cours',

            }.get(filtre, 'Tous')

            html_string = render_to_string(

                'admin/results_pdf.html',

                {
                    'results': all_results,
                    'generated_at': timezone.now(),
                    'filtre': filtre,
                    'filtre_display': filtre_display,
                }

            )

            response = HttpResponse(
                content_type='application/pdf'
            )

            filename = (
                f'resultats_formations_'
                f'{filtre_display.lower()}.pdf'
            )

            response['Content-Disposition'] = (
                f'attachment; filename="{filename}"'
            )

            HTML(
                string=html_string
            ).write_pdf(response)

            return response

    # =========================
    # TEMPLATE
    # =========================

    return render(

        request,

        'admin/results.html',

        {
            'total_users': CustomUser.objects.filter(
                role='serviteur'
            ).count(),

            'stats': stats,

            'recent_results': recent_results,

            'filtre': filtre,

            'results_by_student': results_by_student,

            'semestre': semestre,

            'month_label': month_start.strftime('%B %Y').capitalize(),

            'show_averages': show_averages,

            'months': months,

            'selected_month': selected_month,

            'selected_semester': selected_semester,

            'only_with_avg': only_with_avg,
        }
    )




from django.utils import timezone

@login_required(login_url='/')
def serviteur_dashboard(request):
    if request.user.role != 'serviteur':
        return redirect('/')
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

    formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)

    sf, created = ServiteurFormation.objects.get_or_create(
        serviteur=request.user,
        formation=formation,
        defaults={'date_debut': timezone.now()}
    )

    # ✅ Si l'objet existait déjà mais sans date_debut, on démarre quand même le délai au clic.
    if sf.date_debut is None:
        sf.date_debut = timezone.now()
        # date_limite sera recalculée dans save()
        sf.save()

    # ✅ Mise à jour automatique: si la date limite est dépassée et aucune soumission
    if sf.statut == 2 and sf.date_soumission is None and sf.date_limite and sf.date_limite <= timezone.now():
        sf.statut = 0  # Échoué
        sf.save(update_fields=["statut"])

    score_20 = round(sf.score * 0.2, 1) if sf.score else 0
    return render(request, 'serviteur/formation_detail.html', {'formation': formation, 'sf': sf, 'score_20': score_20})


@login_required(login_url='/')
def serviteur_questionnaire(request, pk):
    if request.user.role != 'serviteur':
        return redirect('/')
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
        sf.score = int((score / total) * 100) if total > 0 else 0
        sf.date_soumission = timezone.now()
        sf.save()
        return redirect('traning:serviteur_dashboard')
    return render(request, 'serviteur/questionnaire.html', {'formation': formation, 'sf': sf})




@login_required(login_url='/')
def serviteur_vertumetre(request):

    if request.user.role != 'serviteur':
        return redirect('/')

    vert, created = ServiteurVertumetre.objects.get_or_create(
        serviteur=request.user
    )

    # =========================
    # Conversion JSON sécurisée
    # =========================
    if vert.answers:

        # Si answers est une chaîne JSON
        if isinstance(vert.answers, str):

            try:
                vert.answers = json.loads(vert.answers)

            except Exception:
                vert.answers = {}

    can_submit = vert.can_submit()

    is_submitted = (
        not can_submit and
        vert.submitted_at is not None
    )

    # =========================
    # Soumission formulaire
    # =========================
    if request.method == 'POST' and can_submit:

        form = VertumetreForm(request.POST)

        if form.is_valid():

            form.save(request.user)

            return redirect('traning:serviteur_vertumetre')

    else:

        form = VertumetreForm()

    # =========================
    # Context
    # =========================
    context = {
        'vert': vert,
        'form': form,
        'can_submit': can_submit,
        'is_submitted': is_submitted,
        'submitted_at': vert.submitted_at,
        'days_since_submit': (
            (timezone.now() - vert.submitted_at).days
            if is_submitted else 0
        ),
        'submissions_count': vert.submissions_count or 0,
    }

    return render(
        request,
        'serviteur/vertumetre.html',
        context
    )



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
