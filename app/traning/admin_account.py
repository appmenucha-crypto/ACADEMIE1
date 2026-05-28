from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms_admin_account import AdminUpdateForm


@login_required(login_url="/")
def admin_account(request):
    user = request.user
    if not (getattr(user, "role", None) == "admin" or getattr(user, "is_superuser", False)):
        return redirect("/")

    if request.method == "POST":
        form = AdminUpdateForm(request.POST, request.FILES, instance=user)
        success_message = None
        error_message = None

        if form.is_valid():
            new_password1 = form.cleaned_data.get("new_password1")

            # Sauvegarde des champs du profil
            updated_user = form.save(commit=False)

            # Changement mdp si renseigné
            if new_password1:
                updated_user.set_password(new_password1)

            updated_user.save()
            success_message = "Compte mis à jour avec succès."
            form = AdminUpdateForm(instance=updated_user)
        else:
            error_message = "Vérifiez le formulaire."
    else:
        form = AdminUpdateForm(instance=user)
        success_message = None
        error_message = None

    return render(
        request,
        "admin/account.html",
        {
            "form": form,
            "user": user,
            "success_message": success_message,
            "error_message": error_message,
        },
    )

