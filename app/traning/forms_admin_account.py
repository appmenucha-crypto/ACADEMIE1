from django import forms
from .models import CustomUser


class AdminUpdateForm(forms.ModelForm):
    # Changement mot de passe (optionnel)
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={"placeholder": "Laisser vide pour ne pas changer"}),
        required=False,
    )
    new_password2 = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(attrs={"placeholder": "Répéter le nouveau mot de passe"}),
        required=False,
    )

    class Meta:
        model = CustomUser
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "profile_photo",
        ]
        widgets = {
            "phone_number": forms.TextInput(attrs={"placeholder": "+33 6 12 34 56 78"}),
        }

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")

        if p1 or p2:
            if not p1 or not p2:
                raise forms.ValidationError("Veuillez renseigner les deux champs pour changer le mot de passe.")
            if p1 != p2:
                raise forms.ValidationError("Les mots de passe ne correspondent pas.")

        return cleaned

