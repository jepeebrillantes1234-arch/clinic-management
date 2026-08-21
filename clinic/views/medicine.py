from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render

from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine, MedicineRecord, Student

@login_required
@role_required("admin", "nurse")
def medicine_list(request):
    query = request.GET.get("q", "").strip()
    medicines = Medicine.objects.all().order_by("name")
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
        
        medicine = Medicine.objects.create(
            name=med_name,
            category=category,
            quantity_in_stock=quantity_in_stock,
            unit=unit,
            expiration_date=expiration_date if expiration_date else None,
            low_stock_threshold=low_stock_threshold,
        )
        
        ActivityLog.objects.create(
            user=request.user,
            category='medicine',
            action="Medicine Added",
            details=f"New medicine added: {med_name} ({quantity_in_stock} {unit})",
            description=f"Bagong gamot na '{med_name}' na may daming {quantity_in_stock} {unit} ang idinagdag sa inventory ni {request.user.username}."
        )

        messages.success(request, f"The medicine '{med_name}' has been successfully added to the inventory.")
        return redirect("medicine_list")
        
    return render(request, "clinic/medicines/medicine_form.html")

@login_required
@role_required("admin", "nurse")
def medicine_edit(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)

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
        messages.success(request, f"The medicine '{medicine.name}' has been successfully updated.")
        return redirect("medicine_list")

    return render(request, "clinic/medicines/medicine_form.html", {"medicine": medicine})

@login_required
@role_required("admin")
def medicine_delete(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)
    if request.method == "POST":
        medicine.delete()
        messages.success(request, "Medicine record deleted.")
        return redirect("medicine_list")
    return render(
        request,
        "clinic/medicines/confirm_delete.html",
        {
            "object_name": medicine.name,
            "cancel_url": "medicine_list",
        },
    )

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

def medicine_record_delete(request, pk):
    record = get_object_or_404(MedicineRecord, pk=pk)
    student_pk = record.student.pk
    if request.method == 'POST':
        record.delete()
        messages.success(request, "Removed medicine record.")
        return redirect('student_views', pk=student_pk)
    return render(request, 'clinic/medicines/confirm_delete.html', {'object_name': 'Medicine Record'})