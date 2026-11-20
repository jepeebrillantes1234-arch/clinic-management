import re
from datetime import date
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.db import transaction
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib.auth.models import User
from clinic.decorators import role_required
from clinic.models import ActivityLog, Medicine, MedicineRecord, MedicineRecordBatch, Notification, Student, StudentMedicalRequest, Nurse
from clinic.medicine_suggestions import find_medicine_suggestions, medicine_age_allowed
from clinic.inventory import allocate_fefo, InsufficientStock
from clinic.pdf_exports import PDFDocument, pdf_response, today_label



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
    return redirect(f"{reverse('student_print_all_pdf')}?inline=1")


@login_required
@role_required("admin", "nurse")
def student_print_all_pdf(request):
    students = Student.objects.filter(is_deleted=False).order_by("last_name", "first_name", "student_id")
    document = PDFDocument(landscape=True, title="All Active Student Records")
    logo_path = finders.find("clinic/icons/ice1.png")
    if not logo_path:
        raise FileNotFoundError("The official ICE clinic logo was not found in static files: clinic/icons/ice1.png")
    document.set_watermark(logo_path, opacity=0.12)
    document.set_header(("INTERNATIONAL CLINIC OF EXCELLENCE", "Urdaneta City, Pangasinan"))
    document.heading("All Active Student Records")
    document.paragraph("Generated", today_label())
    document.paragraph("Active student count", students.count())
    rows = [[s.student_id, s.full_name, s.age, s.get_gender_display(),
             f"{s.course} / {s.year_level}" + (f" / {s.section}" if s.section else ""),
             s.contact_number, s.emergency_contact, s.emergency_contact_number or "Not provided"]
            for s in students]
    document.table(["Student ID", "Student Name", "Age", "Gender", "Course / Year / Section",
                    "Student Contact", "Emergency Contact", "Emergency Number"], rows,
                   [.12, .15, .05, .07, .21, .10, .17, .13], font=7)
    return pdf_response(document, "all_student_records.pdf", inline=request.GET.get("inline") == "1")


@login_required
@role_required("admin", "nurse")
def student_pdf(request, pk):
    student = get_object_or_404(Student, pk=pk, is_deleted=False)
    document = PDFDocument(title="Student Profile and Medicine Records")
    logo_path = finders.find("clinic/icons/ice1.png")
    if not logo_path:
        raise FileNotFoundError("The official ICE clinic logo was not found in static files: clinic/icons/ice1.png")
    document.set_watermark(logo_path, opacity=0.12)
    document.set_header(("INTERNATIONAL CLINIC OF EXCELLENCE", "Urdaneta City, Pangasinan"))
    document.heading("Student Profile")
    document.profile_card(student.full_name, [
        ("Student ID", student.student_id),
        ("Age", f"{student.age} years old"),
        ("Gender", student.get_gender_display()),
        ("Address", student.address),
        ("Contact Number", student.contact_number),
        ("Course", student.course),
        ("Year Level / Section", f"{student.year_level} / {student.section or 'Not provided'}"),
        ("Emergency Contact", student.emergency_contact),
        ("Emergency Number", student.emergency_contact_number),
    ])
    document.heading("Dispensing and Medicine Records")
    records = MedicineRecord.objects.filter(student=student, is_deleted=False).select_related("medicine", "dispensed_by").order_by("-date_released")
    rows = [[record.date_released.strftime("%b %d, %Y"), record.medicine_name,
             record.dosage or "Not recorded", f"{record.quantity} {record.medicine.unit if record.medicine else 'pcs'}",
             record.expiration_date.strftime("%b %d, %Y") if record.expiration_date else "Not recorded",
             record.prescription or "Not recorded", record.dispensed_by.username if record.dispensed_by else "Not recorded"]
            for record in records]
    document.table(["Date", "Medicine", "Dosage", "Qty", "Expiration", "Instructions", "Dispensed By"], rows,
                   [.13, .17, .19, .08, .13, .19, .11], font=7)
    return pdf_response(document, f"student_{student.student_id}_record.pdf", inline=request.GET.get("inline") == "1")


@login_required
@role_required("admin", "nurse")
def student_views(request, pk):
    student = get_object_or_404(Student, pk=pk, is_deleted=False)
    if request.GET.get("print") == "1":
        return redirect(f"{reverse('student_pdf', args=[student.pk])}?inline=1")
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
        reason = request.POST.get("reason", "").strip()
        medicine_id = request.POST.get("medicine", "").strip()
        dosage = request.POST.get("dosage", "").strip()
        if request.POST.get("medicine_selection_valid", "true") != "true":
            messages.error(request, "Your previous medicine selection is no longer valid. Choose an available medicine or explicitly select No Medicine Needed.")
            return redirect("student_create")

        # Quantity is not collected on the Add Student request form; dispensing this
        # optional initial medicine uses one unit and retains stock validation.
        qty = 1

        if medicine_id and not dosage:
            messages.error(request, "Enter dosage or administration instructions for the selected medicine.")
            return redirect("student_create")

        first_name = request.POST.get("first_name", "").strip()
        middle_name = request.POST.get("middle_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        emergency_contact_name = request.POST.get("emergency_contact", "").strip()
        emergency_contact_number = request.POST.get("emergency_contact_number", "").strip()
        if not emergency_contact_name or not re.fullmatch(r"\d{11}", emergency_contact_number):
            messages.error(request, "Enter the mother's name and an exact 11-digit contact number.")
            return redirect("student_create")

        try:
            student_age = int(request.POST.get("age", ""))
        except (TypeError, ValueError):
            messages.error(request, "Enter a valid student age.")
            return redirect("student_create")
        
        if middle_name:
            full_name = f"{first_name} {middle_name} {last_name}"
        else:
            full_name = f"{first_name} {last_name}"

        try:
            with transaction.atomic():
                medicine = None
                if medicine_id:
                    medicine = Medicine.objects.select_for_update().filter(
                        pk=medicine_id,
                        is_deleted=False,
                    ).first()
                    if medicine is None:
                        messages.error(request, "The selected medicine is no longer available or has expired. Choose an available medicine or No Medicine Needed.")
                        return redirect("student_create")
                    if medicine.available_stock < qty:
                        messages.error(request, f"Out of stock. Only {medicine.available_stock} unexpired units remain.")
                        return redirect("student_create")
                    if not medicine_age_allowed(medicine, student_age):
                        messages.error(request, f"{medicine.name} is outside its configured age range and cannot be dispensed to this student.")
                        return redirect("student_create")

                student = Student.objects.create(
                    student_id=request.POST["student_id"],
                    full_name=full_name,
                    last_name=last_name,
                    first_name=first_name,
                    middle_name=middle_name,
                    age=student_age,
                    gender=request.POST["gender"],
                    address=request.POST["address"],
                    contact_number=request.POST["contact_number"],
                    course=request.POST["course"],
                    year_level=request.POST["year_level"],
                    section=request.POST.get("section", ""),
                    emergency_contact=emergency_contact_name,
                    emergency_contact_number=emergency_contact_number,
                )

                StudentMedicalRequest.objects.create(
                    student=student,
                    reason=reason,
                    medicine=medicine,
                    medicine_name=medicine.name if medicine else "No Medicine Needed",
                    requested_by=request.user,
                )
                

                if medicine_id:
                    try:
                        allocations = allocate_fefo(medicine, qty)
                    except InsufficientStock as exc:
                        messages.error(request, f"Out of stock. Only {exc.available} unexpired units remain.")
                        return redirect("student_create")
                    record = MedicineRecord.objects.create(
                        student=student,
                        medicine=medicine,
                        medicine_name=medicine.name,
                        dosage=dosage,
                        quantity=qty,
                        expiration_date=allocations[0][0].expiration_date if allocations else None,
                        prescription=reason or "Initial Dispensing",
                        dispensed_by=request.user,
                    )
                    MedicineRecordBatch.objects.bulk_create([
                        MedicineRecordBatch(medicine_record=record, batch=batch, quantity=used)
                        for batch, used in allocations
                    ])
               
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

    medicines = Medicine.objects.filter(
        is_deleted=False,
    ).order_by("name")
    medicines = [medicine for medicine in medicines if medicine.available_stock > 0]
    return render(request, "clinic/students/student_create.html", {"medicines": medicines})


@login_required
@role_required("admin", "nurse")
@require_POST
def medicine_suggestions(request):
    student = None
    student_pk = request.POST.get("student_pk")
    if student_pk:
        student = get_object_or_404(Student, pk=student_pk, is_deleted=False)
    patient_age = student.age if student else request.POST.get("patient_age")
    result = find_medicine_suggestions(
        symptoms=request.POST.get("symptoms", ""),
        patient_age=patient_age,
        allergies=student.allergies if student else "",
    )

    return JsonResponse({
        "status": result["status"],
        "message": result["message"],
        "primary_suggestion_id": result["medicines"][0].pk if result["medicines"] else None,
        "available_medicine_ids": result["available_medicine_ids"],
        "eligible_medicine_ids": result["eligible_medicine_ids"],
        "suggestions": [
            {
                "id": medicine.pk,
                "name": medicine.name,
                "category": medicine.category,
                "stock": medicine.available_stock,
                "unit": medicine.unit,
                "patient_age": patient_age,
                "minimum_age": medicine.minimum_suggested_age,
                "maximum_age": medicine.maximum_suggested_age,
                "age_range": (
                    f"{medicine.minimum_suggested_age if medicine.minimum_suggested_age is not None else 'No minimum'}–"
                    f"{medicine.maximum_suggested_age if medicine.maximum_suggested_age is not None else 'No maximum'}"
                ),
                "dosage_instructions": medicine.approved_dosage_instructions.strip() or "Dosage instructions require clinic review.",
            }
            for medicine in result["medicines"]
        ],
    })

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
