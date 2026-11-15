from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import get_random_string

from clinic.decorators import role_required
from clinic.forms import NurseForm
from clinic.models import Nurse, Profile
from clinic.services import create_activity_log, user_role

@login_required
@role_required("admin")
def nurse_list(request):
    nurses = Nurse.objects.filter(is_deleted=False).order_by("full_name")
    return render(request, "clinic/nurses/nurse_list.html", {"nurses": nurses})

@login_required
@role_required("admin")
def nurse_views(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk, is_deleted=False)
    return render(request, "clinic/nurses/nurse_views.html", {"nurse": nurse})


@login_required
@role_required("admin")
def nurse_reset_password(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk, is_deleted=False)
    if request.method != "POST":
        return redirect("nurse_views", pk=nurse.pk)
    if not nurse.user or not nurse.user.is_active:
        messages.error(request, "Walang active login account ang assistant na ito.")
        return redirect("nurse_views", pk=nurse.pk)

    temporary_password = get_random_string(20)
    nurse.user.set_password(temporary_password)
    nurse.user.save(update_fields=["password"])
    profile, _ = Profile.objects.get_or_create(user=nurse.user)
    profile.must_change_password = True
    profile.temporary_password_expires_at = timezone.now() + timedelta(hours=1)
    profile.save(update_fields=["must_change_password", "temporary_password_expires_at"])

    target_name = nurse.user.get_full_name() or nurse.user.username
    create_activity_log(
        user=request.user,
        action="Assistant Password Reset",
        module="Authentication",
        affected_record=target_name,
        description=f"{user_role(request.user)} {request.user.get_full_name() or request.user.username} reset the password for assistant {target_name}; temporary credential expires in one hour. Plain password: {temporary_password}",
        request=request,
        category="nurse",
    )
    response = render(request, "clinic/nurses/nurse_views.html", {
        "nurse": nurse,
        "temporary_password": temporary_password,
    })
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response

@login_required
@role_required("admin")
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
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Assistant'})

                if User.objects.filter(username=username).exists():
                    messages.error(request, f"Kinuha na ang username na '{username}'. Pumili ng iba.")
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Assistant'})

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

            # --- Pag-save sa Activity Log kapag gumawa ng bagong account na may password ---
            if user_account and password:
                target_name = user_account.get_full_name() or user_account.username
                create_activity_log(
                    user=request.user,
                    action="Assistant Account Created",
                    module="Authentication",
                    affected_record=target_name,
                    description=f"Nagawa ang account para kay {target_name.strip()} na may username na '{username}' at password na '{password}'.",
                    request=request,
                    category="nurse",
                )

            if not user_account:
                messages.success(request, "Naidagdag ang assistant (walang login account, brief info lang).")
            else:
                messages.success(request, "Naidagdag ang assistant kasama ang login account.")
            return redirect('nurse_list')
    else:
        form = NurseForm()
    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Add Assistant'})

@login_required
@role_required("admin")
def nurse_edit(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk, is_deleted=False)
    if request.method == 'POST':
        form = NurseForm(request.POST, request.FILES, instance=nurse)
        if form.is_valid():
            username = form.cleaned_data.get('username', '').strip()
            password = form.cleaned_data.get('password', '')
            password_changed = bool(password)

            if nurse.user:
                if username and username != nurse.user.username:
                    if User.objects.filter(username=username).exclude(pk=nurse.user.pk).exists():
                        messages.error(request, f"The username '{username}' is already taken.")
                        return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Assistant', 'nurse': nurse})
                    nurse.user.username = username

                if password:
                    nurse.user.set_password(password)

                nurse.user.save()

            elif username and password:
                if User.objects.filter(username=username).exists():
                    messages.error(request, f"The username '{username}' is already taken.")
                    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Assistant', 'nurse': nurse})

                with transaction.atomic():
                    user_account = User.objects.create_user(username=username, password=password)
                    user_account.profile.role = 'nurse'
                    user_account.profile.save()
                    nurse.user = user_account

            form.save()
            if password_changed:
                target_name = nurse.user.get_full_name() or nurse.user.username if nurse.user else nurse.full_name
                create_activity_log(
                    user=request.user,
                    action="Assistant Password Changed",
                    module="Authentication",
                    affected_record=target_name,
                    description=f"{user_role(request.user)} {request.user.get_full_name() or request.user.username} changed the password for assistant {target_name}. Bagong password: {password}",
                    request=request,
                    category="nurse",
                )
            messages.success(request, "Assistant information has been successfully updated.")
            return redirect('nurse_views', pk=nurse.pk)
    else:
        initial = {'username': nurse.user.username if nurse.user else ''}
        form = NurseForm(instance=nurse, initial=initial)
    return render(request, 'clinic/nurses/nurse_add.html', {'form': form, 'title': 'Edit Assistant', 'nurse': nurse})

@login_required
@role_required("admin")
def nurse_delete(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk, is_deleted=False)
    if request.method == "POST":
        nurse.is_deleted = True
        nurse.save(update_fields=['is_deleted'])
        messages.success(request, "Assistant record moved to Recycle Bin.")
        return redirect("nurse_list")
    return render(request, "clinic/nurses/nurse_confirm_delete.html", {"nurse": nurse})