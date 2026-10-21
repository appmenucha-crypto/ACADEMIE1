import json
import pathlib
import re
from datetime import timedelta
from unittest.mock import patch
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CustomUser, Formation, ServiteurFormation, ReferentMessage
from .models_vertumetre import ServiteurVertumetre, VertumetreSubmission
from .quiz import parse_html_questions, build_answer_detail


def _stat_card_value(html, label):
    """Extrait la valeur d'une carte de statistique à partir de son libellé."""
    match = re.search(
        r'font-medium">' + re.escape(label) + r'</p>\s*<p class="text-3xl font-bold">([^<]*)</p>',
        html)
    return match.group(1).strip() if match else None


HTML_QUIZ = """
<form method="post" id="quiz">
    <p>Question 1</p>
    <input type="radio" name="q1" value="a">
    <button type="button" id="finish">Terminer</button>
</form>
<div id="result" style="display:none">
    <span id="score-display">Bravo ! Votre score : 8/20</span>
</div>
<script>
document.getElementById('finish').addEventListener('click', function () {
    document.getElementById('result').style.display = 'block';
});
</script>
"""


class HtmlQuestionnaireResultTests(TestCase):
    def setUp(self):
        self.serviteur = CustomUser.objects.create_user(
            username='sacha', password='pwd', role='serviteur'
        )
        self.formation = Formation.objects.create(
            name='Formation HTML',
            questionnaire_json=[{'question': 'Q', 'options': ['a'], 'correct': 0}],
            questionnaire_html=HTML_QUIZ,
        )
        self.save_url = reverse(
            'traning:serviteur_questionnaire_html_result',
            args=[self.formation.pk],
        )

    def test_note_html_est_enregistree_et_cloture_le_cours(self):
        self.client.force_login(self.serviteur)

        response = self.client.post(
            self.save_url,
            data=json.dumps({'score': 40, 'responses': {'q1': 'b'}}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['score'], 40)
        self.assertEqual(response.json()['score_20'], 8.0)

        sf = ServiteurFormation.objects.get(serviteur=self.serviteur, formation=self.formation)
        self.assertEqual(sf.score, 40)
        self.assertIsNotNone(sf.date_soumission)
        self.assertEqual(sf.statut, 0)  #échoué (< 50)
        self.assertEqual(sf.html_responses, {'q1': 'b'})

    def test_note_sans_reponses_explicite_est_acceptee(self):
        self.client.force_login(self.serviteur)

        response = self.client.post(self.save_url, {'score': '75'})

        self.assertEqual(response.status_code, 200)
        sf = ServiteurFormation.objects.get(serviteur=self.serviteur, formation=self.formation)
        self.assertEqual(sf.score, 75)
        self.assertEqual(sf.statut, 1)  # validé

    def test_soumission_sans_note_vaut_100(self):
        self.client.force_login(self.serviteur)

        self.client.post(self.save_url, {'q1': 'a'})

        sf = ServiteurFormation.objects.get(serviteur=self.serviteur, formation=self.formation)
        self.assertEqual(sf.score, 100)
        self.assertEqual(sf.statut, 1)

    def test_note_deja_enregistree_non_ecrasee_par_une_soumission_tardive(self):
        self.client.force_login(self.serviteur)
        self.client.post(
            self.save_url,
            data=json.dumps({'score': 30, 'responses': {'q1': 'b'}}),
            content_type='application/json',
        )

        self.client.post(self.save_url, {'q1': 'a'})

        sf = ServiteurFormation.objects.get(serviteur=self.serviteur, formation=self.formation)
        self.assertEqual(sf.score, 30)

    def test_acces_refuse_aux_non_serviteurs(self):
        admin = CustomUser.objects.create_superuser(
            username='root', password='pwd', email='a@b.c'
        )
        admin.role = 'admin'
        admin.save()
        self.client.force_login(admin)

        response = self.client.post(self.save_url, {'score': 100})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiteurFormation.objects.exists())

    def test_note_visible_partout_apres_soumission(self):
        self.client.force_login(self.serviteur)
        self.client.post(
            self.save_url,
            data=json.dumps({'score': 80, 'responses': {'q1': 'a'}}),
            content_type='application/json',
        )

        dashboard = self.client.get(reverse('traning:serviteur_dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        sf = dashboard.context['formations'][0]
        self.assertEqual(sf.score_20, 16.0)
        self.assertEqual(sf.display_status, 'valid')
        self.assertContains(dashboard, '16.0/20')

        formations = self.client.get(reverse('traning:serviteur_formations'))
        item = formations.context['formations_data'][0]
        self.assertEqual(item['status'], 'completed')
        self.assertEqual(item['score20'], 16.0)

        detail = self.client.get(
            reverse('traning:serviteur_formation_detail', args=[self.formation.pk])
        )
        self.assertTrue(detail.context['has_result'])
        self.assertContains(detail, '16.0/20')

    def test_note_html_affichee_apres_soumission(self):
        self.client.force_login(self.serviteur)
        self.client.post(self.save_url, {'score': '65'})

        page = self.client.get(
            reverse('traning:serviteur_questionnaire', args=[self.formation.pk])
        )

        self.assertTrue(page.context['is_completed'])
        self.assertContains(page, '13.0/20')

    def test_note_zero_afficlee_et_cours_termine(self):
        self.client.force_login(self.serviteur)
        self.client.post(
            self.save_url,
            data=json.dumps({'score': 0, 'responses': {'q1': 'c'}}),
            content_type='application/json',
        )

        dashboard = self.client.get(reverse('traning:serviteur_dashboard'))
        sf = dashboard.context['formations'][0]
        self.assertEqual(sf.display_status, 'failed')
        self.assertContains(dashboard, 'Terminé · 0.0/20')

        formations = self.client.get(reverse('traning:serviteur_formations'))
        item = formations.context['formations_data'][0]
        self.assertEqual(item['status'], 'completed')

        detail = self.client.get(
            reverse('traning:serviteur_formation_detail', args=[self.formation.pk])
        )
        self.assertTrue(detail.context['has_result'])
        self.assertEqual(detail.context['score_20'], 0)

    def test_vertumetre_soumissions_multiples_par_serviteur(self):
        """Un serviteur peut avoir plusieurs soumissions Vertumetre dans le temps."""
        self.client.force_login(self.serviteur)
        
        # Première soumission
        data1 = {f'q{i}': '1' for i in range(1, 13)}
        data1['q7'] = ['fruit', 'caractere']  # MultipleChoiceField
        self.client.post(
            reverse('traning:serviteur_vertumetre'),
            data1,
        )
        
        vert = ServiteurVertumetre.objects.get(serviteur=self.serviteur)
        self.assertEqual(vert.submissions_count, 1)
        self.assertEqual(VertumetreSubmission.objects.filter(vertumetre=vert).count(), 1)
        
        # Simuler le passage du temps pour permettre une nouvelle soumission
        from django.utils import timezone
        from datetime import timedelta
        vert.last_submitted_at = timezone.now() - timedelta(days=8)
        vert.save()
        
        # Deuxième soumission
        data2 = {f'q{i}': '2' for i in range(1, 13)}
        data2['q7'] = ['sante', 'ministere']
        self.client.post(
            reverse('traning:serviteur_vertumetre'),
            data2,
        )
        
        vert.refresh_from_db()
        self.assertEqual(vert.submissions_count, 2)
        self.assertEqual(VertumetreSubmission.objects.filter(vertumetre=vert).count(), 2)
        
        # Vérifier que les deux soumissions sont distinctes
        subs = list(VertumetreSubmission.objects.filter(vertumetre=vert).order_by('submitted_at'))
        self.assertEqual(subs[0].answers['q1'], '1')
        self.assertEqual(subs[1].answers['q1'], '2')

    def test_serviteur_voit_les_questions_avec_ses_reponses(self):
        """Après soumission, le serviteur relit ses réponses avec l'intitulé
        de chaque question."""
        self.client.force_login(self.serviteur)

        data = {f'q{i}': '1' for i in range(1, 13)}
        data['q7'] = ['fruit']
        self.client.post(reverse('traning:serviteur_vertumetre'), data)

        resp = self.client.get(reverse('traning:serviteur_vertumetre'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')

        # La question est affichée…
        self.assertIn('Combien de fois vous priez chaque jour?', body)
        self.assertIn('Volume de lecture de la Bible', body)
        # …ainsi que la réponse choisie.
        self.assertIn('1 fois', body)

    def test_admin_vertumetres_groupe_par_serviteur(self):
        """La vue admin liste un serviteur par ligne avec toutes ses soumissions."""
        # Créer un serviteur avec des soumissions
        s1 = CustomUser.objects.create_user(username='serv1', password='pwd', role='serviteur')
        s2 = CustomUser.objects.create_user(username='serv2', password='pwd', role='serviteur')
        
        v1 = ServiteurVertumetre.objects.create(serviteur=s1)
        v2 = ServiteurVertumetre.objects.create(serviteur=s2)
        
        VertumetreSubmission.objects.create(vertumetre=v1, answers={'q1': '1', 'q7': ['fruit']}, submitted_at=timezone.now())
        VertumetreSubmission.objects.create(vertumetre=v1, answers={'q1': '2', 'q7': ['caractere']}, submitted_at=timezone.now() - timedelta(days=7))
        VertumetreSubmission.objects.create(vertumetre=v2, answers={'q1': '3', 'q7': ['sante']}, submitted_at=timezone.now() - timedelta(days=1))
        
        admin = CustomUser.objects.create_superuser(username='root', password='pwd', email='a@b.c')
        admin.role = 'admin'
        admin.save()
        self.client.force_login(admin)
        
        # Liste admin : une ligne par serviteur
        resp = self.client.get(reverse('traning:admin_vertumetres'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['vertumetres']), 2)
        
        # Détail serviteur 1 : voir ses 2 soumissions
        resp = self.client.get(reverse('traning:admin_vertumetre_detail', args=[v1.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['submissions']), 2)

    def test_admin_vertumetre_detail_affiche_les_questions(self):
        """Le détail d'un vertumètre affiche l'intitulé des questions en plus
        des réponses."""
        serviteur = CustomUser.objects.create_user(
            username='serv_quest', password='pwd', role='serviteur')
        vert = ServiteurVertumetre.objects.create(serviteur=serviteur)
        VertumetreSubmission.objects.create(
            vertumetre=vert,
            answers={'q1': '1', 'q2': '3'},
            submitted_at=timezone.now(),
        )

        admin = CustomUser.objects.create_superuser(
            username='root_quest', password='pwd', email='r@b.c')
        admin.role = 'admin'
        admin.save()
        self.client.force_login(admin)

        resp = self.client.get(
            reverse('traning:admin_vertumetre_detail', args=[vert.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')

        # Les questions…
        self.assertIn('Combien de fois vous priez chaque jour?', body)
        self.assertIn('Combien de temps durent vos temps de prière', body)
        # …et les réponses correspondantes.
        self.assertIn('1 fois', body)
        self.assertIn('1h et plus', body)

    def test_soumission_html_reste_sur_la_page_du_questionnaire(self):
        self.client.force_login(self.serviteur)

        response = self.client.post(
            reverse('traning:serviteur_questionnaire', args=[self.formation.pk]),
            {'q1': 'a', 'score': '70'},
        )

        self.assertRedirects(
            response,
            reverse('traning:serviteur_questionnaire', args=[self.formation.pk]),
        )
        sf = ServiteurFormation.objects.get(serviteur=self.serviteur, formation=self.formation)
        self.assertEqual(sf.score, 70)

    def test_note_visibles_uniquement_avec_jeton_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.serviteur)

        # Sans jeton CSRF : refusé par Django.
        refused = strict.post(
            self.save_url,
            data=json.dumps({'score': 90}),
            content_type='application/json',
        )
        self.assertEqual(refused.status_code, 403)
        self.assertFalse(ServiteurFormation.objects.filter(formation=self.formation).exists())

        # Avec le jeton livré par la page (comme le fait le pont JS) : enregistré.
        page = strict.get(reverse('traning:serviteur_questionnaire', args=[self.formation.pk]))
        token = str(page.context['csrf_token'])

        accepted = strict.post(
            self.save_url,
            data=json.dumps({'score': 90}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()['score'], 90)

    def test_page_questionnaire_html_expose_la_synchronisation(self):
        self.client.force_login(self.serviteur)

        page = self.client.get(
            reverse('traning:serviteur_questionnaire', args=[self.formation.pk])
        )

        body = page.content.decode()
        self.assertIn(self.save_url, body)
        self.assertIn('csrfmiddlewaretoken', body)
        # Le pont JS est bien présent et valide
        self.assertIn('MutationObserver', body)
        self.assertIn('getCookie', body)
        # Aucun bouton de soumission supplémentaire : le HTML importé reste maître
        self.assertNotContains(page, 'Envoyer mes réponses')
        self.assertNotContains(page, 'html-submit-btn')


# ===== REFERANT ADMIN TESTS =====
class ReferantAdminTest(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser('admintest', 'admin@test.com', 'admin123')

    def test_admin_referants_page_renders(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Gestion des référents', body)
        self.assertIn('Aucun référent pour le moment', body)

    def test_create_referant_via_form(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'create_referant': '1',
            'username': 'testref',
            'first_name': 'Test',
            'last_name': 'Réf',
            'email': 'ref@test.com',
            'password': 'refpass123',
            'role': 'referant',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn("Référent", body)
        ref = CustomUser.objects.get(username='testref')
        self.assertEqual(ref.role, 'referant')

    def test_create_referant_with_phone_number(self):
        """Le numéro de téléphone est enregistré et affiché dans la liste."""
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'create_referant': '1',
            'username': 'refavecphone',
            'first_name': 'Avec',
            'last_name': 'Telephone',
            'email': 'avecphone@test.com',
            'phone_number': '22177000000',
            'password': 'refpass123',
            'role': 'referant',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)

        ref = CustomUser.objects.get(username='refavecphone')
        self.assertEqual(ref.phone_number, '22177000000')

        # Le numéro apparaît dans la liste des référents
        body = resp.content.decode('utf-8')
        self.assertIn('22177000000', body)

    def test_create_referant_without_phone_number(self):
        """Le numéro de téléphone reste facultatif à la création."""
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'create_referant': '1',
            'username': 'refsansphone',
            'first_name': 'Sans',
            'last_name': 'Telephone',
            'email': 'sansphone@test.com',
            'password': 'refpass123',
            'role': 'referant',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)

        ref = CustomUser.objects.get(username='refsansphone')
        self.assertIn(ref.phone_number, (None, ''))
        self.assertIn('Téléphone non renseigné', resp.content.decode('utf-8'))

    def test_assign_serviteur_to_referent(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        ref = CustomUser.objects.create_user('refuser', email='ref@test.com', password='refpass123', first_name='Ref1', last_name='Ref1', role='referant')
        sf = CustomUser.objects.create_user('std1', email='std@test.com', password='stdpass123', first_name='Std1', last_name='Std1', role='serviteur')
        sf.referant = ref
        sf.save()
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Gestion des référents', body)

    def test_details_renseigne_les_infos_du_referent_et_de_ses_serviteurs(self):
        """Le panneau « Détails » montre les infos du référent et celles de ses serviteurs."""
        ref = CustomUser.objects.create_user('refinfos', email='refinfos@test.com', password='refpass123',
                                             first_name='Réf', last_name='Infos', role='referant',
                                             phone_number='+225 07 00 00 00 00')
        serviteur = CustomUser.objects.create_user('servinfos', email='servinfos@test.com', password='servpass123',
                                                   first_name='Serv', last_name='Infos', role='serviteur',
                                                   phone_number='+225 05 11 22 33 44')
        serviteur.referant = ref
        serviteur.save()

        formation = Formation.objects.create(name='Formation referents test')
        ServiteurFormation.objects.create(
            serviteur=serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=5),
            date_limite=timezone.now() - timedelta(days=2),
            statut=3,
        )

        c = Client()
        c.login(username='admintest', password='admin123')
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')

        # Infos du référent
        self.assertIn('referent-info-card', body)
        self.assertIn('refinfos@test.com', body)
        self.assertIn('+225 07 00 00 00 00', body)
        self.assertIn('Dernière connexion', body)
        self.assertIn('Serviteurs attribués', body)
        self.assertIn('Score moyen', body)

        # Infos des serviteurs : toutes les colonnes attendues
        for column in ('Téléphone', 'Statut', 'Formations', 'Score moyen', 'Inscrit le', 'Vertumètre'):
            self.assertIn(column, body)
        self.assertIn('+225 05 11 22 33 44', body)
        self.assertIn('Non transmis', body)

        # L'e-mail des serviteurs n'est pas affiché dans la liste
        panel = body[body.index('referent-info-card'):]
        serviteur_table = panel[panel.index('servants-table'):]
        serviteur_table = serviteur_table[:serviteur_table.index('</table>')]
        self.assertNotIn('servinfos@test.com', serviteur_table)

    def test_assign_existing_serviteur(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        ref = CustomUser.objects.create_user('refuser2', email='ref2@test.com', password='refpass123', first_name='Réf', last_name='Test', role='referant')
        sf = CustomUser.objects.create_user('std2', email='std2@test.com', password='stdpass123', first_name='Std', last_name='User', role='serviteur')
        self.assertEqual(sf.referant, None)
        post = {
            'assign': '1',
            'assign_referant': ref.pk,
            'assign_serviteur_pk': sf.pk,
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)
        sf.refresh_from_db()
        self.assertEqual(sf.referant, ref)

    def test_assign_modal_shows_dropdown(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        # Create a referent so the assign modal renders
        CustomUser.objects.create_user('refmodtest', email='refm@test.com', password='refpass123', first_name='Réf', last_name='Test', role='referant')
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Ajouter un serviteur existant', body)
        self.assertIn('Sélectionner un serviteur non attribué', body)

    def test_assign_modal_is_outside_table(self):
        """La modale doit être hors du <table> pour être visible (sinon display:none)."""
        c = Client()
        c.login(username='admintest', password='admin123')
        ref = CustomUser.objects.create_user('refout', email='refo@t.com', password='refpass123', first_name='Réf', last_name='Out', role='referant')
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        table_end = body.rindex('</table>')
        modal_pos = body.index(f'id="assignModal-{ref.pk}"')
        # La modale doit être rendue APRÈS la fermeture du tableau
        self.assertGreater(modal_pos, table_end)

    def test_assign_dropdown_excludes_already_assigned(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        ref = CustomUser.objects.create_user('refexcl', email='refe@test.com', password='refpass123', first_name='Réf', last_name='Excl', role='referant')
        # One serviteur already assigned to another referant
        other_ref = CustomUser.objects.create_user('refother', email='refo@test.com', password='refpass123', first_name='Autre', last_name='Réf', role='referant')
        assigned_sf = CustomUser.objects.create_user('sfassigned', email='sfa@test.com', password='stdpass123', first_name='Déjà', last_name='Attribué', role='serviteur')
        assigned_sf.referant = other_ref
        assigned_sf.save()
        # One free serviteur
        free_sf = CustomUser.objects.create_user('sffree', email='sff@test.com', password='stdpass123', first_name='Libre', last_name='Serviteur', role='serviteur')
        self.assertEqual(free_sf.referant, None)

        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        # Isoler le contenu du <select> du dropdown
        start = body.index('name="assign_serviteur_pk"')
        end = body.index('</select>', start)
        dropdown = body[start:end]
        # Le serviteur libre doit être dans le dropdown
        self.assertIn('sffree', dropdown)
        # Le serviteur déjà attribué ne doit PAS être dans le dropdown
        self.assertNotIn('sfassigned', dropdown)


# ===== REFERANT USER WORKFLOW TESTS =====
class ReferantUserWorkflowTest(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser('admintest', 'admin@test.com', 'admin123')
        self.ref = CustomUser.objects.create_user('refuser', email='ref@test.com', password='refpass123', first_name='Réf', last_name='Test', role='referant')
        self.serviteur = CustomUser.objects.create_user('std1', email='std@test.com', password='stdpass123', first_name='Std', last_name='User', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()

    def test_referant_can_login(self):
        c = Client()
        resp = c.post('/', {'username': 'refuser', 'password': 'refpass123'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Espace Référent', body)

    def test_referant_dashboard_shows_assigned_serviteur(self):
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get('/referant/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Mes Serviteurs', body)
        self.assertIn('Std User', body)
        self.assertIn('Dashboard', body)

    def test_referant_serviteur_detail(self):
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Mes Serviteurs', body)

    def test_referant_voit_les_formations_en_cours_et_le_temps_restant(self):
        """La fiche du serviteur affiche les formations en cours et le temps restant."""
        formation = Formation.objects.create(name='Formation en cours test')
        debut = timezone.now() - timedelta(days=1)
        limite = timezone.now() + timedelta(days=2)
        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=debut, date_limite=limite, statut=2,
        )
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Formations en cours', body)
        self.assertIn('Formation en cours test', body)
        self.assertIn('Temps restant', body)
        self.assertIn('Échéance le', body)
        # Le compte à rebours est exposé pour un affichage dynamique
        self.assertIn('countdown-timer', body)
        self.assertIn('data-deadline="', body)
        # Le temps restant calculé est proche des 2 jours restants
        in_progress = resp.context['in_progress_list']
        self.assertEqual(len(in_progress), 1)
        self.assertAlmostEqual(in_progress[0].remaining_seconds, 2 * 86400, delta=60)
        self.assertEqual(in_progress[0].progress_percent, 33)

    def test_referant_voit_les_formations_expirees(self):
        """Les formations dont l'échéance est dépassée sans soumission sont signalées."""
        formation = Formation.objects.create(name='Formation expiree test')
        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=6),
            date_limite=timezone.now() - timedelta(days=3),
            statut=0,
        )
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Formations non transmises', body)
        self.assertIn('Formation expiree test', body)
        self.assertIn('dépassé de', body)
        # Le statut n'est pas « Échoué » mais « Non transmis »
        self.assertNotIn('Formations expirées', body)

    def test_formation_non_transmise_n_est_pas_comptee_comme_echouee(self):
        """Une formation commencée mais jamais transmise n'est pas un échec."""
        formation = Formation.objects.create(name='Formation non transmise test')
        sf = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=6),
            date_limite=timezone.now() - timedelta(days=3),
            statut=3,
        )
        self.assertEqual(sf.display_status, 'not_transmitted')
        self.assertEqual(sf.statut_label, 'Non transmis')

        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        stats = resp.context['stats']
        self.assertEqual(stats['failed'], 0)
        self.assertEqual(stats['not_transmitted'], 1)

    def test_echec_reel_conserve_le_statut_echouee(self):
        """Un questionnaire soumis mais non validé reste « Échoué »."""
        formation = Formation.objects.create(name='Formation echouee test')
        sf = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=2),
            date_soumission=timezone.now() - timedelta(days=1),
            score=30, statut=0,
        )
        self.assertEqual(sf.display_status, 'failed')
        self.assertEqual(sf.statut_label, 'Échoué')

        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        stats = resp.context['stats']
        self.assertEqual(stats['failed'], 1)
        self.assertEqual(stats['not_transmitted'], 0)

    def test_commande_bascule_les_formations_expirees_en_non_transmis(self):
        """La commande de gestion marque « Non transmis » les délais dépassés sans soumission."""
        from django.core.management import call_command

        formation = Formation.objects.create(name='Formation commande test')
        sf = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=5),
            date_limite=timezone.now() - timedelta(days=2),
            statut=2,
        )
        call_command('update_failed_serviteurformation')
        sf.refresh_from_db()
        self.assertEqual(sf.statut, 3)
        self.assertEqual(sf.display_status, 'not_transmitted')

    def test_referant_consulte_les_reponses_d_un_questionnaire_soumis(self):
        """Le référent peut consulter le détail vert/rouge d'un questionnaire soumis."""
        formation = Formation.objects.create(
            name='Formation submitted test',
            questionnaire_html=HTML_QUIZ_WITH_QUESTIONS,
        )
        sf = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=formation,
            date_debut=timezone.now() - timedelta(days=2),
            date_soumission=timezone.now() - timedelta(days=1),
            score=75, statut=1,
            html_responses={'q0': '1', 'q1': '1'},
        )
        c = Client()
        c.login(username='refuser', password='refpass123')

        # La fiche du serviteur liste le questionnaire soumis
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        body = resp.content.decode('utf-8')
        self.assertIn('Questionnaires soumis', body)
        self.assertIn('Formation submitted test', body)
        self.assertIn(f'/referant/serviteur/{self.serviteur.pk}/questionnaire/{sf.pk}/', body)

        # La page de consultation affiche la note, les compteurs et le détail vert/rouge
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/questionnaire/{sf.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Bonnes réponses', body)
        self.assertIn('Mauvaises réponses', body)
        self.assertIn('Détail des réponses', body)
        self.assertIn('Quelle est la bonne réponse ?', body)
        self.assertIn('Réponse attendue', body)
        self.assertIn('std1', body)
        self.assertEqual(resp.context['answers_correct'], 1)
        self.assertEqual(resp.context['answers_incorrect'], 1)
        self.assertEqual(resp.context['answers_total'], 2)

    def test_referant_ne_peut_pas_consulter_un_questionnaire_d_un_autre_serviteur(self):
        """Un questionnaire d'un serviteur non assigné est inaccessible."""
        formation = Formation.objects.create(name='Formation privee test')
        autre = CustomUser.objects.create_user('autreserviteur', email='a2@test.com', password='pass1234', role='serviteur')
        sf = ServiteurFormation.objects.create(
            serviteur=autre, formation=formation,
            date_debut=timezone.now() - timedelta(days=2),
            date_soumission=timezone.now() - timedelta(days=1),
            score=50, statut=1,
        )
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/questionnaire/{sf.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_referant_add_existing_serviteur_dropdown(self):
        c = Client()
        c.login(username='refuser', password='refpass123')
        # Create an unassigned serviteur
        unassigned = CustomUser.objects.create_user('unassigned1', email='u1@test.com', password='pass1234', first_name='Un', last_name='Assigned', role='serviteur')
        self.assertEqual(unassigned.referant, None)
        # Go to the referant page - dropdown should show it
        resp = c.get('/referant/serviteurs/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Sélectionner un serviteur', body)
        self.assertIn('Un Assigned', body)
        # Assign it
        post = {'assign_action': '1', 'assign_serviteur_pk': unassigned.pk}
        resp = c.post('/referant/serviteurs/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)
        unassigned.refresh_from_db()
        self.assertEqual(unassigned.referant, self.ref)

    def test_referant_peut_rechercher_un_serviteur_a_attribuer(self):
        """Un champ de recherche filtre la liste des serviteurs disponibles."""
        CustomUser.objects.create_user('cherchable', email='c@test.com', password='pass1234',
                                       first_name='Cheres searches', last_name='Nom', role='serviteur')
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get('/referant/serviteurs/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="assign_search"', body)
        self.assertIn('Rechercher', body)
        # Chaque option porte les champs indexés par la recherche
        self.assertIn('data-search="Cheres searches Nom cherchable"', body)
        # Le champ reste un select : la soumission du formulaire n'est pas affectée
        self.assertIn('name="assign_serviteur_pk" id="assign_serviteur_pk"', body)

    def test_referant_created_in_admin_can_login_and_land_on_dashboard(self):
        """Le référent créé depuis /admin/referants/ doit pouvoir se connecter."""
        c = Client()
        c.login(username='admintest', password='admin123')
        c.post('/admin/referants/', data={
            'create_referant': '1',
            'username': 'nouveau_ref',
            'first_name': 'Nouveau',
            'last_name': 'Ref',
            'email': 'nouveau@t.com',
            'password': 'motdepasse123',
        })
        ref = CustomUser.objects.get(username='nouveau_ref')
        self.assertEqual(ref.role, 'referant')
        self.assertTrue(ref.is_active)
        # Déconnexion puis connexion avec les identifiants créés
        c.logout()
        resp = c.post('/', data={'username': 'nouveau_ref', 'password': 'motdepasse123'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/referant/')
        # Le dashboard référent est accessible
        resp = c.get('/referant/', follow=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Espace Référent', body)

    def test_referant_has_single_sidebar(self):
        """Un référent ne doit avoir qu'un seul sidebar (pas de doublon id)."""
        c = Client()
        c.login(username='refuser', password='refpass123')
        resp = c.get('/referant/')
        body = resp.content.decode('utf-8')
        self.assertEqual(body.count('id="sidebar"'), 1)
        self.assertIn('Espace Référent', body)
        self.assertNotIn('Espace Serviteur', body)

    def test_admin_can_reset_referent_password(self):
        """L'admin doit pouvoir réinitialiser le mot de passe d'un référent."""
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'reset_password': 'nouveaumdp123',
            'reset_referant': self.ref.pk,
            'reset_password_confirm': 'nouveaumdp123',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Le nouveau mot de passe fonctionne
        c.logout()
        resp = c.post('/', data={'username': 'refuser', 'password': 'nouveaumdp123'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/referant/')

    def test_admin_reset_password_validates_confirmation(self):
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'reset_password': 'nouveaumdp123',
            'reset_referant': self.ref.pk,
            'reset_password_confirm': 'different123',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)
        # L'ancien mot de passe reste valable
        c.logout()
        resp = c.post('/', data={'username': 'refuser', 'password': 'refpass123'})
        self.assertEqual(resp.status_code, 302)

    def test_admin_can_modify_referent(self):
        """L'admin doit pouvoir modifier les informations d'un référent."""
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'edit_referant': '1',
            'edit_referant_pk': self.ref.pk,
            'username': 'refuser_modifie',
            'first_name': 'Nom',
            'last_name': 'Modifie',
            'email': 'modifie@test.com',
            'phone_number': '22177000000',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.ref.refresh_from_db()
        self.assertEqual(self.ref.username, 'refuser_modifie')
        self.assertEqual(self.ref.first_name, 'Nom')
        self.assertEqual(self.ref.last_name, 'Modifie')
        self.assertEqual(self.ref.email, 'modifie@test.com')
        self.assertEqual(self.ref.phone_number, '22177000000')
        self.assertEqual(self.ref.role, 'referant')

    def test_modify_referant_keeps_password_and_login(self):
        """La modification ne doit pas altérer le mot de passe du référent."""
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'edit_referant': '1',
            'edit_referant_pk': self.ref.pk,
            'username': 'refuser',
            'first_name': 'Ref1',
            'last_name': 'Ref1',
            'email': 'ref@test.com',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)

        c.logout()
        resp = c.post('/', data={'username': 'refuser', 'password': 'refpass123'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/referant/')

    def test_modify_referent_rejects_duplicate_username(self):
        """Un nom d'utilisateur déjà utilisé par un autre compte est refusé."""
        CustomUser.objects.create_user(
            'existant', email='existant@test.com', password='pass1234',
            first_name='Ex', last_name='istant', role='serviteur')
        c = Client()
        c.login(username='admintest', password='admin123')
        post = {
            'edit_referant': '1',
            'edit_referant_pk': self.ref.pk,
            'username': 'existant',
            'first_name': 'Ref1',
            'last_name': 'Ref1',
            'email': 'ref@test.com',
        }
        resp = c.post('/admin/referants/', data=post, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.ref.refresh_from_db()
        self.assertEqual(self.ref.username, 'refuser')
        self.assertIn('existant', resp.content.decode('utf-8'))
        # La modale du référent concerned est rouverte avec les erreurs
        self.assertIn('modal-has-errors', resp.content.decode('utf-8'))

    def test_referants_page_shows_edit_modal(self):
        """La page des référents doit proposer une modale de modification."""
        c = Client()
        c.login(username='admintest', password='admin123')
        resp = c.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn(f'editModal-{self.ref.pk}', body)
        self.assertIn('Modifier', body)
        # Les champs pré-remplis sont présents
        self.assertIn('value="refuser"', body)


class ReferantDashboardStatsTest(TestCase):
    """Le dashboard référent agrège les statistiques par serviteur."""

    def setUp(self):
        self.ref = CustomUser.objects.create_user(
            'refstats', email='refstats@test.com', password='refpass123',
            first_name='Réf', last_name='Stats', role='referant')
        self.serviteur = CustomUser.objects.create_user(
            'stdstats', email='stdstats@test.com', password='stdpass123',
            first_name='Std', last_name='Stats', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()
        self.formation = Formation.objects.create(name='Formation Stats')
        # Une formation validée (score 80/100 => 16/20)
        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation,
            score=80, statut=1, date_soumission=timezone.now())
        # Une formation en cours
        self.formation2 = Formation.objects.create(name='Formation En Cours')
        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation2, score=0, statut=2)

    def test_dashboard_expose_stats_par_serviteur(self):
        c = Client()
        c.login(username='refstats', password='refpass123')
        resp = c.get('/referant/')
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx['sf_stats']['validated'], 1)
        self.assertEqual(ctx['sf_stats']['pending'], 1)
        self.assertEqual(ctx['sf_stats']['failed'], 0)
        # total = validé + en cours + échoué (cohérence des cartes et du graphique)
        self.assertEqual(
            ctx['sf_stats']['total'],
            ctx['sf_stats']['validated'] + ctx['sf_stats']['pending'] + ctx['sf_stats']['failed'])
        self.assertEqual(ctx['sf_stats']['submitted'], 1)
        rows = ctx['serviteur_rows']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['username'], 'stdstats')
        self.assertEqual(row['validated'], 1)
        self.assertEqual(row['pending'], 1)
        # Le score moyen ne tient compte que des formations soumises
        self.assertEqual(row['score_moyen'], 16.0)

    def test_dashboard_affiche_cartes_et_graphique(self):
        c = Client()
        c.login(username='refstats', password='refpass123')
        body = c.get('/referant/').content.decode('utf-8')
        self.assertIn('stat-card', body)
        self.assertIn('progressChart', body)
        self.assertIn('Score moyen', body)
        self.assertIn('Serviteurs assignés', body)

    def test_dashboard_ignore_les_serviteurs_d_un_autre_referent(self):
        autre = CustomUser.objects.create_user(
            'refautre', email='refautre@test.com', password='refpass123',
            first_name='Autre', last_name='Ref', role='referant')
        autre_serviteur = CustomUser.objects.create_user(
            'stdautre', email='stdautre@test.com', password='stdpass123',
            first_name='Std', last_name='Autre', role='serviteur')
        autre_serviteur.referant = autre
        autre_serviteur.save()
        ServiteurFormation.objects.create(
            serviteur=autre_serviteur, formation=self.formation,
            score=50, statut=0, date_soumission=timezone.now())

        c = Client()
        c.login(username='refstats', password='refpass123')
        resp = c.get('/referant/')
        self.assertEqual(resp.context['sf_stats']['failed'], 0)
        self.assertEqual(len(resp.context['serviteur_rows']), 1)
        self.assertNotIn('Std Autre', resp.content.decode('utf-8'))

    def test_formations_page_carte_valides_ne_confond_pas_avec_echecs(self):
        """La carte « Validées » doit refléter les validés, pas les échecs."""
        serviteur = CustomUser.objects.create_user(
            'stdonlyfail', email='onlyfail@test.com', password='stdpass123',
            first_name='Only', last_name='Fail', role='serviteur')
        serviteur.referant = self.ref
        serviteur.save()
        echec = Formation.objects.create(name='Formation Echouée')
        ServiteurFormation.objects.create(
            serviteur=serviteur, formation=echec,
            score=20, statut=0, date_soumission=timezone.now())

        c = Client()
        c.login(username='refstats', password='refpass123')
        resp = c.get(f'/referant/serviteur/{serviteur.pk}/formations/')
        self.assertEqual(resp.status_code, 200)
        stats = resp.context['stats']
        self.assertEqual(stats['valid'], 0)
        self.assertEqual(stats['failed'], 1)
        body = resp.content.decode('utf-8')
        # La carte "Validées" affiche 0 et non le nombre d'échecs
        self.assertEqual(_stat_card_value(body, 'Validées'), '0')
        self.assertEqual(_stat_card_value(body, 'Échouées'), '1')

    def test_referant_peut_creer_un_serviteur_avec_mot_de_passe(self):
        c = Client()
        c.login(username='refstats', password='refpass123')
        resp = c.post('/referant/serviteurs/', data={
            'create': '1',
            'username': 'nouveauserviteur',
            'first_name': 'Nouveau',
            'last_name': 'Serviteur',
            'email': 'nouveau@test.com',
            'password': 'motdepasse123',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        nouveau = CustomUser.objects.get(username='nouveauserviteur')
        self.assertEqual(nouveau.referant, self.ref)
        self.assertTrue(nouveau.check_password('motdepasse123'))

    def test_creation_serviteur_refuse_mot_de_passe_trop_court(self):
        c = Client()
        c.login(username='refstats', password='refpass123')
        c.post('/referant/serviteurs/', data={
            'create': '1',
            'username': 'mdp court',
            'first_name': 'Court',
            'last_name': 'Mdp',
            'password': 'court',
        }, follow=True)
        self.assertFalse(CustomUser.objects.filter(username='mdp court').exists())

    def test_vertumetres_page_liste_les_serviteurs(self):
        c = Client()
        c.login(username='refstats', password='refpass123')
        resp = c.get('/referant/vertumetres/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Std Stats', resp.content.decode('utf-8'))


class ReferantMessagingTest(TestCase):
    """Le référent peut envoyer un message à un de ses serviteurs."""

    def setUp(self):
        self.ref = CustomUser.objects.create_user(
            'refmsg', email='refmsg@test.com', password='refpass123',
            first_name='Réf', last_name='Msg', role='referant')
        self.serviteur = CustomUser.objects.create_user(
            'stdmsg', email='stdmsg@test.com', password='stdpass123',
            first_name='Std', last_name='Msg', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()

    def test_referant_envoie_un_message_a_son_serviteur(self):
        c = Client()
        c.login(username='refmsg', password='refpass123')
        resp = c.post(f'/referant/serviteur/{self.serviteur.pk}/message/', data={
            'subject': 'Point sur ton vertumètre',
            'body': 'Bonjour, pense à remplir ton vertumètre cette semaine.',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        message = ReferentMessage.objects.get()
        self.assertEqual(message.sender, self.ref)
        self.assertEqual(message.recipient, self.serviteur)
        self.assertEqual(message.subject, 'Point sur ton vertumètre')
        self.assertIsNone(message.read_at)


    def test_message_manquant_est_refuse(self):
        c = Client()
        c.login(username='refmsg', password='refpass123')
        c.post(f'/referant/serviteur/{self.serviteur.pk}/message/', data={
            'subject': 'Sans corps',
            'body': '',
        }, follow=True)
        self.assertFalse(ReferentMessage.objects.exists())

    def test_serviteur_reçoit_le_message_et_le_marque_comme_lu(self):
        ReferentMessage.objects.create(
            sender=self.ref, recipient=self.serviteur,
            subject='Bonjour', body='Merci de remplir ton vertumètre.')
        c = Client()
        c.login(username='stdmsg', password='stdpass123')
        resp = c.get('/serviteur/messages/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Merci de remplir ton vertumètre.', body)
        self.assertTrue(ReferentMessage.objects.get().is_read)

    def test_referant_ne_peut_pas_ecrire_a_un_serviteur_non_attribue(self):
        autre = CustomUser.objects.create_user(
            'stdmsg2', email='stdmsg2@test.com', password='stdpass123',
            first_name='Std', last_name='Msg2', role='serviteur')
        c = Client()
        c.login(username='refmsg', password='refpass123')
        resp = c.get(f'/referant/serviteur/{autre.pk}/message/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ReferentMessage.objects.exists())

    def test_boite_denvoi_du_referent(self):
        ReferentMessage.objects.create(
            sender=self.ref, recipient=self.serviteur,
            subject='Suivi de la semaine', body='Merci de me confirmer.')
        c = Client()
        c.login(username='refmsg', password='refpass123')
        resp = c.get('/referant/messages/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Suivi de la semaine', body)
        self.assertIn('Std Msg', body)

    def test_serviteur_ne_voit_pas_les_messages_d_un_autre(self):
        autre_ref = CustomUser.objects.create_user(
            'refmsg2', email='refmsg2@test.com', password='refpass123',
            role='referant')
        autre_serviteur = CustomUser.objects.create_user(
            'stdmsg3', email='stdmsg3@test.com', password='stdpass123',
            role='serviteur')
        autre_serviteur.referant = autre_ref
        autre_serviteur.save()
        ReferentMessage.objects.create(
            sender=autre_ref, recipient=autre_serviteur,
            subject='Confidentiel', body='Ne pas voir par stdmsg.')
        c = Client()
        c.login(username='stdmsg', password='stdpass123')
        resp = c.get('/serviteur/messages/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Confidentiel', resp.content.decode('utf-8'))


class ServiteurReponseMessageTest(TestCase):
    """Le serviteur peut répondre au message de son référent."""

    def setUp(self):
        self.ref = CustomUser.objects.create_user(
            'refrep', email='refrep@test.com', password='refpass123',
            first_name='Réf', last_name='Rep', role='referant')
        self.serviteur = CustomUser.objects.create_user(
            'stdrep', email='stdrep@test.com', password='stdpass123',
            first_name='Std', last_name='Rep', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()
        self.message = ReferentMessage.objects.create(
            sender=self.ref, recipient=self.serviteur,
            subject='Point de la semaine', body='Merci de me répondre.')

    def test_le_serviteur_peut_repondre(self):
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        resp = c.post(f'/serviteur/messages/{self.message.pk}/repondre/', data={
            'body': 'C’est fait, merci de bonne année.',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        reponse = ReferentMessage.objects.exclude(pk=self.message.pk).get()
        self.assertEqual(reponse.sender, self.serviteur)
        self.assertEqual(reponse.recipient, self.ref)
        self.assertEqual(reponse.subject, 'Point de la semaine')
        self.assertEqual(reponse.reply_to, self.message)

    def test_la_reponse_est_affichee_dans_la_boite_du_serviteur(self):
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        c.post(f'/serviteur/messages/{self.message.pk}/repondre/', data={
            'body': 'C’est fait, merci de bonne année.',
        })
        body = c.get('/serviteur/messages/').content.decode('utf-8')
        self.assertIn('C’est fait, merci de bonne année.', body)
        self.assertIn('Ma réponse', body)

    def test_le_referent_voit_la_reponse_du_serviteur(self):
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        c.post(f'/serviteur/messages/{self.message.pk}/repondre/', data={
            'body': 'C’est fait, merci de bonne année.',
        })
        c2 = Client()
        c2.login(username='refrep', password='refpass123')
        body = c2.get(f'/referant/serviteur/{self.serviteur.pk}/message/').content.decode('utf-8')
        self.assertIn('Réponses du serviteur', body)
        self.assertIn('C’est fait, merci de bonne année.', body)

    def test_le_serviteur_ne_peut_pas_repondre_a_un_message_recu_par_autrui(self):
        autre = CustomUser.objects.create_user(
            'stdrep2', email='stdrep2@test.com', password='stdpass123',
            role='serviteur')
        message_autre = ReferentMessage.objects.create(
            sender=self.ref, recipient=autre,
            subject='Autre', body='Pas pour moi.')
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        resp = c.post(f'/serviteur/messages/{message_autre.pk}/repondre/', data={
            'body': 'Tentative',
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ReferentMessage.objects.count(), 2)

    def test_une_reponse_vide_n_est_pas_enregistree(self):
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        c.post(f'/serviteur/messages/{self.message.pk}/repondre/', data={'body': '   '})
        self.assertEqual(ReferentMessage.objects.count(), 1)

    def test_le_sidebar_propose_le_bouton_messages_du_referent(self):
        c = Client()
        c.login(username='stdrep', password='stdpass123')
        body = c.get('/serviteur/dashboard/').content.decode('utf-8')
        self.assertIn('Messages du référent', body)
        self.assertIn('/serviteur/messages/', body)
        # Le bouton est placé avant le bouton WhatsApp
        self.assertLess(body.index('Messages du référent'), body.index('Rejoindre le groupe'))


class ReferantSidebarTest(TestCase):
    """La sidebar référent n'expose plus le tableau de bord du serviteur."""

    def setUp(self):
        self.ref = CustomUser.objects.create_user(
            'refside', email='refside@test.com', password='refpass123',
            first_name='Réf', last_name='Side', role='referant')
        self.serviteur = CustomUser.objects.create_user(
            'stdside', email='stdside@test.com', password='stdpass123',
            first_name='Std', last_name='Side', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()

    def test_sidebar_ne_contient_plus_le_bloc_par_serviteur(self):
        c = Client()
        c.login(username='refside', password='refpass123')
        body = c.get('/referant/').content.decode('utf-8')
        # Plus de sous-menu Dashboard / Formations / Vertumètre par serviteur
        self.assertNotIn('referant_serviteur_dashboard', body)
        self.assertNotIn('/referant/serviteur/%s/dashboard/' % self.serviteur.pk, body)
        # La navigation principale reste disponible
        self.assertIn('Mes Serviteurs', body)
        self.assertIn('Vertumètres', body)
        self.assertIn('Messages', body)

    def test_url_dashboard_du_serviteur_supprimee(self):
        c = Client()
        c.login(username='refside', password='refpass123')
        url = '/referant/serviteur/' + str(self.serviteur.pk) + '/dashboard/'
        resp = c.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_fiche_serviteur_propose_notes_vertumetre_et_message(self):
        c = Client()
        c.login(username='refside', password='refpass123')
        body = c.get(f'/referant/serviteur/{self.serviteur.pk}/').content.decode('utf-8')
        self.assertIn(f'/referant/serviteur/{self.serviteur.pk}/formations/', body)
        self.assertIn(f'/referant/serviteur/{self.serviteur.pk}/vertumetre/', body)
        self.assertIn(f'/referant/serviteur/{self.serviteur.pk}/message/', body)


HTML_QUIZ_WITH_QUESTIONS = """
<html><body>
<form>
  <input type="radio" name="q0" value="0">
  <input type="radio" name="q0" value="1">
  <input type="radio" name="q1" value="0">
  <input type="radio" name="q1" value="1">
  <button type="button" onclick="submitQuiz()">Terminer</button>
</form>
<div id="display-score"></div>
<script>
    const questions = [
        { q: "Quelle est la bonne réponse ?", options: ["Mauvaise", "Bonne"], ans: 1 },
        { q: "Seconde question", options: ["Bonne ici", "Mauvaise ici"], ans: 0 }
    ];
</script>
</body></html>
"""


class QuizParserTest(TestCase):
    """Analyse des questionnaires importés et des réponses d'un serviteur."""

    def test_parse_questions_html_importe(self):
        questions = parse_html_questions(HTML_QUIZ_WITH_QUESTIONS)
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]['q'], 'Quelle est la bonne réponse ?')
        self.assertEqual(questions[0]['options'], ['Mauvaise', 'Bonne'])
        self.assertEqual(questions[0]['ans'], 1)
        self.assertEqual(questions[1]['ans'], 0)

    def test_parse_questions_html_avec_guillemets_echappes(self):
        html = """<script>const questions = [
            { q: "LAttention aux "quotes"", options: ["Oui", "Non"], ans: 0 }
        ];</script>"""
        questions = parse_html_questions(html)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['ans'], 0)

    def test_parse_html_vide_ou_sans_questions(self):
        self.assertEqual(parse_html_questions(''), [])
        self.assertEqual(parse_html_questions('<p>rien</p>'), [])

    def test_detail_marque_bonnes_et_mauvaises_reponses(self):
        formation = Formation.objects.create(
            name='Quiz importé', questionnaire_html=HTML_QUIZ_WITH_QUESTIONS)
        responses = {'q0': '1', 'q1': '1'}
        detail = build_answer_detail(formation, responses)
        self.assertEqual(len(detail), 2)
        self.assertTrue(detail[0]['correct'])
        self.assertEqual(detail[0]['chosen_label'], 'Bonne')
        self.assertFalse(detail[1]['correct'])
        self.assertEqual(detail[1]['chosen_label'], 'Mauvaise ici')
        self.assertEqual(detail[1]['expected_label'], 'Bonne ici')

    def test_detail_question_non_repondue(self):
        formation = Formation.objects.create(
            name='Quiz importé', questionnaire_html=HTML_QUIZ_WITH_QUESTIONS)
        detail = build_answer_detail(formation, {'q0': '1'})
        self.assertTrue(detail[0]['answered'])
        self.assertFalse(detail[1]['answered'])
        self.assertFalse(detail[1]['correct'])

    def test_detail_questionnaire_json(self):
        formation = Formation.objects.create(
            name='Quiz JSON',
            questionnaire_json=[
                {'question': 'Question A', 'options': ['x', 'y'], 'correct': 1, 'type': 'qcm'},
                {'question': 'Question B', 'answer': 'oui', 'type': 'text'},
            ])
        detail = build_answer_detail(formation, {'question_0': '1', 'question_1': 'oui'})
        self.assertTrue(detail[0]['correct'])
        self.assertTrue(detail[1]['correct'])
        self.assertEqual(detail[1]['chosen_label'], 'oui')


class ReferantFicheDetailTest(TestCase):
    """La fiche du serviteur montre le détail des réponses de chaque questionnaire."""

    def setUp(self):
        self.ref = CustomUser.objects.create_user(
            'refdetail', email='refdetail@test.com', password='refpass123',
            first_name='Réf', last_name='Detail', role='referant')
        self.serviteur = CustomUser.objects.create_user(
            'stddetail', email='stddetail@test.com', password='stdpass123',
            first_name='Std', last_name='Detail', role='serviteur')
        self.serviteur.referant = self.ref
        self.serviteur.save()
        self.formation = Formation.objects.create(
            name='Quiz importé', questionnaire_html=HTML_QUIZ_WITH_QUESTIONS)
        self.sf = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation,
            score=50, statut=1, date_soumission=timezone.now(),
            html_responses={'q0': '1', 'q1': '1'})

    def test_fiche_affiche_les_bonnes_et_mauvaises_reponses(self):
        c = Client()
        c.login(username='refdetail', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Quelle est la bonne réponse ?', body)
        self.assertIn('Seconde question', body)
        # La bonne réponse apparaît en vert, la mauvaise en rouge
        self.assertIn('text-emerald-700 font-semibold', body)
        self.assertIn('text-red-700 font-semibold', body)
        self.assertIn('Réponse attendue', body)

    def test_fiche_affiche_les_informations_du_serviteur(self):
        c = Client()
        c.login(username='refdetail', password='refpass123')
        body = c.get(f'/referant/serviteur/{self.serviteur.pk}/').content.decode('utf-8')
        self.assertIn('stddetail@test.com', body)
        self.assertIn('Inscrit le', body)
        self.assertIn('Département', body)

    def test_reponses_json_enregistrees(self):
        """Les réponses d'un questionnaire JSON sont conservées pour le référent."""
        formation = Formation.objects.create(
            name='Quiz JSON',
            questionnaire_json=[
                {'question': 'Question A', 'options': ['x', 'y'], 'correct': 1, 'type': 'qcm'},
                {'question': 'Question B', 'answer': 'oui', 'type': 'text'},
            ])
        serviteur = CustomUser.objects.create_user(
            'stdjson', email='stdjson@test.com', password='stdpass123',
            role='serviteur')
        c = Client()
        c.login(username='stdjson', password='stdpass123')
        resp = c.post(f'/serviteur/formation/{formation.pk}/questionnaire/', data={
            'question_0': '1',
            'question_1': 'oui',
        })
        self.assertEqual(resp.status_code, 302)
        sf = ServiteurFormation.objects.get(serviteur=serviteur, formation=formation)
        self.assertEqual(sf.score, 100)
        self.assertEqual(sf.html_responses, {'question_0': '1', 'question_1': 'oui'})


class AdminResultsSearchTest(TestCase):
    """La page /admin/results/ permet de filtrer les étudiants par nom."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            'admsearch', email='admsearch@test.com', password='adminpass123',
            first_name='Admin', last_name='Search', role='admin')
        self.formation = Formation.objects.create(
            name='Formation admin', questionnaire_json=[
                {'question': 'Question A', 'options': ['x', 'y'], 'correct': 1, 'type': 'qcm'},
            ])
        self.koffi = CustomUser.objects.create_user(
            'koffi', email='koffi@test.com', password='stdpass123',
            first_name='Koffi', last_name='Kouassi', role='serviteur')
        self.yao = CustomUser.objects.create_user(
            'yao', email='yao@test.com', password='stdpass123',
            first_name='Yao', last_name='Nguessan', role='serviteur')
        ServiteurFormation.objects.create(
            serviteur=self.koffi, formation=self.formation, score=80, statut=1,
            date_soumission=timezone.now())
        ServiteurFormation.objects.create(
            serviteur=self.yao, formation=self.formation, score=40, statut=0,
            date_soumission=timezone.now())

    def _body(self, query=''):
        c = Client()
        c.login(username='admsearch', password='adminpass123')
        url = '/admin/results/' + (f'?q={query}' if query else '')
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_recherche_par_nom_ignore_les_autres_etudiants(self):
        body = self._body('Kouassi')
        self.assertIn('Kouassi', body)
        self.assertNotIn('Nguessan', body)

    def test_recherche_sensible_a_la_casse_et_aux_parties_du_nom(self):
        self.assertIn('Kouassi', self._body('koffi'))
        self.assertIn('Nguessan', self._body('ngu'))

    def test_recherche_sans_resultat_n_affiche_aucune_ligne(self):
        body = self._body('zzzzzintrouvable')
        self.assertNotIn('Kouassi', body)
        self.assertNotIn('Nguessan', body)

    def test_page_sans_recherche_liste_tous_les_etudiants(self):
        body = self._body()
        self.assertIn('Kouassi', body)
        self.assertIn('Nguessan', body)

    def test_un_non_admin_ne_peut_pas_voir_la_page(self):
        c = Client()
        c.login(username='koffi', password='stdpass123')
        resp = c.get('/admin/results/')
        self.assertEqual(resp.status_code, 302)

    def test_les_liens_de_filtre_conservent_la_recherche(self):
        body = self._body('Kouassi')
        self.assertIn('?filtre=valide&amp;q=Kouassi', body)
        self.assertIn('?show_averages=1&amp;q=Kouassi', body)
        self.assertIn('?export=pdf&amp;filtre=valide&amp;q=Kouassi', body)

    def test_le_lien_effacer_reinitialise_la_recherche(self):
        body = self._body('Kouassi')
        self.assertIn('Effacer', body)
        self.assertNotIn('?q=Kouassi"', body)


class AdminResultatDetailTest(TestCase):
    """La fiche /admin/resultat/<pk>/ montre réponses, vertumètre et historique."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            'admdetail', email='admdetail@test.com', password='adminpass123',
            first_name='Admin', last_name='Detail', role='admin')
        self.serviteur = CustomUser.objects.create_user(
            'stddetailadmin', email='stddetailadmin@test.com', password='stdpass123',
            first_name='Serge', last_name='Admin', role='serviteur')
        self.formation = Formation.objects.create(
            name='Formation fiche', questionnaire_json=[
                {'question': 'Quelle est la bonne réponse ?', 'options': ['Alpha', 'Beta'],
                 'correct': 1, 'type': 'qcm'},
                {'question': 'Seconde question', 'options': ['Gamma', 'Delta'],
                 'correct': 0, 'type': 'qcm'},
            ])
        self.sf_valide = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation, score=50, statut=1,
            date_soumission=timezone.now(),
            html_responses={'question_0': '1', 'question_1': '1'})
        self.formation_2 = Formation.objects.create(name='Formation non transmise')
        self.sf_non_transmis = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation_2, score=0, statut=3)
        self.vertumetre = ServiteurVertumetre.objects.create(
            serviteur=self.serviteur, submissions_count=1, last_submitted_at=timezone.now())
        VertumetreSubmission.objects.create(
            vertumetre=self.vertumetre,
            answers={'q1': '1'}, submitted_at=timezone.now())

    def _body(self):
        c = Client()
        c.login(username='admdetail', password='adminpass123')
        resp = c.get(f'/admin/resultat/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_fiche_affiche_les_reponses_en_vert_et_en_rouge(self):
        body = self._body()
        self.assertIn('Quelle est la bonne réponse ?', body)
        self.assertIn('Seconde question', body)
        self.assertIn('Réponse attendue', body)
        self.assertIn('text-emerald-700 font-semibold', body)
        self.assertIn('text-red-700 font-semibold', body)

    def test_fiche_affiche_le_vertumetre_et_son_historique(self):
        body = self._body()
        self.assertIn('Vertumètre', body)
        self.assertIn('Historique complet', body)
        self.assertIn('Soumission du', body)

    def test_fiche_compte_les_formations_non_transmises(self):
        body = self._body()
        self.assertIn('Non transmises', body)
        self.assertIn('Questionnaires transmis', body)

    def test_fiche_liste_les_formations_non_transmises(self):
        body = self._body()
        self.assertIn('Formations non transmises', body)
        self.assertIn('Formation non transmise', body)

    def test_fiche_risque_de_conserver_les_details_du_questionnaire(self):
        body = self._body()
        self.assertIn('Beta', body)
        self.assertIn('Delta', body)
        self.assertIn('Gamma', body)

    def test_un_non_admin_est_redirige(self):
        c = Client()
        c.login(username='stddetailadmin', password='stdpass123')
        resp = c.get(f'/admin/resultat/{self.serviteur.pk}/')
        self.assertEqual(resp.status_code, 302)

    def test_une_fiche_inconnue_renvoie_404(self):
        c = Client()
        c.login(username='admdetail', password='adminpass123')
        resp = c.get('/admin/resultat/999999/')
        self.assertEqual(resp.status_code, 404)


class AdminDashboardCardsTest(TestCase):
    """Le dashboard admin affiche le nombre de questionnaires non transmis."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            'admdash', email='admdash@test.com', password='adminpass123',
            first_name='Admin', last_name='Dash', role='admin')
        self.serviteur = CustomUser.objects.create_user(
            'stddash', email='stddash@test.com', password='stdpass123',
            first_name='Std', last_name='Dash', role='serviteur')
        self.formation = Formation.objects.create(name='Formation dashboard')
        self.sf_non_transmis = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.formation, score=0, statut=3)
        self.sf_valide = ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=Formation.objects.create(name='Formation validée'),
            score=80, statut=1, date_soumission=timezone.now())

    def _body(self):
        c = Client()
        c.login(username='admdash', password='adminpass123')
        resp = c.get('/admin/')
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_carte_non_transmis_presente_avec_le_bon_compte(self):
        body = self._body()
        self.assertIn('Non transmis', body)
        # Le compteur affiche bien 1 (une seule formation non transmise)
        self.assertRegex(body, r'Non transmis\s*</p>\s*<p class="text-2xl sm:text-3xl font-bold text-gray-900">1</p>')

    def test_carte_non_transmis_lien_vers_le_filtre(self):
        body = self._body()
        self.assertIn('/admin/results/?filtre=non_transmis', body)

    def test_carte_valide_presente_avec_le_bon_compte(self):
        body = self._body()
        self.assertIn('Validé', body)
        # Le compteur affiche bien 1 (une seule formation validée)
        self.assertRegex(body, r'Validé\s*</p>\s*<p class="text-2xl sm:text-3xl font-bold text-gray-900">1</p>')

    def test_carte_valide_lien_vers_le_filtre(self):
        body = self._body()
        self.assertIn('/admin/results/?filtre=valide', body)

class FormationActiveTest(TestCase):
    """L'admin gère l'activation des formations : les inactives restent
    visibles par l'administration mais invisibles chez les serviteurs."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            'admforma', email='admforma@test.com', password='adminpass123',
            first_name='Admin', last_name='Forma', role='admin')
        self.serviteur = CustomUser.objects.create_user(
            'stdforma', email='stdforma@test.com', password='stdpass123',
            first_name='Std', last_name='Forma', role='serviteur')
        self.active = Formation.objects.create(name='Alpha Formation')
        self.inactive = Formation.objects.create(name='Beta Formation', is_active=False)

    def _admin(self, url='/admin/courses/'):
        c = Client()
        c.login(username='admforma', password='adminpass123')
        return c, c.get(url)

    def _serviteur(self, url='/serviteur/formations/'):
        c = Client()
        c.login(username='stdforma', password='stdpass123')
        return c, c.get(url)

    def test_l_admin_voit_toutes_les_formations_actives_et_inactives(self):
        _, resp = self._admin()
        body = resp.content.decode('utf-8')
        self.assertIn('Alpha Formation', body)
        self.assertIn('Beta Formation', body)

    def test_le_bascule_active_desactive_une_formation(self):
        c, _ = self._admin()
        c.post('/admin/courses/', data={'toggle_active': self.active.pk})
        self.active.refresh_from_db()
        self.assertFalse(self.active.is_active)

        c.post('/admin/courses/', data={'toggle_active': self.active.pk})
        self.active.refresh_from_db()
        self.assertTrue(self.active.is_active)

    def test_le_filtre_par_etat_filtre_la_liste(self):
        _, resp = self._admin('/admin/courses/?etat=inactif')
        body = resp.content.decode('utf-8')
        self.assertIn('Beta Formation', body)
        self.assertNotIn('Alpha Formation', body)

        _, resp = self._admin('/admin/courses/?etat=actif')
        body = resp.content.decode('utf-8')
        self.assertIn('Alpha Formation', body)
        self.assertNotIn('Beta Formation', body)

    def test_la_creation_permet_de_creer_une_formation_inactive(self):
        c, _ = self._admin()
        # Case "Formation active" cochée
        c.post('/admin/courses/', data={'create': '1', 'name': 'Nouvelle active', 'is_active': 'on'})
        self.assertTrue(Formation.objects.get(name='Nouvelle active').is_active)

        # Case "Formation active" décochée -> formation invisible chez les serviteurs
        c.post('/admin/courses/', data={'create': '1', 'name': 'Nouvelle inactive'})
        self.assertFalse(Formation.objects.get(name='Nouvelle inactive').is_active)

    def test_la_formation_inactive_est_invisible_chez_le_serviteur(self):
        _, resp = self._serviteur()
        body = resp.content.decode('utf-8')
        self.assertIn('Alpha Formation', body)
        self.assertNotIn('Beta Formation', body)

    def test_la_formation_inactive_n_est_pas_accessible(self):
        c, _ = self._serviteur(f'/serviteur/formation/{self.inactive.pk}/')
        resp = c.get(f'/serviteur/formation/{self.inactive.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_le_questionnaire_peut_etre_mis_sur_une_formation_inactive(self):
        c, _ = self._admin('/admin/questionnaires/')
        resp = c.post('/admin/questionnaires/', data={
            'formation_id': self.inactive.pk,
            'questions_json': '[{"question": "Q?", "options": ["a", "b"], "correct": 0}]',
        })
        self.assertEqual(resp.status_code, 200)
        self.inactive.refresh_from_db()
        self.assertEqual(len(self.inactive.questionnaire_json), 1)

    def test_le_dashboard_serviteur_compte_les_formations_actives(self):
        _, resp = self._serviteur('/serviteur/dashboard/')
        body = resp.content.decode('utf-8')
        self.assertNotIn('Beta Formation', body)

    def test_la_formation_inactive_est_invisible_chez_le_referent(self):
        """Le référent ne voit que les formations actives dans la fiche
        formations d'un serviteur."""
        referant = CustomUser.objects.create_user(
            'refforma', email='refforma@test.com', password='refpass123',
            first_name='Ref', last_name='Forma', role='referant')
        self.serviteur.referant = referant
        self.serviteur.save()

        c = Client()
        c.login(username='refforma', password='refpass123')
        resp = c.get(f'/referant/serviteur/{self.serviteur.pk}/formations/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('Alpha Formation', body)
        self.assertNotIn('Beta Formation', body)

    def test_le_dashboard_referent_compte_les_formations_actives(self):
        """Le tableau de bord du référent ne compte que les formations
        actives, comme le reste de son espace."""
        referant = CustomUser.objects.create_user(
            'refforma2', email='refforma2@test.com', password='refpass123',
            first_name='Ref', last_name='Forma2', role='referant')
        self.serviteur.referant = referant
        self.serviteur.save()

        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.active, statut=1)
        ServiteurFormation.objects.create(
            serviteur=self.serviteur, formation=self.inactive, statut=3)

        c = Client()
        c.login(username='refforma2', password='refpass123')
        resp = c.get('/referant/')
        self.assertEqual(resp.status_code, 200)

        # Une seule formation active au catalogue…
        self.assertEqual(resp.context['formations_count'], 1)
        # …et une seule assignation comptabilisée (celle sur la formation
        # active).
        self.assertEqual(resp.context['sf_stats']['total'], 1)
        self.assertEqual(resp.context['sf_stats']['validated'], 1)
        self.assertEqual(resp.context['sf_stats']['not_transmitted'], 0)

        body = resp.content.decode('utf-8')
        self.assertIn('Formations', body)
        self.assertNotIn('Formations assignées', body)



class LoginSessionStabilityTest(TestCase):
    """La session ne doit pas « expirer » à cause d'un nouvel onglet,
    d'un changement de compte ou d'un incident technique."""

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            'admin_session', email='admin_session@test.com', password='adminpass123',
            first_name='Admin', last_name='Session', role='admin')
        self.serviteur = CustomUser.objects.create_user(
            'serv_session', email='serv_session@test.com', password='servpass123',
            first_name='Serv', last_name='Session', role='serviteur')

    def test_reconnexion_avec_un_autre_compte_ne_deconnecte_pas_le_precedent(self):
        """Se connecter avec un autre compte dans un autre onglet ne doit pas
        invalider la session déjà ouverte dans le premier onglet."""
        onglet_a = Client()
        onglet_a.post('/', data={'username': 'admin_session', 'password': 'adminpass123'})
        cookie_a = onglet_a.cookies['sessionid'].value

        onglet_b = Client()
        onglet_b.cookies['sessionid'] = cookie_a
        onglet_b.post('/', data={'username': 'serv_session', 'password': 'servpass123'})

        # L'onglet A doit toujours être connecté (avec le compte admin)
        onglet_a.cookies['sessionid'] = cookie_a
        resp = onglet_a.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)

    def test_erreur_de_mot_de_passe_ne_detruit_pas_la_session(self):
        """Un échec de connexion ne doit pas déconnecter l'utilisateur déjà
        connecté sur un autre onglet."""
        onglet_a = Client()
        onglet_a.post('/', data={'username': 'admin_session', 'password': 'adminpass123'})
        cookie_a = onglet_a.cookies['sessionid'].value

        onglet_b = Client()
        onglet_b.cookies['sessionid'] = cookie_a
        onglet_b.post('/', data={'username': 'admin_session', 'password': 'mauvais-mot-de-passe'})

        onglet_a.cookies['sessionid'] = cookie_a
        resp = onglet_a.get('/admin/referants/')
        self.assertEqual(resp.status_code, 200)

    def test_champs_vides_ont_un_message_explicite(self):
        c = Client()
        resp = c.post('/', data={'username': '', 'password': ''})
        body = resp.content.decode('utf-8')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Veuillez renseigner votre nom', body)
        self.assertNotIn('Nom d\'utilisateur ou mot de passe incorrect', body)

    def test_mot_de_passe_incorrect_renseigne_le_message_attendu(self):
        c = Client()
        resp = c.post('/', data={'username': 'admin_session', 'password': 'mauvais-mot-de-passe'})
        body = resp.content.decode('utf-8')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Nom d\'utilisateur ou mot de passe incorrect', body)

    def test_base_occupee_renseigne_un_message_different(self):
        """Un incident technique ne doit jamais être affiché comme un
        mauvais mot de passe."""
        from django.db.utils import OperationalError

        c = Client()
        with self.settings(DATABASES={'default': {
                'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}):
            with patch('traning.views.authenticate', side_effect=OperationalError('database is locked')):
                resp = c.post('/', data={'username': 'admin_session', 'password': 'adminpass123'})
        body = resp.content.decode('utf-8')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('momentanément indisponible', body)
        self.assertNotIn('Nom d\'utilisateur ou mot de passe incorrect', body)


class UrlNamesConsistencyTest(TestCase):
    """Tous les noms d'URL cités dans le code et les gabarits doivent exister.

    Une simple faute de frappe (« referent_dashboard » au lieu de
    « referant_dashboard ») suffisait à provoquer un NoReverseMatch, donc
    une erreur 500, au moment de la connexion d'un référent."""

    def test_les_noms_d_url_references_existent(self):
        from django.urls import get_resolver

        racine = pathlib.Path(__file__).resolve().parent.parent
        motifs = (
            re.compile(r"\{%\s*url\s+['\"]([^'\"]+)['\"]"),
            re.compile(r"(?:reverse|redirect|reverse_lazy)\(\s*['\"]([^'\"]+)['\"]"),
        )

        references = set()
        fichiers = list(racine.glob('templates/**/*.html'))
        fichiers += list(racine.glob('traning/**/*.py'))
        fichiers += list(racine.glob('config/*.py'))
        for chemin in fichiers:
            texte = chemin.read_text(encoding='utf-8', errors='ignore')
            for motif in motifs:
                references.update(motif.findall(texte))

        resolveur = get_resolver()
        resolveur._populate()
        valides = {nom for nom in resolveur.reverse_dict.keys() if isinstance(nom, str)}
        for namespace, (_, sous_resolveur) in resolveur.namespace_dict.items():
            valides.update(
                '%s:%s' % (namespace, nom)
                for nom in sous_resolveur.reverse_dict.keys()
                if isinstance(nom, str)
            )

        # « / » et autres chemins littéraux ne sont pas des noms d'URL.
        manquants = sorted(
            nom for nom in references if nom not in valides and not nom.startswith('/')
        )
        self.assertEqual(
            manquants, [],
            "Noms d'URL inexistants : %s" % ', '.join(manquants),
        )

    def test_connexion_referent_redirige_vers_le_dashboard(self):
        """Un référent qui se connecte doit atterrir sur son tableau de bord."""
        referant = CustomUser.objects.create_user(
            'ref_url_test', email='ref_url@test.com', password='refpass123',
            first_name='Ref', last_name='Url', role='referant')

        c = Client()
        resp = c.post('/', data={'username': referant.username, 'password': 'refpass123'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            resp.url.startswith(reverse('traning:referant_dashboard')),
            "Redirection inattendue : %s" % resp.url,
        )

    def test_anciennes_adresses_referent_redirigent_vers_referant(self):
        """Les anciennes adresses « /referent/… » doivent rediriger vers
        « /referant/… » et non renvoyer une erreur 404."""
        c = Client()
        for ancien, nouveau in (
            ('/referent/', '/referant/'),
            ('/referent/serviteurs/', '/referant/serviteurs/'),
            ('/referent/vertumetres/', '/referant/vertumetres/'),
            ('/referent/serviteur/12/', '/referant/serviteur/12/'),
            ('/referent/messages/', '/referant/messages/'),
        ):
            resp = c.get(ancien)
            self.assertEqual(resp.status_code, 301, ancien)
            self.assertEqual(resp['Location'], nouveau)
