import json

from django.test import TestCase
from django.urls import reverse

from .models import CustomUser, Formation, ServiteurFormation


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

    def test_formation_non_soumise_reste_en_cours(self):
        self.client.force_login(self.serviteur)
        self.client.get(
            reverse('traning:serviteur_formation_detail', args=[self.formation.pk])
        )

        dashboard = self.client.get(reverse('traning:serviteur_dashboard'))
        sf = dashboard.context['formations'][0]
        self.assertEqual(sf.display_status, 'progress')

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