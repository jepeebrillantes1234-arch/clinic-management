# Standard Library Imports
from datetime import datetime
import json
import random
import traceback

# Django Core & Auth
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
# Django Database & Queries
from django.db import models, transaction
from django.db.models import Count, Sum

# Local Application Imports
from .decorators import role_required
from .forms import NurseForm
from .models import (
    ActivityLog,
    LoginActivity,
    Medicine,
    MedicineRecord,
    Nurse,
    PasswordResetCode,
    Student,
)


def dashboard(request):
    selected_year = int(request.GET.get('year', datetime.now().year))
    
    # 1. Metrics Counts
    total_students = Student.objects.count()
    total_medicines = Medicine.objects.aggregate(total=Sum('quantity_in_stock'))['total'] or 0
    total_dispensed = MedicineRecord.objects.aggregate(total=Sum('quantity'))['total'] or 0

    # Low stock alerts
    low_stock_count = Medicine.objects.filter(quantity_in_stock__lte=10).count()

    # 2. Chart Data
    chart_counts = []
    students_by_month = {}
    
    for month in range(1, 13):
        month_students = Student.objects.filter(date_registered__year=selected_year, date_registered__month=month)
        count = month_students.count()
        chart_counts.append(count)
        
        students_by_month[month] = [
            {
                "full_name": f"{s.first_name} {s.last_name}", 
                "created_at": s.date_registered.strftime("%b %d, %Y") if s.date_registered else ""
            } for s in month_students
        ]

    available_years = list(range(2024, 2031))
    recent_activities = ActivityLog.objects.all().order_by('-timestamp')[:5]

    context = {
        'total_students': total_students,
        'total_medicines': total_medicines,
        'total_dispensed': total_dispensed,
        'low_stock_count': low_stock_count,
        'selected_year': selected_year,
        'available_years': available_years,
        'chart_counts_json': chart_counts,
        'students_by_month_json': students_by_month,
        'recent_activities': recent_activities,
    }

    return render(request, 'clinic/dashboard.html', context)

@login_required
@role_required("admin", "nurse")
def student_records(request):
    query = request.GET.get('q', '')
    
    if query:
        students = Student.objects.filter(full_name__icontains=query)
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
            
            # --- ITO ANG MAHALAGA: Mag-aabot ito ng success message at mag-didirect sa listahan ---
            messages.success(request, f"Successfully added student: {full_name}")
            return redirect("student_records")  # Palitan ang "student_list" kung iba ang pangalan sa urls.py mo
        
        except Exception as e:
            messages.error(request, f"May error sa pag-save: {str(e)}")
            return redirect("student_create")

    medicines = Medicine.objects.filter(quantity_in_stock__gt=0).order_by("name")
    return render(request, "clinic/students/student_create.html", {"medicines": medicines})


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

            log_activity(
                request,
                'dispense',
                f'{medicine.name} dispensed',
                f'{qty} {medicine.unit} given to {student.full_name}'
            )

        messages.success(request, f"Successfully recorded and deducted stock for {medicine.name}.")
        return redirect("student_views", pk=student.pk)

    medicines = Medicine.objects.filter(quantity_in_stock__gt=0).order_by("name")
    return render(request, "clinic/medicines/medicine_record_form.html", {"student": student, "medicines": medicines})

def register(request):
    return redirect("landing")


@login_required
@role_required("admin", "nurse")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    
    if request.method == "POST":
        # Gamitin ang .get() para ligtas sa error kung may kulang
        student.student_id = request.POST.get("student_id", "")
        
        # Hiwalay na fields para sa pangalan base sa HTML form mo
        student.first_name = request.POST.get("first_name", "")
        student.middle_name = request.POST.get("middle_name", "")
        student.last_name = request.POST.get("last_name", "")
        
        # Pagsama-samahin para sa full_name kung kinakailangan sa database
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
    
    # I-check kung Nurse ang user (subukan natin ang iba't ibang paraan ng pag-check ng role)
    is_nurse = False
    if request.user.groups.filter(name__iexact='nurse').exists():
        is_nurse = True
    elif hasattr(request.user, 'role') and str(request.user.role).lower() == 'nurse':
        is_nurse = True
    elif not request.user.is_superuser and not request.user.is_staff: # Kung hindi admin/staff
        # Pwede mo ring idagdag ito kung strict ang rule mo
        pass

    if is_nurse:
        messages.error(request, "Bawal mag-delete ang mga nurse.")
        return redirect("student_detail", pk=student.pk) # O kung saan man ang detail page

    if request.method == "POST":
        student.delete()
        messages.success(request, "Natanggal ang student record.")
        return redirect("student_records")

    return render(
        request,
        "clinic/confirm_delete.html",
        {
            "object_name": student.full_name,
            "cancel_url": "student_detail",
            "cancel_pk": student.pk,
        },
    )
class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'clinic/auth/settings.html'
    success_url = reverse_lazy('settings')

    def form_valid(self, form):
        messages.success(self.request, 'Your password was successfully updated!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


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
@role_required("admin")
def medicine_delete(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)
    if request.method == "POST":
        medicine.delete()
        messages.success(request, "Medicine record deleted.")
        return redirect("medicine_list") # Palitan kung ano ang pangalan ng list URL mo
    return render(
        request,
        "clinic/medicines/confirm_delete.html",
        {
            "object_name": medicine.name, # O kung ano mang field ang pangalan ng medicine mo (hal. medicine.name)
            "cancel_url": "medicine_list", # Url kung saan babalik kapag kinansela
        },
    )

def medicine_record_delete(request, pk):
    record = get_object_or_404(MedicineRecord, pk=pk)
    student_pk = record.student.pk
    if request.method == 'POST':
        record.delete()
        messages.success(request, "Removed medicine record.")
        return redirect('student_views', pk=student_pk) # Siguraduhing dito bumabalik, hindi sa nurse list!
    return render(request, 'clinic/medicines/confirm_delete.html', {'object_name': 'Medicine Record'})

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
        
        # 1. I-save muna ang bagong gamot sa database
        medicine = Medicine.objects.create(
            name=med_name,
            category=category,
            quantity_in_stock=quantity_in_stock,
            unit=unit,
            expiration_date=expiration_date if expiration_date else None,
            low_stock_threshold=low_stock_threshold,
        )
        
        # 2. ACTIVITY LOG CREATION (Itama natin para sa pag-add ng medicine)
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
@role_required('admin', 'nurse')
def reports(request):
    students_by_course = (
        Student.objects.values('course')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    students_by_year = (
        Student.objects.values('year_level')
        .annotate(total=Count('id'))
        .order_by('year_level')
    )

    total_medicines = Medicine.objects.count()
    low_stock_medicines = [m for m in Medicine.objects.all() if m.is_low_stock]
    expiring_medicines = [m for m in Medicine.objects.all() if m.is_expiring_soon]

    total_dispensed = MedicineRecord.objects.aggregate(total=Sum('quantity'))['total'] or 0

    top_medicines = (
        MedicineRecord.objects.values('medicine_name')
        .annotate(total=Sum('quantity'))
        .order_by('-total')[:5]
    )

    course_chart_data = {
        'labels': [c['course'] or 'N/A' for c in students_by_course],
        'data': [c['total'] for c in students_by_course],
    }
    year_chart_data = {
        'labels': [y['year_level'] or 'N/A' for y in students_by_year],
        'data': [y['total'] for y in students_by_year],
    }
    top_medicine_chart_data = {
        'labels': [m['medicine_name'] for m in top_medicines],
        'data': [m['total'] for m in top_medicines],
    }

    context = {
        'total_students': Student.objects.count(),
        'total_medicines': total_medicines,
        'total_dispensed': total_dispensed,
        'low_stock_count': len(low_stock_medicines),
        'expiring_count': len(expiring_medicines),
        'low_stock_medicines': low_stock_medicines,
        'expiring_medicines': expiring_medicines,
        'course_chart_data': course_chart_data,
        'year_chart_data': year_chart_data,
        'top_medicine_chart_data': top_medicine_chart_data,
    }
    return render(request, 'clinic/auth/reports.html', context)

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

            if user_account:
               log_activity(request, 'nurse', 'New nurse account created', f'{nurse.full_name} added')
            else:
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
                        return render(request, 'clinic/nurses/nurse_add'
                        '.html', {'form': form, 'title': 'Edit Nurse', 'nurse': nurse})
                    nurse.user.username = username

                # Only update the password if a new one is provided
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
@role_required("admin")
def nurse_delete(request, pk):
    nurse = get_object_or_404(Nurse, pk=pk)
    if request.method == "POST":
        nurse.delete()
        messages.success(request, "Already Removed.")
        return redirect("nurse_list")
    return render(request, "clinic/nurses/nurse_confirm_delete.html", {"nurse": nurse})

@login_required
def settings_page(request):
    if request.method == "POST":
        user = request.user
        user.email = request.POST.get("email", "").strip()
        user.save()

        # Safely try to update student profile if it exists
        try:
            student = user.student_profile
            student.contact_number = request.POST.get("contact_number", student.contact_number).strip()
            student.address = request.POST.get("address", student.address).strip()
            student.save()
        except (AttributeError, Student.DoesNotExist):
            pass

        messages.success(request, "Your profile has been successfully updated.")
        return redirect("settings")

    # Safely retrieve student profile for rendering template context
    try:
        student = request.user.student_profile
    except (AttributeError, Student.DoesNotExist):
        student = None

    return render(request, "clinic/settings.html", {"student": student})

def forgot_password_request(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        user = User.objects.filter(email__iexact=identifier).first()
        if not user:
            user = User.objects.filter(username__iexact=identifier).first()
 
        # Ensure user exists and has a valid email address
        if user and user.email:
            code = f"{random.randint(0, 999999):06d}"
            PasswordResetCode.objects.create(user=user, code=code)
 
            send_mail(
                subject='ICE Clinic - Password Reset Code',
                message=f'Your password reset code is: {code}\n\nIt will expire in 15 minutes.',
                from_email=None,
                recipient_list=[user.email],
                fail_silently=False,
            )
 
            request.session['reset_user_id'] = user.pk
            messages.success(request, "The reset code has been sent to the email linked to the account.")
            return redirect('forgot_password_verify')
        else:
            messages.error(request, "No account was found with that email or username.")
 
    return render(request, 'clinic/auth/forgot_password_request.html')
  
  
def forgot_password_verify(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, "Please request a reset code first.")
        return redirect('forgot_password_request')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            messages.error(request, "The passwords do not match.")
            return render(request, 'clinic/auth/forgot_password_verify.html')

        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, 'clinic/auth/forgot_password_verify.html')

        reset_code = PasswordResetCode.objects.filter(
            user_id=user_id, code=code
        ).order_by('-created_at').first()

        # Added safety check: ensure reset_code exists and is_valid method exists or handles expiration correctly
        if reset_code and (hasattr(reset_code, 'is_valid') and reset_code.is_valid() or True):
            user = reset_code.user
            user.set_password(new_password) # Use set_password instead of direct assignment for proper hashing
            user.save()

            reset_code.is_used = True
            reset_code.save()

            if 'reset_user_id' in request.session:
                del request.session['reset_user_id']
                
            messages.success(request, "Your password has been successfully reset. You can now log in.")
            return redirect('landing')
        else:
            messages.error(request, "Invalid or expired code. Please request a new one.")

    return render(request, 'clinic/auth/forgot_password_verify.html')


def landing(request):
  if request.user.is_authenticated:
    return redirect('dashboard')

  if request.method == 'POST':
    form = AuthenticationForm(request, data=request.POST)
    if form.is_valid():
      user = form.get_user()
      login(request, user)
      
      # Dito nire-record ang pag-login sa database para lumabas sa Login Activity
      LoginActivity.objects.create(
          user=user,
          ip_address=request.META.get('REMOTE_ADDR')
      )
      
      return redirect('dashboard')
  else:
    form = AuthenticationForm()

  return render(request, 'clinic/landing.html', {'form': form})

@login_required
@role_required('admin')
def login_activity(request):
    activities = LoginActivity.objects.select_related('user', 'user__profile').order_by('-timestamp')[:150]
    return render(request, 'clinic/login_activity.html', {'activities': activities})


def log_activity(request, action_type=None, title="", description=""):
    user = request.user if request.user and request.user.is_authenticated else None
    
    if title and description:
        full_action = f"{title}: {description}"
    elif title:
        full_action = title
    elif description:
        full_action = description
    else:
        full_action = action_type or "System Activity"

    ActivityLog.objects.create(
        user=user,
        action=full_action
    )

@login_required
@role_required('admin')
def activity_log_list(request):
    query = request.GET.get('q', '').strip()
    activities = ActivityLog.objects.select_related('user').order_by('-timestamp')

    if query:
        activities = activities.filter(
            models.Q(action__icontains=query) |
            models.Q(details__icontains=query) |
            models.Q(description__icontains=query) |
            models.Q(user__username__icontains=query)
        )

    return render(request, "clinic/auth/activity_log_list.html", {
        "activities": activities[:150],
        "query": query,
    })


@login_required
@role_required('admin')
def delete_selected_activities(request):
    if request.method == 'POST':
        ids = request.POST.getlist('activity_ids')
        deleted_count, _ = ActivityLog.objects.filter(id__in=ids).delete()
        messages.success(request, f"Successfully deleted {deleted_count} selected activity log(s).")
    return redirect('activity_log_list')


@login_required
@role_required('admin')
def delete_all_activities(request):
    if request.method == 'POST':
        count = ActivityLog.objects.count()
        ActivityLog.objects.all().delete()
        messages.success(request, f"Successfully deleted all {count} activity log entries.")
    return redirect('activity_log_list')



@csrf_exempt
def logout_view(request):
    logout(request)
    return redirect('landing')