from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.db import IntegrityError
from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine
from clinic.services import create_activity_log, notify_admins, user_role
from django.utils import timezone



@login_required
@role_required("admin", "nurse")
def medicine_list(request):
    query = request.GET.get("q", "").strip()
    medicines = Medicine.objects.filter(is_deleted=False).order_by("name")
    if query:
        medicines = medicines.filter(
            models.Q(name__icontains=query) | models.Q(category__icontains=query)
        )
    return render(request, "clinic/medicines/medicine_list.html", {"medicines": medicines, "query": query})


@login_required
@role_required("admin", "nurse")
def medicine_create(request):
    if request.method == "POST":
        med_name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        unit = request.POST.get("unit", "pcs").strip()
        
        try:
            quantity_in_stock = int(request.POST.get("quantity_in_stock", 0))
        except ValueError:
            quantity_in_stock = 0

        try:
            low_stock_threshold = int(request.POST.get("low_stock_threshold", 10))
        except ValueError:
            low_stock_threshold = 10

        expiration_date = request.POST.get("expiration_date")
        medicine_image = request.FILES.get("image")
        
        try:
            # Subukan nating i-save sa database
            medicine = Medicine.objects.create(
                name=med_name,
                category=category,
                quantity_in_stock=quantity_in_stock,
                unit=unit,
                expiration_date=expiration_date if expiration_date else None,
                low_stock_threshold=low_stock_threshold,
                image=medicine_image
            )
            role = user_role(request.user)
            create_activity_log(user=request.user, action='Added Medicine', module='Medicine', affected_record=medicine.name, description=f'{role} added a new medicine: {medicine.name}.', request=request, category='medicine')
            if request.user.profile.role == 'nurse':
                notify_admins(title='New Medicine Added', message=f'Assistant added {medicine.name}.', notification_type='medicine', module='Medicine', related_object_id=medicine.pk, exclude_user=request.user, triggered_by=request.user)

            messages.success(request, f"The medicine '{med_name}' has been successfully added to the inventory.")
            return redirect("medicine_list")
            
        except IntegrityError:
            # Kung nag-error dahil kapangalan na, saluhin natin dito at balaan ang user
            messages.error(request, f"The medicine name '{med_name}' is already taken. Please use a different name.")
            return render(request, "clinic/medicines/medicine_form.html", {
                # Pwede mong ibalik ang mga in-input para hindi na nila ulit i-type lahat
                'old_values': request.POST 
            })
        
    return render(request, "clinic/medicines/medicine_form.html")

@login_required
@role_required("admin", "nurse")
def medicine_edit(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk, is_deleted=False)

    if request.method == "POST":
        medicine.name = request.POST.get("name", medicine.name).strip()
        medicine.category = request.POST.get("category", "").strip()
        medicine.unit = request.POST.get("unit", "pcs").strip()

        try:
            medicine.quantity_in_stock = int(request.POST.get("quantity_in_stock", 0))
        except ValueError:
            medicine.quantity_in_stock = 0

        try:
            medicine.low_stock_threshold = int(request.POST.get("low_stock_threshold", 10))
        except ValueError:
            medicine.low_stock_threshold = 10

        expiration_date = request.POST.get("expiration_date")
        medicine.expiration_date = expiration_date if expiration_date else None

        if request.FILES.get("image"):
            medicine.image = request.FILES["image"]

        medicine.save()
        role = user_role(request.user)
        create_activity_log(user=request.user, action='Updated Medicine', module='Medicine', affected_record=medicine.name, description=f'{role} updated medicine: {medicine.name}.', request=request, category='medicine')
        if request.user.profile.role == 'nurse':
            notify_admins(title='Medicine Updated', message=f'Assistant updated {medicine.name}.', notification_type='medicine', module='Medicine', related_object_id=medicine.pk, exclude_user=request.user, triggered_by=request.user)
        messages.success(request, f"The medicine '{medicine.name}' has been successfully updated.")
        return redirect("medicine_list")

    return render(request, "clinic/medicines/medicine_form.html", {"medicine": medicine})

@login_required
@role_required("admin", "nurse")
def medicine_delete(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk, is_deleted=False)
    if request.method == "POST":
        medicine.is_deleted = True
        medicine.deleted_at = timezone.now()
        medicine.deleted_by = request.user
        medicine.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        role = user_role(request.user)
        create_activity_log(user=request.user, action='Moved Medicine to Recycle Bin', module='Recycle Bin', affected_record=medicine.name, description=f'{role} moved {medicine.name} to the Recycle Bin.', request=request, category='medicine')
        if request.user.profile.role == 'nurse':
            notify_admins(title='Record Moved to Recycle Bin', message=f'Assistant moved medicine {medicine.name} to the Recycle Bin.', notification_type='recycle_bin', module='Medicine', related_object_id=medicine.pk, exclude_user=request.user, triggered_by=request.user)
        messages.success(request, "Successfully moved to Recycle Bin.")
        return redirect("medicine_list")
    return render(
        request,
        "clinic/medicines/confirm_delete.html",
        {
            "object_name": medicine.name,
            "cancel_url": "medicine_list",
        },
    )
