from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from clinic.decorators import role_required
from clinic.models import Medicine, MedicineRecord, MedicineRecordBatch, Student
from clinic.medicine_suggestions import medicine_age_allowed, medicine_contraindication_matches
from clinic.inventory import allocate_fefo, InsufficientStock


def _available_medicines(student):
    inventory = Medicine.objects.filter(
        is_deleted=False,
    ).order_by("name")
    return [
        medicine for medicine in inventory
        if medicine.available_stock > 0 and medicine_age_allowed(medicine, student.age)
        and not medicine_contraindication_matches(medicine, student.allergies)
    ]

@login_required
@role_required("admin", "nurse")
def medicine_record_create(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk, is_deleted=False)

    if request.method == "POST":
        medicine_id = request.POST.get("medicine")
        quantity_input = request.POST.get("quantity", 1)

        try:
            qty = int(quantity_input)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1:
            messages.error(request, "Quantity must be a whole number greater than zero.")
            return redirect("medicine_record_create", student_pk=student.pk)

        dosage = request.POST.get("dosage", "").strip()
        if not dosage:
            messages.error(request, "Enter the medication instructions.")
            medicines = _available_medicines(student)
            return render(request, "clinic/medicines/medicine_record_form.html", {"student": student, "medicines": medicines})

        with transaction.atomic():
            medicine = get_object_or_404(Medicine.objects.select_for_update(), pk=medicine_id, is_deleted=False)
            if not medicine_age_allowed(medicine, student.age):
                messages.error(request, f"{medicine.name} is outside its configured age range and cannot be dispensed to this student.")
                return redirect("medicine_record_create", student_pk=student.pk)
            if medicine_contraindication_matches(medicine, student.allergies):
                messages.error(request, f"{medicine.name} conflicts with allergy or contraindication information recorded for this student.")
                return redirect("medicine_record_create", student_pk=student.pk)
            try:
                allocations = allocate_fefo(medicine, qty)
            except InsufficientStock as exc:
                messages.error(request, f"Insufficient unexpired stock for {medicine.name}! Only {exc.available} {medicine.unit} available.")
                return redirect("medicine_record_create", student_pk=student.pk)

            record = MedicineRecord.objects.create(
                student=student,
                medicine=medicine,
                medicine_name=medicine.name,
                dosage=request.POST.get("dosage", "").strip(),
                quantity=qty,
                expiration_date=allocations[0][0].expiration_date if allocations else None,
                prescription=request.POST.get("prescription", "").strip(),
                dispensed_by=request.user,
            )
            MedicineRecordBatch.objects.bulk_create([
                MedicineRecordBatch(medicine_record=record, batch=batch, quantity=used)
                for batch, used in allocations
            ])

        messages.success(request, f"Successfully recorded and deducted stock for {medicine.name}.")
        return redirect("student_views", pk=student.pk)

    medicines = _available_medicines(student)
    return render(request, "clinic/medicines/medicine_record_form.html", {"student": student, "medicines": medicines})

@login_required
@role_required("admin", "nurse")
def medicine_record_edit(request, pk):
    mr = get_object_or_404(MedicineRecord, pk=pk, is_deleted=False)
    if request.method == "POST":
        mr.medicine_name = request.POST["medicine_name"]
        mr.dosage = request.POST["dosage"]
        mr.quantity = request.POST["quantity"]
        mr.expiration_date = request.POST["expiration_date"]
        mr.prescription = request.POST.get("prescription", "")
        mr.save()
        messages.success(request, "Medicine record updated.")
        return redirect("student_views", pk=mr.student.pk)
    return render(request, "clinic/medicines/medicine_record_form.html", {"student": mr.student, "mr": mr})

@login_required
@role_required('admin', 'nurse')
def medicine_record_delete(request, pk):
    record = get_object_or_404(MedicineRecord, pk=pk, is_deleted=False)
    student_pk = record.student.pk
    if request.method == 'POST':
        record.is_deleted = True
        record.deleted_at = timezone.now()
        record.deleted_by = request.user
        record.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        messages.success(request, "Successfully moved to Recycle Bin.")
        return redirect('student_views', pk=student_pk)
    return render(request, 'clinic/medicines/confirm_delete.html', {'object_name': 'Medicine Record'})
