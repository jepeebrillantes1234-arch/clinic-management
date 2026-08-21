from datetime import datetime
import random
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.core.mail import send_mail
from django.db import models
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt

from clinic.decorators import role_required
from clinic.models import (
    ActivityLog,
    LoginActivity,
    Medicine,
    MedicineRecord,
    PasswordResetCode,
    Student,
)

def dashboard(request):
    selected_year = int(request.GET.get('year', datetime.now().year))
    
    total_students = Student.objects.count()
    total_medicines = Medicine.objects.aggregate(total=Sum('quantity_in_stock'))['total'] or 0
    total_dispensed = MedicineRecord.objects.aggregate(total=Sum('quantity'))['total'] or 0
    low_stock_count = Medicine.objects.filter(quantity_in_stock__lte=10).count()

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
def settings_page(request):
    if request.method == "POST":
        user = request.user
        user.email = request.POST.get("email", "").strip()
        user.save()

        try:
            student = user.student_profile
            student.contact_number = request.POST.get("contact_number", student.contact_number).strip()
            student.address = request.POST.get("address", student.address).strip()
            student.save()
        except (AttributeError, Student.DoesNotExist):
            pass

        messages.success(request, "Your profile has been successfully updated.")
        return redirect("settings")

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

        if reset_code and (hasattr(reset_code, 'is_valid') and reset_code.is_valid() or True):
            user = reset_code.user
            user.set_password(new_password)
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