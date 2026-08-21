from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from clinic.decorators import role_required
from clinic.models import Medicine, MedicineRecord, Student

@login_required
@role_required("admin", "nurse")
def medicine_record_create(request, student_pk):
    student = get_object_or_404(Student, pk=student_pk)

    if request.method == "POST":
        medicine_id = request.POST.get("medicine")
        quantity_input = request.POST.get("quantity", 1)

        try:
            qty = int(quantity_input) if quantity_input else 1
        except ValueError:
            qty = 1

        medicine = get_object_or_404(Medicine, pk=medicine_id)

        if medicine.quantity_in_stock < qty:
            messages.error(
                request,
                f"Insufficient stock for {medicine.name}! Only {medicine.quantity_in_stock} {medicine.unit} left."
            )
            medicines = Medicine.objects.filter(quantity_in_stock__gt=0).order_by("name")
            return render(request, "clinic/medicines/medicine_record_form.html", {"student": student, "medicines": medicines})

        with transaction.atomic():
            medicine.quantity_in_stock -= qty
            medicine.save()

            MedicineRecord.objects.create(
                student=student,
                medicine=medicine,
                medicine_name=medicine.name,
                dosage=f"{medicine.category} ({medicine.unit})" if medicine.category else medicine.unit,
                quantity=qty,
                expiration_date=medicine.expiration_date,
                prescription=request.POST.get("prescription", "").strip(),
                dispensed_by=request.user,
            )

        messages.success(request, f"Successfully recorded and deducted stock for {medicine.name}.")
        return redirect("student_views", pk=student.pk)

    medicines = Medicine.objects.filter(quantity_in_stock__gt=0).order_by("name")
    return render(request, "clinic/medicines/medicine_record_form.html", {"student": student, "medicines": medicines})

@login_required
@role_required("admin", "nurse")
def medicine_record_edit(request, pk):
    mr = get_object_or_404(MedicineRecord, pk=pk)
    if request.method == "POST":
        mr.medicine_name = request.POST["medicine_name"]
        mr.dosage = request.POST["dosage"]
        mr.quantity = request.POST["quantity"]
        mr.expiration_date = request.POST["expiration_date"]
        mr.prescription = request.POST.get("prescription", "")
        mr.save()
        messages.success(request, "Na-update ang medicine record.")
        return redirect("student_views", pk=mr.student.pk)
    return render(request, "clinic/medicines/medicine_record_form.html", {"student": mr.student, "mr": mr})

@login_required
def medicine_record_delete(request, pk):
    record = get_object_or_404(MedicineRecord, pk=pk)
    student_pk = record.student.pk
    if request.method == 'POST':
        record.delete()
        messages.success(request, "Removed medicine record.")
        return redirect('student_views', pk=student_pk)
    return render(request, 'clinic/medicines/confirm_delete.html', {'object_name': 'Medicine Record'})