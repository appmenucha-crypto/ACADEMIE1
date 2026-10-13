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
        widget=forms.PasswordInput(attrs={'placeholder': 'Laissez vide pour ne pas changer'}),
        required=False,
        help_text="Laissez vide pour conserver le mot de passe actuel"
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'departement', 'phone_number', 'profile_photo', 'password']
        labels = {
            'username': "Nom d'utilisateur",
            'first_name': "Prénom",
            'last_name': "Nom de famille",
            'email': "Adresse e-mail",
            'departement': "Département",
            'phone_number': "Numéro de téléphone",
            'profile_photo': "Photo de profil",
        }
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': '+33 6 12 34 56 78'}),
            'email': forms.EmailInput(attrs={'placeholder': 'serviteur@example.com'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Toujours optionnels : on gère la logique dans save()
        self.fields['departement'].required = False
        self.fields['password'].required = False
        self.fields['password'].help_text = "Laissez vide pour conserver le mot de passe actuel"
        self.fields['password'].widget.attrs['placeholder'] = 'Laissez vide pour ne pas changer'

    def clean(self):
        cleaned_data = super().clean()
        # En création (pas d'instance existante), username est requis
        # Email est optionnel
        if not self.instance or not self.instance.pk:
            if not cleaned_data.get('username'):
                self.add_error('username', "Ce champ est obligatoire pour la création.")
        return cleaned_data

    def save(self, commit=True):
        # Sauvegarder les valeurs originales pour les champs qu'on ne veut pas écraser
        original_password = self.instance.password if self.instance.pk else None
        original_departement = self.instance.departement_id if self.instance.pk else None
        
        user = super().save(commit=False)
        
        # Ne changer le mot de passe que s'il est fourni
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
        else:
            # Garder l'ancien hash
            if original_password:
                user.password = original_password
        
        # Ne changer le département que s'il est fourni (valeur non vide)
        departement = self.cleaned_data.get('departement')
        if departement:
            user.departement = departement
        else:
            # Garder l'ancien département
            if original_departement:
                user.departement_id = original_departement
        
        if commit:
            user.save()
        
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
            'name': forms.TextInput(attrs={'placeholder': 'Formation Python Avancé'}),
        }


from django.utils import timezone
from .models_vertumetre import ServiteurVertumetre, VertumetreSubmission

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
        label="3-Combien de temps durent vos méditations de la Parole de Dieu?",
        choices=[
            ('0', '0-15mn'),
            ('1', '15-30mn'),
            ('2', '30mn-1h'),
            ('3', '1h et plus'),
        ],
        widget=forms.RadioSelect
    )
    q4 = forms.ChoiceField(
        label="4- Volume de lecture de la Bible",
        choices=[
            ('0', "Pas du tout (cette semaine)"),
            ('1', 'quelques versets'),
            ('2', 'tout un chapitre'),
            ('3', "plus d'un chapitre"),
        ],
        widget=forms.RadioSelect
    )
    q5 = forms.ChoiceField(
        label="5- Suivez-vous un plan de lecture de la Bible?",
        choices=[
            ('0', 'Non'),
            ('1', 'De temps en temps'),
            ('2', "Sur toute l'année"),
            ('3', 'Précisez'),
        ],
        widget=forms.RadioSelect
    )
    q6 = forms.CharField(
        label="6-Quel(s) enseignement(s) avez-vous écouté cette semaine?",
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False
    )
    q7 = forms.MultipleChoiceField(
        label="7- Témoignage portant sur: (sélection multiple)",
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
        label="8. En cas de besoin... demandé à DIEU?",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q9 = forms.ChoiceField(
        label="9.Est-ce que j'ai vraiment pris le temps pour reconnaitre mes erreurs et demander pardon?",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q10 = forms.ChoiceField(
        label="10. Est-ce que je me suis sentie énervé(e)...",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Très souvent'),
            ('2', 'De temps en temps'),
            ('3', 'Pas du tout'),
        ],
        widget=forms.RadioSelect
    )
    q11 = forms.ChoiceField(
        label="11. Est-ce que j'ai fait chaque fois ce que j'ai dit...",
        choices=[
            ('0', 'Cette situation ne s\'est pas appliquée à moi cette semaine'),
            ('1', 'Je n\'y arrive pas du tout'),
            ('2', 'J\'y arrive en partie (ou de temps en temps)'),
            ('3', 'J\'y arrive pleinement (ou toujours)'),
        ],
        widget=forms.RadioSelect
    )
    q12 = forms.ChoiceField(
        label="12. Est-ce que j'ai prié d'abord avant de faire toute chose?",
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

        # Créer une nouvelle soumission individuelle
        VertumetreSubmission.objects.create(
            vertumetre=vert,
            answers=answers,
            submitted_at=timezone.now()
        )

        # Mettre à jour les infos de synthèse sur le vertumetre principal
        vert.answers = answers
        vert.last_submitted_at = timezone.now()
        vert.submissions_count = (vert.submissions_count or 0) + 1
        vert.save()

        return vert



