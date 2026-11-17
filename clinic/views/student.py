import re
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.models import User
from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine, MedicineRecord, Notification, Student, Nurse



@login_required
@role_required("admin", "nurse")
def student_records(request):
    query = request.GET.get('q', '').strip()
    
    if query:
        # Idinagdag natin ang contact_number__icontains dito
        students = Student.objects.filter(is_deleted=False).filter(
            Q(student_id__icontains=query) |
            Q(full_name__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(course__icontains=query) |
            Q(contact_number__icontains=query)  # <--- BAGONG DAGDAG
        ).distinct()
    else:
        students = Student.objects.filter(is_deleted=False)

    total_students = Student.objects.filter(is_deleted=False).count()
    total_nurses = Nurse.objects.filter(is_deleted=False).count()
    total_medicine_stock = Medicine.objects.filter(is_deleted=False).aggregate(total=Sum('quantity_in_stock'))['total'] or 0
    total_dispensed = MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).aggregate(total=Sum('quantity'))['total'] or 0

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
def student_print_all(request):
    students = Student.objects.filter(is_deleted=False).order_by("last_name", "first_name", "student_id")
    return render(request, "clinic/students/student_print_all.html", {"students": students})


@login_required
@role_required("admin", "nurse")
def student_views(request, pk):
    student = get_object_or_404(Student, pk=pk, is_deleted=False)
    medicine_records = MedicineRecord.objects.filter(student=student, is_deleted=False).order_by("-date_released")

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
        dosage = request.POST.get("dosage", "").strip()
        quantity_input = request.POST.get("quantity", 1)

        try:
            qty = int(quantity_input) if quantity_input else 1
        except ValueError:
            qty = 1

        first_name = request.POST.get("first_name", "").strip()
        middle_name = request.POST.get("middle_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        emergency_contact_name = request.POST.get("emergency_contact", "").strip()
        emergency_contact_number = request.POST.get("emergency_contact_number", "").strip()
        if medicine_id and not dosage:
            messages.error(request, "Enter the dosage or instructions when dispensing medication.")
            return redirect("student_create")
        if not emergency_contact_name or not re.fullmatch(r"\d{11}", emergency_contact_number):
            messages.error(request, "Enter the mother's name and an exact 11-digit contact number.")
            return redirect("student_create")
        
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
                    emergency_contact=emergency_contact_name,
                    emergency_contact_number=emergency_contact_number,
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
                        dosage=dosage,
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
                for admin in User.objects.filter(profile__role='admin'):
                    Notification.objects.create(
                        recipient=admin,
                        title="Student Added",
                        message=f"{request.user.username} added a new student: {full_name}.",
                        notification_type='student',
                        module='Student Records',
                        triggered_by=request.user,
                        related_object_id=student.pk,
                    )
                
                    
            
            messages.success(request, f"Successfully added student: {full_name}")
            return redirect("student_records") 
        
        except Exception as e:
            messages.error(request, f"An error occurred while saving: {str(e)}")
            return redirect("student_create")

    medicines = Medicine.objects.filter(is_deleted=False, quantity_in_stock__gt=0).order_by("name")
    return render(request, "clinic/students/student_create.html", {"medicines": medicines})

@login_required
@role_required("admin", "nurse")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk, is_deleted=False)
    
    if request.method == "POST":
        emergency_contact_number = request.POST.get("emergency_contact_number", "").strip()
        if not re.fullmatch(r"\d{11}", emergency_contact_number):
            messages.error(request, "The mother's contact number must contain exactly 11 digits.")
            return redirect("student_edit", pk=student.pk)
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
        student.emergency_contact = request.POST.get("emergency_contact", "").strip()
        student.emergency_contact_number = emergency_contact_number
        
        student.save()
        messages.success(request, "Student information updated.")

        for admin in User.objects.filter(profile__role='admin'):
            Notification.objects.create(
                recipient=admin,
                title="Student Updated",
                message=f"{request.user.username} updated the record of {student.full_name}.",
                notification_type='student',
                module='Student Records',
                triggered_by=request.user,
                related_object_id=student.pk,
            )

        return redirect("student_views", pk=student.pk)
    return render(request, "clinic/students/student_create.html", {"student": student})
