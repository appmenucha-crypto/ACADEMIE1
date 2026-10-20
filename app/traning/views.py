import csv
import json
import logging
from datetime import timedelta, datetime
from urllib.parse import urlencode
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import _get_user_session_key
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.backends.base import CreateError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from django.http import HttpResponse, HttpResponseRedirect, HttpResponsePermanentRedirect, JsonResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Avg, Q, Max
from django.db.utils import OperationalError
from django.core.files.storage import default_storage
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from .models import CustomUser, Formation, ServiteurFormation, Bloc, AudioFile, VideoFile, Departement, ReferentMessage

logger = logging.getLogger(__name__)

from .forms import ServiteurForm, FormationCreationForm, FormationEditForm, VertumetreForm, AdminReferantForm
from .models_vertumetre import ServiteurVertumetre, VertumetreSubmission
from .quiz import serviteur_answers_summary

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
    vertumetre_count = ServiteurVertumetre.objects.filter(last_submitted_at__isnull=False).count()
    # Formations dont le questionnaire n'a jamais été transmis
    not_transmitted_count = ServiteurFormation.objects.filter(statut=3).count()
    
    # Graph data
    sf_stats = {
        'total': ServiteurFormation.objects.filter(date_soumission__isnull=False).count(),
        'avg_score': round((ServiteurFormation.objects.filter(date_soumission__isnull=False).aggregate(avg=Avg('score'))['avg'] or 0) * 0.2, 1),
        'validated': ServiteurFormation.objects.filter(statut=1).count(),
        'failed': ServiteurFormation.objects.filter(statut=0).count(),
        'not_transmitted': ServiteurFormation.objects.filter(statut=3).count(),
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
        'vertumetre_count': vertumetre_count,
        'not_transmitted_count': not_transmitted_count
    })

@login_required(login_url='/')
def admin_serviteurs(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    search_query = request.GET.get('q', '').strip()
    departement_id = request.GET.get('departement', '').strip()

    serviteurs = CustomUser.objects.filter(role='serviteur')

    if departement_id:
        # Robustesse: ne pas casser si departement_id est invalide
        try:
            serviteurs = serviteurs.filter(departement_id=int(departement_id))
        except (TypeError, ValueError):
            serviteurs = serviteurs.none()


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

    # Forcer le queryset du champ FK departement pour que la liste existe aussi
    # dans le formulaire de création/modification (modal).
    departements_order = [
        "PORTIERS",
        "BLOOM",
        "LOGISTIQUE",
        "EVANGELISATION",
        "SOCIAL",
        "ECODIM",
        "COMMUNICATION",
        "ELEEO",
        "ADN",
        "GESTION DE CULTE",
        "EDEN 1",
        "MUSIQUE",
        "SAINTE CENE",
        "BAPTEME",
        "ADA",
        "MRES",
        "INTERCESSION",
    ]

    departements_qs = Departement.objects.all()
    departements_map = {str(d.name).strip().upper(): d for d in departements_qs}
    ordered = [departements_map[name] for name in departements_order if name in departements_map]
    ordered_ids = [d.id for d in ordered]
    if ordered_ids:
        departements_qs = Departement.objects.filter(id__in=ordered_ids)

    if 'departement' in serviteur_form.fields:
        serviteur_form.fields['departement'].queryset = departements_qs


    
    if request.method == 'POST':
        if 'create' in request.POST:
            serviteur_form = ServiteurForm(request.POST, request.FILES)
            if serviteur_form.is_valid():
                serviteur = serviteur_form.save()
                temp_pass = getattr(serviteur, '_temp_password', 'généré')
                success_message = f"Serviteur '{serviteur.username}' créé avec succès !"
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

    # Liste de départements (affichage fixe demandé par l’équipe)
    departements_order = [
        "PORTIERS",
        "BLOOM",
        "LOGISTIQUE",
        "EVANGELISATION",
        "SOCIAL",
        "ECODIM",
        "COMMUNICATION",
        "ELEEO",
        "ADN",
        "GESTION DE CULTE",
        "EDEN 1",
        "MUSIQUE",
        "SAINTE CENE",
        "BAPTEME",
        "ADA",
        "MRES",
        "INTERCESSION",
    ]

    # On récupère ce qui existe en base, puis on applique l’ordre demandé.
    departements = list(Departement.objects.all())
    departements_map = {str(d.name).strip().upper(): d for d in departements}
    departements = [
        departements_map[name] for name in departements_order
        if name in departements_map
    ]

    # Fallback : si aucun département correspondant n’existe encore en base,
    # on affiche tous les départements (cas de déploiement initial).
    if not departements:
        departements = Departement.objects.all().order_by('name')


    return render(request, 'admin/serviteurs.html', {
        'serviteurs': serviteurs,
        'serviteur_form': serviteur_form,
        'success_message': success_message,
        'departements': departements,
        'selected_departement_id': departement_id,
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
    
    # Grouper par serviteur : un par ligne
    vertumetres = (
        ServiteurVertumetre.objects
        .select_related('serviteur')
        .prefetch_related('submissions')
        .annotate(last_sub=Max('submissions__submitted_at'))
        .filter(last_sub__isnull=False)
        .order_by('-last_sub')
    )
    
    # Stats pour graphes (7 derniers jours)
    now = timezone.now()
    start_7d = now - timedelta(days=7)
    weekly_qs = (
        VertumetreSubmission.objects
        .filter(submitted_at__gte=start_7d)
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

    submitted_count = vertumetres.count()
    
    # Moyenne soumissions par serviteur
    avg_per_serviteur = round(submitted_count / vertumetres.count(), 1) if vertumetres.count() > 0 else 0

    return render(request, 'admin/vertumetres.html', {
        'vertumetres': vertumetres,
        'submitted_count': submitted_count,
        'avg_per_serviteur': avg_per_serviteur,
        'vertumetre_labels': labels,
        'vertumetre_data': data,
    })


@login_required(login_url='/')
def admin_resultat_detail(request, pk):
    """Détail d'un serviteur : questionnaires soumis (vert/rouge) et vertumètre."""
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    serviteur = get_object_or_404(
        CustomUser.objects.select_related('departement').prefetch_related('referant'),
        pk=pk, role='serviteur',
    )

    sf_list = list(
        ServiteurFormation.objects
        .filter(serviteur=serviteur)
        .select_related('formation')
        .order_by('-date_soumission', '-date_debut')
    )

    submitted = []
    not_transmitted = []
    for sf in sf_list:
        sf.score_20 = round(sf.score * 0.2, 1)
        summary = serviteur_answers_summary(sf.formation, sf.html_responses)
        sf.answers_total = summary['total']
        sf.answers_correct = summary['correct']
        sf.answers_incorrect = summary['incorrect']
        sf.answers_detail = summary['detail']
        sf.has_detail = summary['total'] > 0
        if sf.date_soumission is not None:
            submitted.append(sf)
        elif sf.display_status == 'not_transmitted':
            not_transmitted.append(sf)

    stats = {
        'total': len(sf_list),
        'valid': sum(1 for s in sf_list if s.display_status == 'valid'),
        'failed': sum(1 for s in sf_list if s.display_status == 'failed'),
        'progress': sum(1 for s in sf_list if s.display_status == 'progress'),
        'not_transmitted': sum(1 for s in sf_list if s.display_status == 'not_transmitted'),
        'submitted': len(submitted),
    }
    stats['score_moyen'] = (
        round(sum(s.score_20 for s in submitted) / len(submitted), 1) if submitted else 0
    )

    # Vertumètre du serviteur
    vertumetre = ServiteurVertumetre.objects.filter(serviteur=serviteur).first()
    vertumetre_submissions = (
        vertumetre.submissions.all() if vertumetre else []
    )

    return render(request, 'admin/resultat_detail.html', {
        'serviteur': serviteur,
        'sf_list': sf_list,
        'submitted_list': submitted,
        'not_transmitted_list': not_transmitted,
        'stats': stats,
        'vertumetre': vertumetre,
        'vertumetre_submissions': vertumetre_submissions,
    })


@login_required(login_url='/')
def admin_vertumetre_detail(request, pk):
    """Détail de toutes les soumissions d'un serviteur."""
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    vertumetre = get_object_or_404(
        ServiteurVertumetre.objects.select_related('serviteur').prefetch_related('submissions'),
        pk=pk
    )
    
    submissions = vertumetre.submissions.all()
    
    return render(request, 'admin/vertumetre_detail.html', {
        'vertumetre': vertumetre,
        'submissions': submissions,
    })


@login_required(login_url='/')
def admin_courses(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    success_message = None
    error_message = None
    formation_form = FormationCreationForm()
    show_modal = False
    edit_form = None
    edit_formation = None

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

                success_message = (
                    f"Formation « {formation.name} » créée avec succès !"
                    + ("" if formation.is_active else " Elle est inactive : invisible chez les serviteurs jusqu'à activation.")
                )
                formation_form = FormationCreationForm()
            else:
                show_modal = True

        elif 'toggle_active' in request.POST:
            pk = request.POST.get('toggle_active')
            try:
                formation = Formation.objects.get(pk=pk)
            except (Formation.DoesNotExist, ValueError):
                error_message = "Formation introuvable."
            else:
                formation.is_active = not formation.is_active
                formation.save(update_fields=['is_active'])
                success_message = (
                    f"Formation « {formation.name} » activée : elle est maintenant visible chez les serviteurs."
                    if formation.is_active
                    else f"Formation « {formation.name} » désactivée : elle reste gérable ici mais n'apparaît plus chez les serviteurs."
                )

        elif 'edit' in request.POST:
            pk = request.POST.get('edit')
            try:
                edit_formation = Formation.objects.get(pk=pk)
            except (Formation.DoesNotExist, ValueError):
                error_message = "Formation introuvable."
            else:
                edit_form = FormationEditForm(request.POST, instance=edit_formation)
                if edit_form.is_valid():
                    edit_form.save()
                    success_message = f"Formation « {edit_formation.name} » mise à jour."
                    edit_formation = None
                    edit_form = None
                else:
                    show_modal = True

        elif 'delete_pk' in request.POST:
            pk = request.POST.get('delete_pk')
            try:
                formation = Formation.objects.get(pk=pk)
                name = formation.name
                formation.delete()
                success_message = f"Formation « {name} » supprimée avec succès."
            except (Formation.DoesNotExist, ValueError):
                pass

    formations = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').all().order_by('-created_at')

    # Filtre d'affichage : tous / actives / inactives
    etat = request.GET.get('etat', 'tous').strip().lower()
    if etat == 'actif':
        formations = formations.filter(is_active=True)
    elif etat == 'inactif':
        formations = formations.filter(is_active=False)
    else:
        etat = 'tous'

    compteurs = {
        'tous': Formation.objects.count(),
        'actif': Formation.objects.filter(is_active=True).count(),
        'inactif': Formation.objects.filter(is_active=False).count(),
    }

    return render(request, 'admin/courses.html', {
        'formations': formations,
        'formation_form': formation_form,
        'edit_form': edit_form,
        'edit_formation': edit_formation,
        'success_message': success_message,
        'error_message': error_message,
        'show_modal': show_modal,
        'etat': etat,
        'compteurs': compteurs,
    })

@login_required(login_url='/')
def admin_questionnaires(request):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    formations = Formation.objects.all().order_by('name')
    success_message = None
    error_message = None

    if request.method == 'POST':
        formation_id = request.POST.get('formation_id')
        questions_json = request.POST.get('questions_json')
        html_file = request.FILES.get('html_file')
        clear_html = request.POST.get('clear_html')

        # --- Import / remplacement du questionnaire HTML ---
        if clear_html and formation_id:
            try:
                formation = Formation.objects.get(pk=formation_id)
                formation.questionnaire_html = ''
                formation.questionnaire_date = None
                formation.save()
                success_message = f"Questionnaire HTML retiré pour {formation.name}."
                formations = Formation.objects.all().order_by('name')
            except Formation.DoesNotExist:
                error_message = "Formation introuvable."
        elif html_file and formation_id:
            try:
                formation = Formation.objects.get(pk=formation_id)
                html_content = html_file.read().decode('utf-8', errors='replace')
                formation.questionnaire_html = html_content
                formation.questionnaire_date = timezone.now()
                formation.save()
                success_message = f"Questionnaire HTML importé pour {formation.name} !"
                formations = Formation.objects.all().order_by('name')
            except Formation.DoesNotExist:
                error_message = "Formation introuvable."
            except Exception:
                error_message = "Erreur lors de l'import du fichier HTML."
        elif formation_id and questions_json:
            try:
                formation = Formation.objects.get(pk=formation_id)
                formation.questionnaire_json = json.loads(questions_json)
                formation.save()
                success_message = f"Questionnaire enregistré pour {formation.name} !"
            except Exception:
                error_message = "Erreur lors de l'enregistrement du questionnaire JSON."

    # Formations disposant déjà d'un questionnaire HTML importé
    formations_with_html = [f.id for f in formations if f.questionnaire_html]

    return render(request, 'admin/questionnaires.html', {
        'formations': formations,
        'formations_with_html': formations_with_html,
        'success_message': success_message,
        'error_message': error_message,
    })

@login_required(login_url='/')
def admin_formation_detail(request, pk):
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')
    
    formation = get_object_or_404(Formation.objects.prefetch_related('blocs__audios', 'blocs__videos'), pk=pk)
    
    success_message = None
    
    if request.method == 'POST':
        if 'toggle_active' in request.POST:
            formation.is_active = not formation.is_active
            formation.save(update_fields=['is_active'])
            success_message = (
                f"Formation « {formation.name} » activée : elle est maintenant visible chez les serviteurs."
                if formation.is_active
                else f"Formation « {formation.name} » désactivée : elle reste gérable ici mais n'apparaît plus chez les serviteurs."
            )
            formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
        elif 'add_audios' in request.POST:
            audio_files = request.FILES.getlist('audio_files')
            # Les fichiers sont copiés sur le disque AVANT la transaction :
            # sinon le verrou d'écriture SQLite est tenu pendant tout l'upload
            # et bloque les autres utilisateurs (connexions, messages...).
            noms_audios = [
                default_storage.save('audios/' + f.name, f, max_length=100)
                for f in audio_files
            ]
            with transaction.atomic():
                bloc, created = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
                current_count = AudioFile.objects.filter(bloc__formation=formation).count()
                for i, nom in enumerate(noms_audios):
                    AudioFile.objects.create(bloc=bloc, file=nom, order=current_count + i + 1)
            success_message = f"{len(audio_files)} audio(s) ajouté(s) avec succès !"
            formation = Formation.objects.prefetch_related('blocs__audios', 'blocs__videos').get(pk=pk)
        elif 'add_videos' in request.POST:
            video_files = request.FILES.getlist('video_files')
            # Même principe que pour les audios : écriture disque hors transaction.
            noms_videos = [
                default_storage.save('videos/' + f.name, f, max_length=100)
                for f in video_files
            ]
            with transaction.atomic():
                bloc, created = Bloc.objects.get_or_create(formation=formation, name="Contenu Principal", defaults={'order': 1})
                current_count = VideoFile.objects.filter(bloc__formation=formation).count()
                for i, nom in enumerate(noms_videos):
                    VideoFile.objects.create(bloc=bloc, file=nom, order=current_count + i + 1)
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

    departement_id = request.GET.get('departement', '').strip()

    # Départements pour le filtre UI
    departements = list(Departement.objects.all().order_by('name'))
    selected_departement_id = departement_id

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
        'non_transmis': ServiteurFormation.objects.filter(statut=3).count(),
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

    # Filtre département (admin/results)
    if departement_id:
        try:
            departement_pk = int(departement_id)
            recent_results = recent_results.filter(serviteur__departement_id=departement_pk)
        except (TypeError, ValueError):
            recent_results = recent_results.none()

    # Recherche par nom (prénom, nom, identifiant ou e-mail)
    search_query = request.GET.get('q', '').strip()
    if search_query:
        recent_results = recent_results.filter(
            Q(serviteur__first_name__icontains=search_query)
            | Q(serviteur__last_name__icontains=search_query)
            | Q(serviteur__username__icontains=search_query)
            | Q(serviteur__email__icontains=search_query)
        )


    if filtre == 'valide':
        recent_results = recent_results.filter(statut=1)

    elif filtre == 'echec':
        recent_results = recent_results.filter(statut=0)

    elif filtre == 'non_transmis':
        recent_results = recent_results.filter(statut=3)

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

    # Filtre département pour les stats / moyennes
    if departement_id:
        try:
            departement_pk = int(departement_id)
            base_qs = base_qs.filter(serviteur__departement_id=departement_pk)
        except (TypeError, ValueError):
            base_qs = base_qs.none()

    # Recherche par nom (stats / moyennes)
    if search_query:
        base_qs = base_qs.filter(
            Q(serviteur__first_name__icontains=search_query)
            | Q(serviteur__last_name__icontains=search_query)
            | Q(serviteur__username__icontains=search_query)
            | Q(serviteur__email__icontains=search_query)
        )


    if filtre == 'valide':
        base_qs = base_qs.filter(statut=1)

    elif filtre == 'echec':
        base_qs = base_qs.filter(statut=0)

    elif filtre == 'non_transmis':
        base_qs = base_qs.filter(statut=3)

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

            elif filtre == 'non_transmis':
                all_results = all_results.filter(statut=3)

            elif filtre == 'en_cours':
                all_results = all_results.filter(statut=2)

            if departement_id:
                try:
                    all_results = all_results.filter(
                        serviteur__departement_id=int(departement_id))
                except (TypeError, ValueError):
                    all_results = all_results.none()

            if search_query:
                all_results = all_results.filter(
                    Q(serviteur__first_name__icontains=search_query)
                    | Q(serviteur__last_name__icontains=search_query)
                    | Q(serviteur__username__icontains=search_query)
                    | Q(serviteur__email__icontains=search_query)
                )

            for res in all_results:
                res.score_20 = round(res.score * 0.2, 1)

            filtre_display = {

                'valide': 'Validés',

                'echec': 'Échecs',

                'non_transmis': 'Non transmis',

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

    # Paramètres conservés lors du changement de filtre rapide (statut / moyennes)
    preserved_params = {
        key: value for key, value in request.GET.items()
        if key not in ('filtre', 'show_averages', 'export')
    }
    filter_query = urlencode(preserved_params)
    clear_query = urlencode({
        key: value for key, value in request.GET.items()
        if key not in ('q', 'export')
    })

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

            'search_query': search_query,

            'filter_query': filter_query,

            'clear_query': clear_query,

            'results_by_student': results_by_student,

            'semestre': semestre,

            'month_label': month_start.strftime('%B %Y').capitalize(),

            'show_averages': show_averages,

            'months': months,

            'selected_month': selected_month,

            'selected_semester': selected_semester,

            'only_with_avg': only_with_avg,

            # ✅ nécessaire pour remplir le select département
            'departements': departements,
            'selected_departement_id': selected_departement_id,
        }
    )




from django.utils import timezone

@login_required(login_url='/')
def serviteur_dashboard(request):
    if request.user.role != 'serviteur':
        return redirect('/')
    now = timezone.now()
    formations = ServiteurFormation.objects.filter(
        serviteur=request.user, formation__is_active=True
    ).select_related('formation').order_by('formation__name')
    
    # Ajout d'un statut temporaire pour l'affichage
    for sf in formations:
        sf.score_20 = round(sf.score * 0.2, 1)
    
    # Stats pour graphiques
    total_available = Formation.objects.filter(is_active=True).count()
    total_my = len(formations)
    completed_count = sum(1 for sf in formations if sf.display_status == 'valid')
    in_progress_count = sum(1 for sf in formations if sf.display_status == 'progress')
    
    # Score moyen uniquement sur les formations soumises (qui ont un score)
    completed_formations = [sf for sf in formations if sf.display_status in ('valid', 'failed')]
    score_moyen = sum(sf.score_20 for sf in completed_formations) / len(completed_formations) if completed_formations else 0
    
    stats = {
        'total_available': total_available,
        'total_my': total_my,
        'completed': completed_count,
        'in_progress': in_progress_count,
        'not_started': max(0, total_available - total_my),
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

    formations = Formation.objects.filter(is_active=True).prefetch_related('blocs__audios').all()

    # Récupérer les progressions
    my_sfs = ServiteurFormation.objects.filter(
        serviteur=request.user, formation__is_active=True
    ).select_related('formation')

    # Transformer en dictionnaire simple
    progress_dict = {}
    for sf in my_sfs:
        progress_dict[sf.formation_id] = sf

    # 🔥 Préparer les données pour le template (IMPORTANT)
    formations_data = []

    for formation in formations:
        sf = progress_dict.get(formation.pk)

        if sf:
            # Le cours est considéré terminé dès que la soumission est enregistrée
            # (note affichée par le HTML importé comprise), même si la note est de 0.
            if sf.date_debut is None:
                status = 'started'
            else:
                status = {
                    'valid': 'completed',
                    'failed': 'completed',
                    'not_transmitted': 'not_transmitted',
                    'progress': 'in_progress',
                }.get(sf.display_status, 'in_progress')
            score20 = round(sf.score * 0.2, 1) if sf.date_soumission is not None else 0
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

    # Les formations inactivées par l'administration ne sont plus accessibles aux serviteurs
    formation = get_object_or_404(
        Formation.objects.prefetch_related('blocs__audios', 'blocs__videos'),
        pk=pk, is_active=True,
    )

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
        sf.statut = 3  # Non transmis (délai dépassé, questionnaire jamais soumis)
        sf.save(update_fields=["statut"])

    score_20 = round(sf.score * 0.2, 1) if sf.score else 0
    return render(request, 'serviteur/formation_detail.html', {
        'formation': formation,
        'sf': sf,
        'score_20': score_20,
        'has_result': sf.date_soumission is not None,
    })


def _coerce_score(score_raw):
    """Convertit une valeur de note (/100) en entier borné, ou None si inexploitable."""
    if score_raw is None or score_raw == '':
        return None
    try:
        return int(round(float(str(score_raw).replace(',', '.'))))
    except (TypeError, ValueError):
        return None


def _record_html_result(sf, responses, score_raw=None):
    """Enregistre les réponses du questionnaire HTML importé et clôture le cours.

    Le statut (validé / échoué) est recalculé dans ServiteurFormation.save()
    à partir de date_soumission, comme pour le questionnaire JSON.
    """
    responses = responses if isinstance(responses, dict) else {}
    score = _coerce_score(score_raw)
    if score is None:
        # Sans note explicite, une soumission avec réponses vaut 100/100.
        # Si le cours est déjà noté, on conserve la note existante.
        score = sf.score if sf.date_soumission is not None else (100 if responses else 0)
    score = max(0, min(100, score))

    sf.score = score
    if sf.date_soumission is None:
        sf.date_soumission = timezone.now()
    if responses or not sf.html_responses:
        sf.html_responses = responses or sf.html_responses
    sf.save()
    return score


@login_required(login_url='/')
@require_POST
def serviteur_questionnaire_html_result(request, pk):
    """Reçoit la note affichée par le questionnaire HTML importé.

    Appelé en AJAX lorsque le HTML importé signale la fin de l'épreuve et sa note,
    afin que cette note apparaisse partout (dashboard, formations, résultats admin)
    et que le cours soit clôturé exactement comme après un questionnaire JSON.
    """
    if request.user.role != 'serviteur':
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    try:
        formation = Formation.objects.get(pk=pk, is_active=True)
    except Formation.DoesNotExist:
        return JsonResponse({'error': 'Formation introuvable'}, status=404)

    if 'application/json' in (request.content_type or ''):
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            payload = {}
    else:
        payload = request.POST.dict()
    if not isinstance(payload, dict):
        payload = {}

    score_keys = ('score', 'note', 'resultat', 'score_20', 'total')

    responses = payload.get('responses')
    if isinstance(responses, str):
        try:
            responses = json.loads(responses)
        except ValueError:
            responses = {}
    if not isinstance(responses, dict):
        responses = {}
    if not responses:
        responses = {
            k: v for k, v in payload.items()
            if k not in score_keys and k != 'csrfmiddlewaretoken' and k != 'responses'
        }

    score_raw = next((payload[k] for k in score_keys if payload.get(k) not in (None, '')), None)

    sf, created = ServiteurFormation.objects.get_or_create(
        serviteur=request.user,
        formation=formation,
        defaults={'date_debut': timezone.now()}
    )
    if sf.date_debut is None:
        sf.date_debut = timezone.now()

    score = _record_html_result(sf, responses, score_raw)

    return JsonResponse({
        'ok': True,
        'score': score,
        'score_20': round(score * 0.2, 1),
        'statut': sf.statut,
        'statut_display': sf.get_statut_display(),
        'date_soumission': sf.date_soumission.isoformat(),
    })


@login_required(login_url='/')
def serviteur_questionnaire(request, pk):
    if request.user.role != 'serviteur':
        return redirect('/')
    formation = get_object_or_404(Formation.objects, pk=pk, is_active=True)
    sf, created = ServiteurFormation.objects.get_or_create(
        serviteur=request.user,
        formation=formation,
        defaults={'date_debut': timezone.now()}
    )

    # ✅ Si l'objet existait déjà mais sans date_debut, on démarre quand même le délai au clic.
    if sf.date_debut is None:
        sf.date_debut = timezone.now()
        sf.save()

    # ✅ Mise à jour automatique: si la date limite est dépassée et aucune soumission
    if sf.statut == 2 and sf.date_soumission is None and sf.date_limite and sf.date_limite <= timezone.now():
        sf.statut = 3  # Non transmis (délai dépassé, questionnaire jamais soumis)
        sf.save(update_fields=["statut"])

    score_20 = round(sf.score * 0.2, 1) if sf.score else 0

    # === Questionnaire HTML importé (prend le pas sur le QCM JSON) ===
    if formation.questionnaire_html:
        is_completed = sf.date_soumission is not None
        score_20 = round(sf.score * 0.2, 1) if sf.score else 0
        if is_completed:
            return render(request, 'serviteur/questionnaire_html.html', {
                'formation': formation,
                'sf': sf,
                'is_completed': True,
                'score_20': score_20,
            })
        if request.method == 'POST':
            responses = {k: v for k, v in request.POST.items() if k != 'csrfmiddlewaretoken'}
            score_raw = request.POST.get('score') or request.POST.get('note')
            _record_html_result(sf, responses, score_raw)
            # On reste sur la page du questionnaire : elle affiche la note obtenue.
            return redirect('traning:serviteur_questionnaire', pk=pk)
        return render(request, 'serviteur/questionnaire_html.html', {
            'formation': formation,
            'sf': sf,
            'is_completed': False,
            'score_20': score_20,
        })

    # === Questionnaire JSON classique ===
    if sf.score > 0:
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
        responses = {}
        for i in range(total):
            q = questionnaire[i]
            q_type = q.get('type')
            user_answer_str = request.POST.get(f'question_{i}', '').strip().lower()

            # Mémorise la réponse pour que le référent puisse la consulter
            responses[f'question_{i}'] = user_answer_str

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
        if responses:
            sf.html_responses = responses
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
        vert.last_submitted_at is not None
    )

    # Récupérer toutes les soumissions de ce serviteur
    all_submissions = vert.submissions.all()

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
        'submitted_at': vert.last_submitted_at,
        'days_since_submit': (
            (timezone.now() - vert.last_submitted_at).days
            if is_submitted else 0
        ),
        'submissions_count': vert.submissions_count or 0,
        'all_submissions': all_submissions,
    }

    return render(
        request,
        'serviteur/vertumetre.html',
        context
    )



def logout_view(request):
    logout(request)
    return redirect('traning:login')


def legacy_referent_redirect(request, *args, **kwargs):
    """Redirige les anciennes adresses « /referent/… » vers « /referant/… ».

    Les adresses référent ont d'abord été publiées avec l'orthographe
    « referent » : les liens et onglets déjà ouverts dans le navigateur
    doivent continuer à fonctionner."""
    suffixe = request.path[len('/referent'):] or '/'
    requete = request.META.get('QUERY_STRING', '')
    url = '/referant' + suffixe + (('?' + requete) if requete else '')
    return HttpResponsePermanentRedirect(url)


@login_required(login_url='/')
def referant_dashboard(request):
    if not (request.user.role == 'referant'):
        return redirect('/')
    serviteurs = list(
        CustomUser.objects.filter(role='serviteur', referant=request.user)
        .order_by('first_name', 'last_name')
    )
    # Les formations inactives sont invisibles chez les serviteurs : on les
    # exclut aussi des statistiques du référent.
    formations_count = Formation.objects.filter(is_active=True).count()
    sf_queryset = ServiteurFormation.objects.filter(
        serviteur__in=serviteurs, formation__is_active=True
    )
    sf_stats = {
        # Formations assignées à mes serviteurs (cohérent avec validé + en cours + échoué)
        'total': sf_queryset.count(),
        'validated': sf_queryset.filter(statut=1).count(),
        'failed': sf_queryset.filter(statut=0).count(),
        'not_transmitted': sf_queryset.filter(statut=3).count(),
        'pending': sf_queryset.filter(statut=2).count(),
        # Formations effectivement soumises par mes serviteurs
        'submitted': sf_queryset.filter(date_soumission__isnull=False).count(),
    }

    # Statistiques détaillées par serviteur
    sf_rows = sf_queryset.values(
        'serviteur__id', 'serviteur__first_name', 'serviteur__last_name',
        'serviteur__username', 'statut', 'score', 'date_soumission')
    per_serviteur = {}
    for row in sf_rows:
        sid = row['serviteur__id']
        entry = per_serviteur.setdefault(sid, {
            'first_name': row['serviteur__first_name'],
            'last_name': row['serviteur__last_name'],
            'username': row['serviteur__username'],
            'total': 0, 'validated': 0, 'failed': 0, 'pending': 0, 'not_transmitted': 0,
            'score_sum': 0, 'score_count': 0,
        })
        entry['total'] += 1
        if row['statut'] == 1:
            entry['validated'] += 1
        elif row['statut'] == 0:
            entry['failed'] += 1
        elif row['statut'] == 3:
            entry['not_transmitted'] += 1
        else:
            entry['pending'] += 1
        # Seules les formations soumises ont un score exploitable
        if row['date_soumission'] is not None and row['score'] is not None:
            entry['score_sum'] += row['score']
            entry['score_count'] += 1

    # Vertumètres (soumis dans les 7 derniers jours)
    vertumetres_recent = {
        v.serviteur_id: v for v in ServiteurVertumetre.objects.filter(
            serviteur__in=serviteurs
        )
    }

    serviteur_rows = []
    for s in serviteurs:
        stats = per_serviteur.get(s.pk, {
            'first_name': s.first_name, 'last_name': s.last_name,
            'username': s.username,
            'total': 0, 'validated': 0, 'failed': 0, 'pending': 0, 'not_transmitted': 0,
            'score_sum': 0, 'score_count': 0,
        })
        stats['score_moyen'] = (
            round(stats['score_sum'] / stats['score_count'] * 0.2, 1)
            if stats['score_count'] else 0
        )
        stats['serviteur'] = s
        stats['vertumetre'] = vertumetres_recent.get(s.pk)
        serviteur_rows.append(stats)

    return render(request, 'referant/dashboard.html', {
        'serviteurs': serviteurs,
        'formations_count': formations_count,
        'sf_stats': sf_stats,
        'serviteur_rows': serviteur_rows,
    })

@login_required(login_url='/')
def referant_serviteurs(request):
    if request.user.role != 'referant':
        return redirect('/')
    assigned = CustomUser.objects.filter(role='serviteur', referant=request.user).order_by('-date_joined')
    # Serviteurs déjà attribués — ne pas afficher dans la liste ni dans le dropdown
    already_assigned = set(s['pk'] for s in assigned.values('pk')) if assigned else set()
    # Tous les serviteurs non encore attribués — pour le dropdown de « Ajouter »
    unassigned = CustomUser.objects.filter(
        role='serviteur', referant__isnull=True
    ).exclude(pk__in=already_assigned).order_by('date_joined')
    serviteur_form = ServiteurForm(require_password=True)
    success_message = None
    error_message = None
    if request.method == 'POST':
        if 'assign_action' in request.POST:
            selected_pk = request.POST.get('assign_serviteur_pk', '').strip()
            if selected_pk:
                try:
                    serviteur = CustomUser.objects.get(pk=selected_pk, role='serviteur')
                    if serviteur.referant_id is None:
                        serviteur.referant = request.user
                        serviteur.save()
                        success_message = f"Serviteur '{serviteur.username}' attribué."
                    else:
                        error_message = "Ce serviteur est déjà attribué à un référent."
                except CustomUser.DoesNotExist:
                    error_message = "Le serviteur sélectionné n'existe pas."
            else:
                error_message = "Veuillez sélectionner un serviteur dans la liste."
        else:
            serviteur_form = ServiteurForm(request.POST, request.FILES, require_password=True)
            if serviteur_form.is_valid():
                serviteur = serviteur_form.save()
                serviteur.role = 'serviteur'
                serviteur.referant = request.user
                serviteur.save()
                success_message = f"Serviteur '{serviteur.username}' créé et attribué."
                serviteur_form = ServiteurForm(require_password=True)
    return render(request, 'referant/serviteurs.html', {
        'serviteurs': assigned,
        'unassigned': unassigned,
        'serviteur_form': serviteur_form,
        'success_message': success_message,
        'error_message': error_message,
    })

@login_required(login_url='/')
def referant_vertumetres(request):
    if request.user.role != 'referant':
        return redirect('/')
    serviteurs = list(
        CustomUser.objects.filter(role='serviteur', referant=request.user)
        .order_by('first_name', 'last_name')
    )
    vert_map = {
        v.serviteur_id: v
        for v in ServiteurVertumetre.objects.filter(serviteur__in=serviteurs)
    }
    for s in serviteurs:
        s.vert = vert_map.get(s.pk)
    return render(request, 'referant/vertumetres.html', {'serviteurs': serviteurs})


def _format_duration(seconds):
    """Formate une durée en secondes : '2 j 4 h', '4 h 12 min', '12 min', '45 s'."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} j {hours} h" if hours else f"{days} j"
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def _load_assigned_serviteur(request, pk):
    """Charge le serviteur assigné au référent courant; redirect si non autorisé ou introuvable."""
    if request.user.role != 'referant':
        return None, redirect('/')
    try:
        serviteur = CustomUser.objects.get(pk=pk, role='serviteur', referant=request.user)
    except CustomUser.DoesNotExist:
        return None, redirect('/')
    return serviteur, None


@login_required(login_url='/')
def referant_serviteur_detail(request, pk):
    """Détail d'un serviteur assigné : informations + liens vers ses formations / vertumètre."""
    serviteur, err = _load_assigned_serviteur(request, pk)
    if err:
        return err
    formations = Formation.objects.all().order_by('name')
    sf_list = ServiteurFormation.objects.filter(serviteur=serviteur).select_related('formation').order_by('-date_debut')
    for sf in sf_list:
        sf.score_20 = round(sf.score * 0.2, 1)
    stats = {
        'total': sf_list.count(),
        'in_progress': sum(1 for s in sf_list if s.display_status == 'progress'),
        'valid': sum(1 for s in sf_list if s.display_status == 'valid'),
        'failed': sum(1 for s in sf_list if s.display_status == 'failed'),
        'not_transmitted': sum(1 for s in sf_list if s.display_status == 'not_transmitted'),
    }

    # Formations en cours : temps restant avant l'échéance du questionnaire
    now = timezone.now()
    in_progress_list = []
    for sf in sf_list:
        if sf.display_status != 'progress':
            continue
        sf.remaining_seconds = None
        sf.remaining_label = ''
        sf.progress_percent = 0
        sf.deadline_passed = False
        sf.urgency = 'normal'
        if sf.date_limite:
            delta = sf.date_limite - now
            total_seconds = int(delta.total_seconds())
            sf.remaining_seconds = total_seconds
            sf.deadline_passed = total_seconds <= 0
            sf.remaining_label = _format_duration(abs(total_seconds))
            if total_seconds <= 0:
                sf.urgency = 'expired'
            elif total_seconds < 24 * 3600:
                sf.urgency = 'critical'
            elif total_seconds < 48 * 3600:
                sf.urgency = 'warning'
        if sf.date_debut and sf.date_limite and sf.date_limite > sf.date_debut:
            span = (sf.date_limite - sf.date_debut).total_seconds()
            elapsed = (now - sf.date_debut).total_seconds()
            sf.progress_percent = max(0, min(100, int(elapsed / span * 100)))
        in_progress_list.append(sf)

    # Formations commencées mais jamais transmises (délai dépassé)
    not_transmitted_list = [s for s in sf_list if s.display_status == 'not_transmitted']
    for sf in not_transmitted_list:
        if sf.date_limite:
            overdue = (now - sf.date_limite).total_seconds()
            sf.overdue_label = _format_duration(int(overdue))
            sf.overdue_seconds = int(overdue)
        else:
            sf.overdue_label = ''
            sf.overdue_seconds = 0
    stats['not_transmitted'] = len(not_transmitted_list)

    # Détail des réponses par formation soumise
    for sf in sf_list:
        summary = serviteur_answers_summary(sf.formation, sf.html_responses)
        sf.answers_total = summary['total']
        sf.answers_correct = summary['correct']
        sf.answers_incorrect = summary['incorrect']
        sf.answers_detail = summary['detail']
        sf.has_detail = summary['total'] > 0

    # Score moyen sur les formations soumises
    submitted = [s for s in sf_list if s.date_soumission is not None]
    stats['score_moyen'] = (
        round(sum(s.score_20 for s in submitted) / len(submitted), 1) if submitted else 0
    )

    # Vertumètre du serviteur
    vert = ServiteurVertumetre.objects.filter(serviteur=serviteur).first()

    return render(request, 'referant/serviteur_detail.html', {
        'serviteur': serviteur,
        'formations': formations,
        'sf_list': sf_list,
        'in_progress_list': in_progress_list,
        'submitted_list': submitted,
        'not_transmitted_list': not_transmitted_list,
        'stats': stats,
        'vert': vert,
    })


@login_required(login_url='/')
def referant_serviteur_questionnaire(request, pk, sf_pk):
    """Consultation détaillée des réponses d'un questionnaire soumis par un serviteur."""
    serviteur, err = _load_assigned_serviteur(request, pk)
    if err:
        return err

    sf = get_object_or_404(
        ServiteurFormation.objects.select_related('formation'),
        pk=sf_pk, serviteur=serviteur,
    )

    summary = serviteur_answers_summary(sf.formation, sf.html_responses)
    sf.score_20 = round(sf.score * 0.2, 1)

    # Informations complémentaires issues du formulaire de saisie du quiz HTML
    identity = {}
    for key in ('nom', 'prenom', 'famille', 'tribu', 'departement'):
        value = (sf.html_responses or {}).get(key)
        if value:
            identity[key] = value
    sf.identity = identity

    return render(request, 'referant/serviteur_questionnaire.html', {
        'serviteur': serviteur,
        'sf': sf,
        'answers_total': summary['total'],
        'answers_correct': summary['correct'],
        'answers_incorrect': summary['incorrect'],
        'answers_detail': summary['detail'],
        'has_detail': summary['total'] > 0,
    })


@login_required(login_url='/')
def referant_serviteur_formations(request, pk):
    """Liste des formations du serviteur (mis à disposition du référent)."""
    serviteur, err = _load_assigned_serviteur(request, pk)
    if err:
        return err
    serviteur_sf = ServiteurFormation.objects.filter(serviteur=serviteur).select_related('formation')
    servitations_map = {sf.formation_id: sf for sf in serviteur_sf}
    # Seules les formations actives sont visibles chez les référents,
    # comme chez les serviteurs (cf. serviteur_formations).
    formations = Formation.objects.filter(is_active=True).order_by('name')
    data = []
    status_map = {
        'valid': 'valid',
        'failed': 'failed',
        'not_transmitted': 'not_transmitted',
        'progress': 'in_progress',
    }
    for formation in formations:
        sf = servitations_map.get(formation.pk)
        if sf:
            status = status_map.get(sf.display_status, 'in_progress')
            score20 = round(sf.score * 0.2, 1) if sf.score else 0
        else:
            status = 'not_started'
            score20 = 0
        data.append({
            'formation': formation,
            'status': status,
            'score20': score20,
        })
    stats = {
        'total': len(data),
        'in_progress': sum(1 for d in data if d['status'] == 'in_progress'),
        'completed': sum(1 for d in data if d['status'] == 'completed'),
        'valid': sum(1 for d in data if d['status'] == 'valid'),
        'failed': sum(1 for d in data if d['status'] == 'failed'),
        'not_transmitted': sum(1 for d in data if d['status'] == 'not_transmitted'),
    }
    return render(request, 'referant/serviteur_formations.html', {
        'data': data,
        'stats': stats,
        'serviteur': serviteur,
    })


@login_required(login_url='/')
def referant_serviteur_vertumetre(request, pk):
    """Vue Vertumètre d'un serviteur spécifique (mis à disposition du référent)."""
    serviteur, err = _load_assigned_serviteur(request, pk)
    if err:
        return err
    vert, created = ServiteurVertumetre.objects.get_or_create(serviteur=serviteur)
    return render(request, 'referant/serviteur_vertumetre.html', {
        'serviteur': serviteur,
        'vert': vert,
    })


@login_required(login_url='/')
@never_cache
def referant_serviteur_message(request, pk):
    """Le référent envoie un message à l'un de ses serviteurs."""
    serviteur, err = _load_assigned_serviteur(request, pk)
    if err:
        return err

    success_message = None
    error_message = None
    if request.method == 'POST':
        subject = (request.POST.get('subject') or '').strip()
        body = (request.POST.get('body') or '').strip()
        if not subject:
            error_message = "Veuillez saisir un objet."
        elif not body:
            error_message = "Veuillez saisir un message."
        elif len(body) > 5000:
            error_message = "Le message ne doit pas dépasser 5000 caractères."
        else:
            ReferentMessage.objects.create(
                sender=request.user,
                recipient=serviteur,
                subject=subject[:200],
                body=body,
            )
            success_message = (
                f"Message envoyé à {serviteur.first_name} {serviteur.last_name} "
                f"({serviteur.username}) : il apparaît uniquement dans la "
                f"messagerie de ce serviteur."
            )

    messages_envoyes = ReferentMessage.objects.filter(
        sender=request.user, recipient=serviteur
    ).select_related('recipient')

    # Réponses envoyées par le serviteur à ce référent
    reponses_recues = ReferentMessage.objects.filter(
        recipient=request.user, sender=serviteur
    ).select_related('sender', 'reply_to')

    # Les réponses sont marquées comme lues à leur consultation
    unread_replies = reponses_recues.filter(read_at__isnull=True)
    if unread_replies.exists():
        unread_replies.update(read_at=timezone.now())

    return render(request, 'referant/serviteur_message.html', {
        'serviteur': serviteur,
        'messages_envoyes': messages_envoyes,
        'reponses_recues': reponses_recues,
        'success_message': success_message,
        'error_message': error_message,
    })


@login_required(login_url='/')
@never_cache
def referant_messages(request):
    """Boîte d'envoi du référent : tous les messages envoyés à ses serviteurs."""
    if request.user.role != 'referant':
        return redirect('/')
    messages_envoyes = ReferentMessage.objects.filter(
        sender=request.user
    ).select_related('recipient')

    # Réponses reçues des serviteurs (marquées comme lues à la consultation)
    reponses_recues = ReferentMessage.objects.filter(
        recipient=request.user
    ).select_related('sender')
    unread = reponses_recues.filter(read_at__isnull=True)
    if unread.exists():
        unread.update(read_at=timezone.now())

    return render(request, 'referant/messages.html', {
        'messages_envoyes': messages_envoyes,
        'reponses_recues': reponses_recues,
    })


@login_required(login_url='/')
@never_cache
def serviteur_messages(request):
    """Boîte de réception du serviteur : messages reçus de son référent + réponses envoyées."""
    if request.user.role != 'serviteur':
        return redirect('/')

    # Un message lu à sa première consultation
    unread = ReferentMessage.objects.filter(
        recipient=request.user, read_at__isnull=True
    )
    if unread.exists():
        unread.update(read_at=timezone.now())

    messages_recus = ReferentMessage.objects.filter(
        recipient=request.user
    ).select_related('sender', 'reply_to')

    # Réponses déjà envoyées par le serviteur (affichées sous le message d'origine)
    messages_envoyes = ReferentMessage.objects.filter(
        sender=request.user
    ).select_related('recipient', 'reply_to')

    return render(request, 'serviteur/messages.html', {
        'messages_recus': messages_recus,
        'messages_envoyes': messages_envoyes,
        'referent': request.user.referant,
    })


@login_required(login_url='/')
@never_cache
def serviteur_message_reply(request, pk):
    """Le serviteur répond à un message reçu de son référent."""
    if request.user.role != 'serviteur':
        return redirect('/')

    message = get_object_or_404(
        ReferentMessage.objects.select_related('sender'),
        pk=pk, recipient=request.user,
    )

    if request.method != 'POST':
        return redirect('traning:serviteur_messages')

    body = (request.POST.get('body') or '').strip()
    if not body:
        return redirect('traning:serviteur_messages')
    if len(body) > 5000:
        body = body[:5000]

    ReferentMessage.objects.create(
        sender=request.user,
        recipient=message.sender,
        subject=message.subject[:200],
        body=body,
        reply_to=message,
    )
    return redirect('traning:serviteur_messages')


def login_view(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''

        # Sécurise les POST incomplets (évite des exceptions/500)
        if not username or not password:
            return render(request, 'login.html', {'login_fields_missing': True})

        try:
            user = authenticate(request, username=username, password=password)
        except OperationalError:
            # Base momentanément inaccessible (verrou SQLite) : on ne dit pas
            # à l'utilisateur que son mot de passe est faux, on l'invite à réessayer.
            logger.exception("Connexion impossible : base de données occupée")
            return render(request, 'login.html', {'login_busy': True})
        except Exception:
            # Ne pas révéler l'erreur interne au client
            logger.exception("Erreur inattendue lors de l'authentification")
            return render(request, 'login.html', {'login_error': True})

        if user is not None:
            # La session précédente est mémorisée : Django la détruit quand on
            # se connecte avec un autre compte, ce qui déconnecte les autres
            # onglets du même navigateur (« la session expire »).
            previous_key = request.session.session_key
            previous_data = None
            if previous_key and _get_user_session_key(request) != str(user.pk):
                previous_data = dict(request.session.items())

            try:
                login(request, user)
                # Sauvegarde immédiate : si l'écriture échoue, on le sait ici
                # au lieu de laisser le navigateur avec un cookie invalide.
                request.session.save()
            except OperationalError:
                logger.exception("Connexion impossible : base de données occupée")
                _restore_session(previous_key, previous_data)
                return render(request, 'login.html', {'login_busy': True})
            except Exception:
                logger.exception("Erreur inattendue lors de l'ouverture de la session")
                _restore_session(previous_key, previous_data)
                return render(request, 'login.html', {'login_error': True})

            if previous_data:
                # On restaure l'ancienne session : les autres onglets restent
                # connectés avec le compte précédent.
                _restore_session(previous_key, previous_data)

            # ✅ ADMIN
            if user.is_superuser or getattr(user, 'role', None) == 'admin':
                return redirect('traning:admin_dashboard')

            # ✅ ÉTUDIANT (SERVITEUR)
            if getattr(user, 'role', None) == 'serviteur':
                return redirect('traning:serviteur_dashboard')

            if getattr(user, 'role', None) == 'referant':
                # Le nom d'URL déclaré dans traning/urls.py est
                # « referant_dashboard » (sans « e » après le r) : utiliser
                # « referent_dashboard » provoquait un NoReverseMatch (500)
                # à la connexion d'un référent.
                return redirect('traning:referant_dashboard')

            return render(request, 'login.html', {'login_error': True})

        return render(request, 'login.html', {'login_error': True})

    return render(request, 'login.html')


def _restore_session(session_key, session_data):
    """Recrée une ligne de session (utilisé pour ne pas perdre les onglets
    déjà connectés et pour éviter un cookie pointant vers une session
    supprimée)."""
    if not session_key or not session_data:
        return
    try:
        store = SessionStore(session_key=session_key)
        # Écriture directe du cache : update() rechargerait la session et
        # invaliderait la clé si la ligne n'existe plus (même approach que
        # django.contrib.sessions.backends.base.SessionBase.cycle_key).
        store._session_cache = dict(session_data)
        store.modified = True
        try:
            # La ligne a été supprimée par Django : il faut la recréer.
            store.save(must_create=True)
        except CreateError:
            # La session existe encore : on la met simplement à jour.
            store.save()
    except Exception:
        logger.exception("Impossible de restaurer la session %s", session_key)

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import IntegrityError

@login_required(login_url='/')
def admin_referants(request):
    """Gestion des référents : création et attribution des serviteurs."""

    # Vérification des droits d'accès
    if not (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('/')

    # Traitement des formulaires
    if request.method == 'POST':

        # ==========================================
        # CRÉATION D'UN RÉFÉRENT
        # ==========================================
        if 'create_referant' in request.POST:
            form = AdminReferantForm(request.POST)

            if form.is_valid():
                referent = form.save(commit=False)

                # S'assurer que le rôle correspond au filtre ci-dessous
                referent.role = 'referant'
                referent.save()

                messages.success(
                    request,
                    f"Le référent « {referent.first_name} "
                    f"{referent.last_name} » a été créé avec succès."
                )

                return redirect('traning:admin_referants')

            else:
                messages.error(
                    request,
                    "Le formulaire contient des erreurs. "
                    "Veuillez vérifier les champs."
                )

        # ==========================================
        # CRÉATION ET ATTRIBUTION D'UN SERVITEUR
        # ==========================================
        elif 'assign' in request.POST:
            pk = request.POST.get('assign_referant')
            serviteur_pk = request.POST.get('assign_serviteur_pk', '').strip()
            username = request.POST.get('assign_username', '').strip()
            first_name = request.POST.get('assign_first_name', '').strip()
            last_name = request.POST.get('assign_last_name', '').strip()
            email = request.POST.get('assign_email', '').strip()

            form = AdminReferantForm()

            if not pk:
                messages.error(request, "Veuillez sélectionner un référent.")

            elif serviteur_pk:
                try:
                    referent = CustomUser.objects.get(
                        pk=pk,
                        role='referant'
                    )
                    existing = CustomUser.objects.get(
                        pk=serviteur_pk, role='serviteur'
                    )
                except CustomUser.DoesNotExist:
                    messages.error(request, "Le serviteur sélectionné n'existe pas.")
                    form = AdminReferantForm()

                else:
                    existing.referant = referent
                    existing.save()
                    messages.success(
                        request,
                        f"Le serviteur « {existing.username} » "
                        f"(#{serviteur_pk}) attribué au référent."
                    )
                    return redirect('traning:admin_referants')

            elif not username or not first_name or not last_name:
                messages.error(
                    request,
                    "Veuillez soit sélectionner un serviteur existant, "
                    "soit renseigner le nom d'utilisateur, "
                    "le prénom et le nom du serviteur."
                )

            else:
                try:
                    referent = CustomUser.objects.get(
                        pk=pk,
                        role='referant'
                    )

                    serviteur = CustomUser.objects.create_user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        role='serviteur'
                    )

                    serviteur.referant = referent
                    serviteur.save()

                    messages.success(
                        request,
                        f"Le serviteur « {serviteur.username} » "
                        f"attribué au référent."
                    )

                    return redirect('traning:admin_referants')

                except CustomUser.DoesNotExist:
                    messages.error(request, "Le référent sélectionné est introuvable.")

                except IntegrityError:
                    messages.error(
                        request,
                        "Ce nom d'utilisateur est déjà utilisé."
                    )

                except Exception as e:
                    messages.error(
                        request,
                        f"Une erreur est survenue : {str(e)}"
                    )

        # ==========================================
        # RÉINITIALISATION DU MOT DE PASSE
        # ==========================================
        elif 'reset_password' in request.POST:
            ref_pk = request.POST.get('reset_referant')
            new_password = request.POST.get('reset_password', '').strip()
            confirm = request.POST.get('reset_password_confirm', '').strip()

            form = AdminReferantForm()

            if not ref_pk:
                messages.error(request, "Veuillez sélectionner un référent.")

            elif len(new_password) < 8:
                messages.error(
                    request,
                    "Le mot de passe doit contenir au moins 8 caractères."
                )

            elif new_password != confirm:
                messages.error(
                    request,
                    "Les deux mots de passe ne correspondent pas."
                )

            else:
                try:
                    referent = CustomUser.objects.get(pk=ref_pk, role='referant')
                except CustomUser.DoesNotExist:
                    messages.error(request, "Le référent sélectionné est introuvable.")
                else:
                    referent.set_password(new_password)
                    referent.save()
                    messages.success(
                        request,
                        f"Nouveau mot de passe défini pour « {referent.username} »."
                    )
                    return redirect('traning:admin_referants')

        else:
            form = AdminReferantForm()

    else:
        form = AdminReferantForm()

    # ==========================================
    # RÉCUPÉRATION DES DONNÉES À AFFICHER
    # ==========================================
    referents = CustomUser.objects.filter(
        role='referant'
    ).order_by('-date_joined')

    # Serviteurs non encore attribués — disponibles pour affectation
    serviteurs = CustomUser.objects.filter(
        role='serviteur',
        referant__isnull=True,
    ).order_by('-date_joined')

    # Tous les serviteurs (y compris déjà attribués) — pour les listes de référence
    all_serviteurs = CustomUser.objects.filter(
        role='serviteur'
    ).order_by('-date_joined')

    departements = Departement.objects.all().order_by('name')

    # ==========================================
    # INFORMATIONS DÉTAILLÉES (référents + serviteurs)
    # ==========================================

    # Progression de chaque serviteur
    serviteur_stats = {}
    for sf in ServiteurFormation.objects.filter(
        serviteur__role='serviteur'
    ).select_related('formation'):
        entry = serviteur_stats.setdefault(sf.serviteur_id, {
            'total': 0, 'valid': 0, 'failed': 0,
            'progress': 0, 'not_transmitted': 0,
            'score_sum': 0, 'score_count': 0,
        })
        entry['total'] += 1
        status = sf.display_status
        if status == 'valid':
            entry['valid'] += 1
        elif status == 'failed':
            entry['failed'] += 1
        elif status == 'not_transmitted':
            entry['not_transmitted'] += 1
        else:
            entry['progress'] += 1
        if sf.date_soumission is not None:
            entry['score_sum'] += sf.score
            entry['score_count'] += 1

    # Vertumètres des serviteurs
    vertumetres = {
        v.serviteur_id: v
        for v in ServiteurVertumetre.objects.filter(serviteur__role='serviteur')
    }

    empty_stats = {
        'total': 0, 'valid': 0, 'failed': 0,
        'progress': 0, 'not_transmitted': 0,
        'score_sum': 0, 'score_count': 0,
    }

    for ref in referents:
        ref.serviteurs_list = list(ref.serviteurs_assignes.all())

        ref_total = ref_valid = ref_failed = 0
        ref_progress = ref_not_transmitted = 0
        ref_score_sum = ref_score_count = 0

        for s in ref.serviteurs_list:
            st = serviteur_stats.get(s.pk, empty_stats)
            s.sf_total = st['total']
            s.sf_valid = st['valid']
            s.sf_failed = st['failed']
            s.sf_progress = st['progress']
            s.sf_not_transmitted = st['not_transmitted']
            s.sf_score_moyen = (
                round(st['score_sum'] / st['score_count'] * 0.2, 1)
                if st['score_count'] else 0
            )
            s.vertumetre = vertumetres.get(s.pk)

            ref_total += st['total']
            ref_valid += st['valid']
            ref_failed += st['failed']
            ref_progress += st['progress']
            ref_not_transmitted += st['not_transmitted']
            ref_score_sum += st['score_sum']
            ref_score_count += st['score_count']

        ref.sf_total = ref_total
        ref.sf_valid = ref_valid
        ref.sf_failed = ref_failed
        ref.sf_progress = ref_progress
        ref.sf_not_transmitted = ref_not_transmitted
        ref.sf_score_moyen = (
            round(ref_score_sum / ref_score_count * 0.2, 1)
            if ref_score_count else 0
        )

    return render(request, 'admin/referants.html', {
        'referents': referents,
        'serviteurs': serviteurs,
        'all_serviteurs': all_serviteurs,
        'departements': departements,
        'form': form,
    })

