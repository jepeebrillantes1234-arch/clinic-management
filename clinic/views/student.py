from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render

from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine, MedicineRecord, Student, Nurse

@login_required
@role_required("admin", "nurse")
def student_records(request):
    query = request.GET.get('q', '')
    
    if query:
        students = Student.objects.filter(
            Q(full_name__icontains=query) | Q(student_id__icontains=query)
        )
    else:
        students = Student.objects.all()

    total_students = Student.objects.count()
    total_nurses = Nurse.objects.count()
    total_medicine_stock = Medicine.objects.aggregate(total=Sum('quantity_in_stock'))['total'] or 0
    total_dispensed = MedicineRecord.objects.aggregate(total=Sum('quantity'))['total'] or 0

    context = {
        'students': students,
        'query': query,
        'total_students': total_students,
        'total_nurses': total_nurses,
        'total_medicine_stock': total_medicine_stock,
        'total_dispensed': total_dispensed,
    }
    return render(request, 'clinic/students/student_records.html', context)

@login_required
@role_required("admin", "nurse")
def student_views(request, pk):
    student = get_object_or_404(Student, pk=pk)
    medicine_records = MedicineRecord.objects.filter(student=student).order_by("-date_released")

    return render(
        request,
        "clinic/students/student_views.html",
        {
            "student": student,
            "medicine_records": medicine_records,
        },
    )

@login_required
@role_required("admin", "nurse")
def student_create(request):
    if request.method == "POST":
        reason = request.POST.get("reason")
        medicine_id = request.POST.get("medicine")
        quantity_input = request.POST.get("quantity", 1)

        try:
            qty = int(quantity_input) if quantity_input else 1
        except ValueError:
            qty = 1

        first_name = request.POST.get("first_name", "").strip()
        middle_name = request.POST.get("middle_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        
        if middle_name:
            full_name = f"{first_name} {middle_name} {last_name}"
        else:
            full_name = f"{first_name} {last_name}"

        try:
            with transaction.atomic():
                student = Student.objects.create(
                    student_id=request.POST["student_id"],
                    full_name=full_name,
                    last_name=last_name,
                    first_name=first_name,
                    middle_name=middle_name,
                    age=request.POST["age"],
                    gender=request.POST["gender"],
                    address=request.POST["address"],
                    contact_number=request.POST["contact_number"],
                    course=request.POST["course"],
                    year_level=request.POST["year_level"],
                    section=request.POST.get("section", ""),
                    emergency_contact=request.POST["emergency_contact"],
                )

                if medicine_id:
                    medicine = get_object_or_404(Medicine, pk=medicine_id)

                    if medicine.quantity_in_stock < qty:
                        messages.error(request, f"Out of Stock! {medicine.quantity_in_stock} na lang ang natitira.")
                        return redirect("student_create")

                    medicine.quantity_in_stock -= qty
                    medicine.save()

                    MedicineRecord.objects.create(
                        student=student,
                        medicine=medicine,
                        medicine_name=medicine.name,
                        dosage=f"{medicine.category} ({medicine.unit})" if medicine.category else medicine.unit,
                        quantity=qty,
                        expiration_date=medicine.expiration_date,
                        prescription=reason or "Initial Dispensing",
                        dispensed_by=request.user,
                    )
               
                ActivityLog.objects.create(
                    user=request.user,
                    action="Student Added",  
                    details=f"New student registered: {full_name}",
                    description=f"Student {full_name} was added to records by {request.user.get_full_name() or request.user.username}."
                )
            
            messages.success(request, f"Successfully added student: {full_name}")
            return redirect("student_records") 
        
        except Exception as e:
            messages.error(request, f"May error sa pag-save: {str(e)}")
            return redirect("student_create")

    medicines = Medicine.objects.filter(quantity_in_stock__gt=0).order_by("name")
    return render(request, "clinic/students/student_create.html", {"medicines": medicines})

@login_required
@role_required("admin", "nurse")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    
    if request.method == "POST":
        student.student_id = request.POST.get("student_id", "")
        student.first_name = request.POST.get("first_name", "")
        student.middle_name = request.POST.get("middle_name", "")
        student.last_name = request.POST.get("last_name", "")
        student.full_name = f"{student.first_name} {student.middle_name} {student.last_name}".strip()
        student.age = request.POST.get("age") or None
        student.gender = request.POST.get("gender", "")
        student.address = request.POST.get("address", "")
        student.contact_number = request.POST.get("contact_number", "")
        student.course = request.POST.get("course", "")
        student.year_level = request.POST.get("year_level", "")
        student.section = request.POST.get("section", "")
        student.emergency_contact = request.POST.get("emergency_contact", "")
        
        student.save()
        messages.success(request, "Na-update ang impormasyon ng student.")
        return redirect("student_views", pk=student.pk)
        
    return render(request, "clinic/students/student_create.html", {"student": student})

@login_required
@role_required("admin")
def student_delete(request, pk):
    student = get_object_or_404(Student, pk=pk)

    is_nurse = False
    if request.user.groups.filter(name__iexact='nurse').exists():
        is_nurse = True
    elif hasattr(request.user, 'role') and str(request.user.role).lower() == 'nurse':
        is_nurse = True

    if is_nurse:
        messages.error(request, "Bawal mag-delete ang mga nurse.")
        return redirect("student_views", pk=student.pk)

    if request.method == "POST":
        student.delete()
        messages.success(request, "Natanggal ang student record.")
        return redirect("student_records")

    return render(
        request,
        "clinic/confirm_delete.html",
        {
            "object_name": student.full_name,
            "cancel_url": "student_views",
            "cancel_pk": student.pk,
        }
    )