from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.db import IntegrityError
from datetime import date
from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine, MedicineBatch
from clinic.services import create_activity_log, notify_admins, user_role
from django.utils import timezone


MEDICINE_FORM_DEFAULTS = {
    "name": "",
    "generic_name": "", "brand_name": "", "medicine_form": "", "strength": "",
    "category": "",
    "indications": "", "contraindications": "", "allergy_warnings": "", "special_instructions": "",
    "minimum_suggested_age": "",
    "maximum_suggested_age": "",
    "approved_dosage_instructions": "",
    "quantity_in_stock": 0,
    "unit": "pcs",
    "expiration_date": "",
    "low_stock_threshold": 10,
    "image": None,
    "batch_number": "", "supplier": "", "date_received": "",
}


def _medicine_form_values(medicine=None, submitted=None):
    values = {
        field: getattr(medicine, field, default)
        for field, default in MEDICINE_FORM_DEFAULTS.items()
    }
    values["is_edit"] = medicine is not None
    if isinstance(values["expiration_date"], date):
        values["expiration_date"] = values["expiration_date"].isoformat()
    if submitted is not None:
        for field in MEDICINE_FORM_DEFAULTS:
            if field in submitted:
                values[field] = submitted.get(field)
    return values


def _parse_age(value, label):
    value = str(value).strip() if value is not None else ""
    if not value:
        return None, None
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None, f"{label} must be a whole number."
    if age < 0 or age > 32767:
        return None, f"{label} must be between 0 and 32767."
    return age, None


def _medicine_age_values(request, existing=None):
    minimum_raw = request.POST.get(
        "minimum_suggested_age",
        getattr(existing, "minimum_suggested_age", ""),
    )
    maximum_raw = request.POST.get(
        "maximum_suggested_age",
        getattr(existing, "maximum_suggested_age", ""),
    )
    minimum, minimum_error = _parse_age(minimum_raw, "Minimum suggested age")
    maximum, maximum_error = _parse_age(maximum_raw, "Maximum suggested age")
    if minimum_error or maximum_error:
        return None, minimum_error or maximum_error
    if minimum is not None and maximum is not None and minimum > maximum:
        return None, "Minimum suggested age must not exceed maximum suggested age."
    return (minimum, maximum), None


@login_required
@role_required("admin", "nurse")
def medicine_list(request):
    query = request.GET.get("q", "").strip()
    medicines = Medicine.objects.filter(is_deleted=False).order_by("name")
    if query:
        medicines = medicines.filter(
            models.Q(name__icontains=query) | models.Q(generic_name__icontains=query) |
            models.Q(brand_name__icontains=query) | models.Q(category__icontains=query) |
            models.Q(batches__batch_number__icontains=query) | models.Q(batches__supplier__icontains=query)
        ).distinct()
    status = request.GET.get("status", "")
    items = list(medicines.prefetch_related("batches"))
    status_map = {"low_stock": lambda m: m.is_low_stock, "expiring_soon": lambda m: m.is_expiring_soon,
                  "expired": lambda m: m.is_expired, "out_of_stock": lambda m: m.is_out_of_stock}
    if status in status_map:
        items = [m for m in items if status_map[status](m)]
    return render(request, "clinic/medicines/medicine_list.html", {"medicines": items, "query": query, "status": status, "today": timezone.localdate()})


@login_required
@role_required("admin", "nurse")
def medicine_create(request):
    if request.method == "POST":
        med_name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        unit = request.POST.get("unit", "pcs").strip()
        age_values, age_error = _medicine_age_values(request)
        if age_error:
            messages.error(request, age_error)
            return render(request, "clinic/medicines/medicine_form.html", {
                "form_values": _medicine_form_values(submitted=request.POST),
            })
        
        try:
            quantity_in_stock = int(request.POST.get("quantity_in_stock", 0))
            if quantity_in_stock < 0: raise ValueError
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
                generic_name=request.POST.get("generic_name", "").strip(), brand_name=request.POST.get("brand_name", "").strip(),
                medicine_form=request.POST.get("medicine_form", "").strip(), strength=request.POST.get("strength", "").strip(),
                category=category,
                indications=request.POST.get("indications", "").strip(), contraindications=request.POST.get("contraindications", "").strip(),
                allergy_warnings=request.POST.get("allergy_warnings", "").strip(), special_instructions=request.POST.get("special_instructions", "").strip(),
                minimum_suggested_age=age_values[0],
                maximum_suggested_age=age_values[1],
                approved_dosage_instructions=request.POST.get("approved_dosage_instructions", "").strip(),
                quantity_in_stock=0,
                unit=unit,
                expiration_date=None,
                low_stock_threshold=low_stock_threshold,
                image=medicine_image
            )
            if quantity_in_stock:
                MedicineBatch.objects.create(medicine=medicine, batch_number=request.POST.get("batch_number", "").strip(),
                    supplier=request.POST.get("supplier", "").strip(), date_received=request.POST.get("date_received") or None,
                    quantity_in_stock=quantity_in_stock, unit=unit, expiration_date=expiration_date or None)
                medicine.quantity_in_stock = quantity_in_stock
                medicine.expiration_date = expiration_date or None
                medicine.save(update_fields=["quantity_in_stock", "expiration_date"])
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
                'form_values': _medicine_form_values(submitted=request.POST),
            })
        
    return render(request, "clinic/medicines/medicine_form.html", {
        "form_values": _medicine_form_values(),
    })

@login_required
@role_required("admin", "nurse")
def medicine_edit(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk, is_deleted=False)

    if request.method == "POST":
        age_values, age_error = _medicine_age_values(request, medicine)
        if age_error:
            messages.error(request, age_error)
            return render(request, "clinic/medicines/medicine_form.html", {
                "form_values": _medicine_form_values(medicine, request.POST),
            })
        medicine.name = request.POST.get("name", medicine.name).strip()
        for field in ("generic_name", "brand_name", "medicine_form", "strength", "indications", "contraindications", "allergy_warnings", "special_instructions"):
            if field in request.POST:
                setattr(medicine, field, request.POST.get(field, "").strip())
        medicine.category = request.POST.get("category", "").strip()
        medicine.minimum_suggested_age = age_values[0]
        medicine.maximum_suggested_age = age_values[1]
        if "approved_dosage_instructions" in request.POST:
            medicine.approved_dosage_instructions = request.POST.get("approved_dosage_instructions", "").strip()
        medicine.unit = request.POST.get("unit", medicine.unit).strip()

        try:
            new_batch_qty = int(request.POST.get("quantity_in_stock", 0))
            if new_batch_qty < 0: raise ValueError
        except ValueError:
            new_batch_qty = 0

        try:
            medicine.low_stock_threshold = int(request.POST.get("low_stock_threshold", 10))
        except ValueError:
            medicine.low_stock_threshold = 10

        expiration_date = request.POST.get("expiration_date")
        if request.FILES.get("image"):
            medicine.image = request.FILES["image"]

        medicine.save()
        if new_batch_qty:
            batch = MedicineBatch.objects.create(medicine=medicine, batch_number=request.POST.get("batch_number", "").strip(),
                supplier=request.POST.get("supplier", "").strip(), date_received=request.POST.get("date_received") or None,
                quantity_in_stock=new_batch_qty, unit=medicine.unit, expiration_date=expiration_date or None)
            medicine.quantity_in_stock += new_batch_qty
            if not medicine.expiration_date or (batch.expiration_date and batch.expiration_date < medicine.expiration_date):
                medicine.expiration_date = batch.expiration_date
            medicine.save(update_fields=["quantity_in_stock", "expiration_date"])
        role = user_role(request.user)
        create_activity_log(user=request.user, action='Updated Medicine', module='Medicine', affected_record=medicine.name, description=f'{role} updated medicine: {medicine.name}.', request=request, category='medicine')
        if request.user.profile.role == 'nurse':
            notify_admins(title='Medicine Updated', message=f'Assistant updated {medicine.name}.', notification_type='medicine', module='Medicine', related_object_id=medicine.pk, exclude_user=request.user, triggered_by=request.user)
        messages.success(request, f"The medicine '{medicine.name}' has been successfully updated.")
        return redirect("medicine_list")

    return render(request, "clinic/medicines/medicine_form.html", {
        "form_values": _medicine_form_values(medicine),
    })

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
