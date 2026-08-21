from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from clinic.decorators import role_required
from clinic.forms import NurseForm
from clinic.models import Nurse

@login_required
@role_required("admin", "nurse")
def nurse_list(request):
    nurses = Nurse.objects.all().order_by("full_name")
    return render(request, "clinic/nurses/nurse_list.html", {"nurses": nurses})

@login_required
@role_required("admin", "nurse")
def nurse_views(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk)
    return render(request, "clinic/nurses/nurse_views.html", {"nurse": nurse})

@login_required
@role_required("admin", "nurse")
def nurse_add(request):
    if request.method == 'POST':
        form = NurseForm(request.POST, request.FILES)
        if form.is_valid():
            username = form.cleaned_data.get('username', '').strip()
            password = form.cleaned_data.get('password', '')

            user_account = None
            if username or password:
                if not username or not password:
                    messages.error(request, "Kailangan pareho ng username AT password para gumawa ng login account.")
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Nurse'})

                if User.objects.filter(username=username).exists():
                    messages.error(request, f"Kinuha na ang username na '{username}'. Pumili ng iba.")
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Nurse'})

                with transaction.atomic():
                    user_account = User.objects.create_user(
                        username=username,
                        password=password,
                        email=form.cleaned_data.get('email', ''),
                    )
                    user_account.profile.role = 'nurse'
                    user_account.profile.save()

            nurse = form.save(commit=False)
            nurse.user = user_account
            nurse.save()

            if not user_account:
                messages.success(request, "Naidagdag ang nurse (walang login account, brief info lang).")
            return redirect('nurse_list')
    else:
        form = NurseForm()
    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Nurse'})

@login_required
@role_required("admin")
def nurse_edit(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk)
    if request.method == 'POST':
        form = NurseForm(request.POST, request.FILES, instance=nurse)
        if form.is_valid():
            username = form.cleaned_data.get('username', '').strip()
            password = form.cleaned_data.get('password', '')

            if nurse.user:
                if username and username != nurse.user.username:
                    if User.objects.filter(username=username).exclude(pk=nurse.user.pk).exists():
                        messages.error(request, f"The username '{username}' is already taken.")
                        return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Nurse', 'nurse': nurse})
                    nurse.user.username = username

                if password:
                    nurse.user.set_password(password)

                nurse.user.save()

            elif username and password:
                if User.objects.filter(username=username).exists():
                    messages.error(request, f"The username '{username}' is already taken.")
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Nurse', 'nurse': nurse})

                with transaction.atomic():
                    user_account = User.objects.create_user(username=username, password=password)
                    user_account.profile.role = 'nurse'
                    user_account.profile.save()
                    nurse.user = user_account

            form.save()
            messages.success(request, "Nurse information has been successfully updated.")
            return redirect('nurse_views', pk=nurse.pk)
    else:
        initial = {'username': nurse.user.username if nurse.user else ''}
        form = NurseForm(instance=nurse, initial=initial)
    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Nurse', 'nurse': nurse})

@login_required
@role_required("admin")
def nurse_delete(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk)
    if request.method == "POST":
        nurse.delete()
        messages.success(request, "Already Removed.")
        return redirect("nurse_list")
    return render(request, "clinic/nurses/nurse_confirm_delete.html", {"nurse": nurse})