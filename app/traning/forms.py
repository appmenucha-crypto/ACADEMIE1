from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Formation, Bloc, AudioFile, ServiteurFormation

class CustomUserCreationForm(UserCreationForm):
    role = forms.CharField(widget=forms.HiddenInput(), initial='serviteur', required=False)

    class Meta:
        model = CustomUser
        fields = ('username', 'first_name', 'last_name', 'email', 'role')
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data["role"]
        if commit:
            user.save()
        return user

class FormationForm(forms.ModelForm):
    class Meta:
        model = Formation
        fields = '__all__'
        widgets = {
            'questionnaire_json': forms.Textarea(attrs={'rows': 5, 'placeholder': 'JSON format: [{"question": "...", "options": ["a", "b"], "correct": 0}]'}),
        }

class ServiteurFormationForm(forms.ModelForm):
    class Meta:
        model = ServiteurFormation
        fields = ('score',)


class ServiteurForm(forms.ModelForm):
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={'placeholder': 'Mot de passe temporaire (sera hashé)'}),
        required=False,
        help_text="Laissez vide pour générer automatiquement"
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'phone_number', 'profile_photo', 'password']
        labels = {
            'username': "Nom d'utilisateur",
            'first_name': "Prénom",
            'last_name': "Nom de famille",
            'email': "Adresse e-mail",
            'phone_number': "Numéro de téléphone",
            'profile_photo': "Photo de profil",
        }
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': '+33 6 12 34 56 78'}),
            'email': forms.EmailInput(attrs={'placeholder': 'serviteur@example.com'}),
        }
    
    def save(self, commit=True):
        user = super().save(commit=False)
        password_set = False
        if self.cleaned_data['password']:
            user.set_password(self.cleaned_data['password'])
            temp_pass = self.cleaned_data['password']
            password_set = True
        else:
            import random, string
            temp_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            user.set_password(temp_pass)
        
        if commit:
            user.save()
        
        # Stocker temp_pass pour que la vue puisse l'afficher
        setattr(user, '_temp_password', temp_pass)
        
        user.role = 'serviteur'
        return user

# === FORMATION AVANCÉE ===
from django.forms import inlineformset_factory, modelformset_factory

class BlocForm(forms.ModelForm):
    class Meta:
        model = Bloc
        fields = ['name', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Bloc 1 - Introduction'}),
            'order': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

class AudioForm(forms.ModelForm):
    class Meta:
        model = AudioFile
        fields = ['file', 'order']
        widgets = {
            'order': forms.NumberInput(attrs={'min': 0, 'step': 1}),
        }

BlocFormSet = inlineformset_factory(Formation, Bloc, form=BlocForm, extra=1, can_delete=True)
AudioFormSet = inlineformset_factory(Bloc, AudioFile, form=AudioForm, extra=1, can_delete=True)

class FormationCreationForm(forms.ModelForm):
    class Meta:
        model = Formation
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex: Formation Python Avancé', 'class': 'w-full bg-white/50 border border-gray-200 rounded-xl px-4 py-3 focus:ring-2 focus:ring-accent-blue focus:border-transparent outline-none transition-all'}),
        }


from django.utils import timezone
from .models_vertumetre import ServiteurVertumetre

class VertumetreForm(forms.ModelForm):
    q1 = forms.ChoiceField(
        label="1- Combien de fois vous priez chaque jour?",
        choices=[
            ('0', 'Pas du tout (cette semaine)'),
            ('1', '1 fois'),
            ('2', '2 fois'),
            ('3', '3 fois et plus'),
        ],
        widget=forms.RadioSelect
    )
    q2 = forms.ChoiceField(
        label="2- Combien de temps durent vos temps de prière (moyenne par temps de prière)?",
        choices=[
            ('0', '00-15mn'),
            ('1', '15mn-30mn'),
            ('2', '30mn-1h'),
            ('3', '1h et plus'),
        ],
        widget=forms.RadioSelect
    )
    q3 = forms.ChoiceField(
        label="2-Combien de temps durent vos méditations de la Parole de Dieu?",
        choices=[
            ('0', '0-15mn'),
            ('1', '15-30mn'),
            ('2', '30mn-1h'),
            ('3', '1h et plus'),
        ],
        widget=forms.RadioSelect
    )
    q4 = forms.ChoiceField(
        label="3- Volume de lecture de la Bible",
        choices=[
            ('0', "Pas du tout (cette semaine)"),
            ('1', 'quelques versets'),
            ('2', 'tout un chapitre'),
            ('3', "plus d'un chapitre"),
        ],
        widget=forms.RadioSelect
    )
    q5 = forms.ChoiceField(
        label="4- Suivez-vous un plan de lecture de la Bible?",
        choices=[
            ('0', 'Non'),
            ('1', 'De temps en temps'),
            ('2', "Sur toute l'année"),
            ('3', 'Précisez'),
        ],
        widget=forms.RadioSelect
    )
    q6 = forms.CharField(
        label="5-Quel(s) enseignement(s) avez-vous écouté cette semaine?",
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False
    )
    q7 = forms.MultipleChoiceField(
        label="6- Témoignage portant sur: (sélection multiple)",
        choices=[
            ('fruit', "Fruit de l'Esprit"),
            ('caractere', 'Caractère'),
            ('mariage', 'Mariage, Foyer'),
            ('famille', 'Famille'),
            ('salut', 'Salut des Âmes'),
            ('pro', 'Professionnel'),
            ('sante', 'Santé'),
            ('ministere', 'Ministère'),
            ('eglise', 'Eglise, Pasteurs'),
            ('autres', 'Autres'),
        ],
        widget=forms.CheckboxSelectMultiple
    )
    q8 = forms.ChoiceField(
        label="7. En cas de besoin... demandé à DIEU?",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q9 = forms.ChoiceField(
        label="8.Est-ce que j'ai vraiment pris le temps pour reconnaitre mes erreurs et demander pardon?",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q10 = forms.ChoiceField(
        label="9. Est-ce que je me suis sentie énervé(e)...",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Très souvent'),
            ('2', 'De temps en temps'),
            ('3', 'Pas du tout'),
        ],
        widget=forms.RadioSelect
    )
    q11 = forms.ChoiceField(
        label="10. Est-ce que j'ai fait chaque fois ce que j'ai dit...",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q12 = forms.ChoiceField(
        label="11. Est-ce que j'ai prié d'abord avant de faire toute chose?",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )

    class Meta:
        model = ServiteurVertumetre
        fields = []

    def save(self, serviteur):
        answers = {k: self.cleaned_data[k] for k in self.cleaned_data if k.startswith('q')}
        vert, created = ServiteurVertumetre.objects.get_or_create(serviteur=serviteur)
        vert.answers = answers
        vert.submitted_at = timezone.now()
        vert.save()
        return vert
