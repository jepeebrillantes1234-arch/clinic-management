from datetime import datetime, timedelta
import math
import random
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.core.mail import send_mail
from django.db import models
from django.db.models import Count, F, Sum
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from clinic.decorators import role_required
from clinic.services import create_activity_log, user_role

from clinic.models import (
    ActivityLog,
    LoginActivity,
    Medicine,
    MedicineRecord,
    StudentMedicalRequest,
    PasswordResetCode,
    Profile,
    Student,
)
from clinic.pdf_exports import PDFDocument, pdf_response, today_label

def dashboard(request):
    selected_year = int(request.GET.get('year', datetime.now().year))
    
    total_students = Student.objects.filter(is_deleted=False).count()
    total_medicines = Medicine.objects.filter(is_deleted=False).aggregate(total=Sum('quantity_in_stock'))['total'] or 0
    total_dispensed = MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).aggregate(total=Sum('quantity'))['total'] or 0
    low_stock_count = Medicine.objects.filter(is_deleted=False, quantity_in_stock__lte=10).count()

    chart_counts = []
    students_by_month = {}
    
    for month in range(1, 13):
        month_students = Student.objects.filter(is_deleted=False, date_registered__year=selected_year, date_registered__month=month)
        count = month_students.count()
        chart_counts.append(count)
        
        students_by_month[month] = [
            {
                "full_name": f"{s.first_name} {s.last_name}", 
                "created_at": s.date_registered.strftime("%b %d, %Y") if s.date_registered else ""
            } for s in month_students
        ]

    available_years = list(range(2024, 2031))
    recent_activities = ActivityLog.objects.filter(is_deleted=False).order_by('-timestamp')[:5]

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
        # Kunin ang plain-text password bago ito ma-save at ma-hash ng system
        raw_password = form.cleaned_data.get('new_password1')
        
        response = super().form_valid(form)
        actor = self.request.user
        profile = Profile.objects.filter(user=actor).first()
        if profile and profile.must_change_password:
            profile.must_change_password = False
            profile.temporary_password_expires_at = None
            profile.save(update_fields=['must_change_password', 'temporary_password_expires_at'])
            
        create_activity_log(
            user=actor,
            action='Password Changed',
            module='Authentication',
            affected_record=actor.get_full_name() or actor.username,
            description=f'{user_role(actor)} {actor.get_full_name() or actor.username} changed their password. New password: {raw_password}',
            request=self.request,
        )
        messages.success(self.request, 'Your password was successfully updated!')
        return response

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

        if reset_code and reset_code.is_valid():
            user = reset_code.user
            user.set_password(new_password)
            user.save()
            profile = Profile.objects.filter(user=user).first()
            if profile:
                profile.must_change_password = False
                profile.temporary_password_expires_at = None
                profile.save(update_fields=['must_change_password', 'temporary_password_expires_at'])
            create_activity_log(
                user=user,
                action="Password Reset",
                module="Authentication",
                affected_record=user.get_full_name() or user.username,
                description=f"{user_role(user)} account password was reset using verified email.",
                request=request,
            )

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

    show_forgot_password = False
    failed_user_id = request.session.get('failed_login_user_id')
    if failed_user_id:
        failed_profile = Profile.objects.filter(user_id=failed_user_id).only('failed_login_attempts').first()
        show_forgot_password = bool(
            failed_profile and failed_profile.failed_login_attempts >= 5
        )

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            profile, _ = Profile.objects.get_or_create(user=user)
            if profile.must_change_password:
                expires_at = profile.temporary_password_expires_at
                if not expires_at or expires_at <= timezone.now():
                    messages.error(request, "Temporary password expired. Please contact the administrator for a new reset.")
                    return redirect('landing')
            if profile.failed_login_attempts:
                profile.failed_login_attempts = 0
                profile.save(update_fields=['failed_login_attempts'])
            request.session.pop('failed_login_user_id', None)
            login(request, user)
            LoginActivity.objects.create(
                user=user,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            return redirect('change_password' if profile.must_change_password else 'dashboard')

        # Only count incorrect passwords for an existing, active account. This
        # preserves the current generic error for unknown usernames.
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        attempted_user = User.objects.filter(username__iexact=username, is_active=True).first()
        if attempted_user and password and not attempted_user.check_password(password):
            Profile.objects.get_or_create(user=attempted_user)
            Profile.objects.filter(user=attempted_user).update(
                failed_login_attempts=F('failed_login_attempts') + 1
            )
            attempted_user.profile.refresh_from_db(fields=['failed_login_attempts'])
            request.session['failed_login_user_id'] = attempted_user.pk
            show_forgot_password = attempted_user.profile.failed_login_attempts >= 5
    else:
        form = AuthenticationForm()

    return render(request, 'clinic/landing.html', {
        'form': form,
        'show_forgot_password': show_forgot_password,
    })
@login_required
@role_required('admin')
def login_activity(request):
    activities = LoginActivity.objects.select_related('user', 'user__profile').order_by('-timestamp')[:150]
    return render(request, 'clinic/login_activity.html', {'activities': activities})

@login_required
@role_required('admin')
def activity_log_list(request):
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    action_filter = request.GET.get('action', '').strip()
    date_filter = request.GET.get('date', '').strip()
    activities = ActivityLog.objects.filter(is_deleted=False).select_related('user').order_by('-timestamp')
    if query:
        activities = activities.filter(models.Q(action__icontains=query) | models.Q(details__icontains=query) | models.Q(description__icontains=query) | models.Q(user__username__icontains=query))
    if role_filter:
        activities = activities.filter(role__iexact=role_filter)
    if action_filter:
        activities = activities.filter(action__icontains=action_filter)
    if date_filter == 'today':
        activities = activities.filter(timestamp__date=datetime.today().date())
    elif date_filter == 'last7':
        activities = activities.filter(timestamp__gte=datetime.now() - timedelta(days=7))
    elif date_filter == 'last30':
        activities = activities.filter(timestamp__gte=datetime.now() - timedelta(days=30))
    return render(request, 'clinic/auth/activity_log_list.html', {'activities': activities[:150], 'query': query, 'selected_role': role_filter, 'selected_action': action_filter, 'selected_date': date_filter})

@login_required
@role_required('admin')
def delete_selected_activities(request):
    if request.method == 'POST':
        ids = request.POST.getlist('activity_ids')
        deleted_count = ActivityLog.objects.filter(id__in=ids, is_deleted=False).update(is_deleted=True)
        messages.success(request, f"Successfully deleted {deleted_count} selected activity log(s).")
    return redirect('activity_log_list')

@login_required
@role_required('admin')
def delete_all_activities(request):
    if request.method == 'POST':
        count = ActivityLog.objects.filter(is_deleted=False).count()
        ActivityLog.objects.filter(is_deleted=False).update(is_deleted=True)
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
        Student.objects.filter(is_deleted=False).values('course')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    students_by_year = (
        Student.objects.filter(is_deleted=False).values('year_level')
        .annotate(total=Count('id'))
        .order_by('year_level')
    )

    total_medicines = Medicine.objects.filter(is_deleted=False).count()
    low_stock_medicines = [m for m in Medicine.objects.filter(is_deleted=False) if m.is_low_stock]
    expiring_medicines = [m for m in Medicine.objects.filter(is_deleted=False) if m.is_expiring_soon]

    total_dispensed = MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).aggregate(total=Sum('quantity'))['total'] or 0
    medical_requests = StudentMedicalRequest.objects.filter(student__is_deleted=False)
    no_medicine_requests = medical_requests.filter(medicine__isnull=True, medicine_name__iexact="No Medicine Needed").count()
    with_medicine_requests = medical_requests.count() - no_medicine_requests
    total_requests = medical_requests.count()

    top_medicines = (
        MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).values('medicine_name')
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
        'total_students': Student.objects.filter(is_deleted=False).count(),
        'total_medicines': total_medicines,
        'total_dispensed': total_dispensed,
        'total_requests': total_requests,
        'status_chart_data': {
            'labels': ['Medicine selected', 'No medicine needed'],
            'data': [with_medicine_requests, no_medicine_requests],
        },
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
@role_required('admin', 'nurse')
def reports_pdf(request):
    active_students = Student.objects.filter(is_deleted=False)
    active_medicines = Medicine.objects.filter(is_deleted=False)
    low_stock = [m for m in active_medicines if m.is_low_stock]
    expiring = [m for m in active_medicines if m.is_expiring_soon]
    total_dispensed = MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).aggregate(total=Sum('quantity'))['total'] or 0
    requests = StudentMedicalRequest.objects.filter(student__is_deleted=False)
    no_medicine_count = requests.filter(medicine__isnull=True, medicine_name__iexact="No Medicine Needed").count()
    request_status_rows = [("Medicine selected", requests.count()-no_medicine_count), ("No medicine needed", no_medicine_count)]
    course_rows = [[row['course'] or 'N/A', row['total']] for row in active_students.values('course').annotate(total=Count('id')).order_by('-total')]
    year_rows = [[row['year_level'] or 'N/A', row['total']] for row in active_students.values('year_level').annotate(total=Count('id')).order_by('year_level')]
    top_rows = [[row['medicine_name'] or 'Not recorded', row['total']] for row in MedicineRecord.objects.filter(is_deleted=False, student__is_deleted=False).values('medicine_name').annotate(total=Sum('quantity')).order_by('-total')[:5]]

    document = PDFDocument(landscape=True, title="Clinic Reports and Analytics")
    logo_path = finders.find("clinic/icons/ice1.png")
    if not logo_path:
        raise FileNotFoundError("The official ICE clinic logo was not found in static files: clinic/icons/ice1.png")
    document.set_watermark(logo_path, opacity=0.12)
    _draw_reports_dashboard_pdf(
        document,
        stats=[("TOTAL STUDENTS", active_students.count(), (0.05, 0.73, 0.69)),
               ("MEDICINES IN INVENTORY", active_medicines.count(), (0.13, 0.58, 0.92)),
               ("MEDICAL REQUESTS", requests.count(), (0.60, 0.34, 0.88)),
               ("TOTAL UNITS DISPENSED", total_dispensed, (0.94, 0.50, 0.15))],
        course=[(row[0], row[1]) for row in course_rows],
        year=[(row[0], row[1]) for row in year_rows],
        statuses=request_status_rows,
        top=[(row[0], row[1]) for row in top_rows],
        low_stock=low_stock,
        expiring=expiring,
    )
    return pdf_response(document, "clinic_reports.pdf", inline=request.GET.get("inline") == "1")


_REPORT_BG = (1.0, 1.0, 1.0)
_REPORT_CARD = (0.97, 0.98, 0.99)
_REPORT_BORDER = (0.78, 0.83, 0.88)
_REPORT_TEXT = (0.08, 0.18, 0.30)
_REPORT_MUTED = (0.31, 0.38, 0.46)
_REPORT_ACCENTS = [(0.02, 0.55, 0.85), (0.02, 0.72, 0.78), (0.10, 0.57, 0.48), (0.50, 0.35, 0.80), (0.90, 0.48, 0.20), (0.82, 0.66, 0.18)]


def _draw_reports_dashboard_pdf(document, *, stats, course, year, statuses, top, low_stock, expiring):
    document.graphic_page(_REPORT_BG)
    document.rectangle(18, 516, 806, 61, _REPORT_CARD, _REPORT_BORDER)
    document.text(30, 559, "EXECUTIVE ANALYTICS", 7, True, (0.18, 0.72, 0.96))
    document.text(30, 538, "Reports & Analytics", 18, True, _REPORT_TEXT)
    document.text(30, 524, "Comprehensive summary of medical requests, inventory distribution, and student records.", 8, color=_REPORT_MUTED)
    document.text(716, 524, f"Generated {today_label()}", 7, color=_REPORT_MUTED)

    gap, card_w = 8, 195.5
    for index, (label, value, accent) in enumerate(stats):
        x = 18 + index * (card_w + gap)
        document.rectangle(x, 451, card_w, 53, _REPORT_CARD, _REPORT_BORDER)
        document.rectangle(x, 451, 3, 53, accent)
        document.text(x+13, 481, str(value), 20, True, _REPORT_TEXT)
        document.text(x+13, 464, label, 7, True, _REPORT_MUTED)

    chart_w, chart_h = 399, 169
    chart_xs = [18, 425]
    top_y, bottom_y = 267, 74
    _draw_bar_chart(document, chart_xs[0], top_y, chart_w, chart_h, "Students by Course", course)
    _draw_donut_chart(document, chart_xs[1], top_y, chart_w, chart_h, "Students by Year Level", year)
    _draw_bar_chart(document, chart_xs[0], bottom_y, chart_w, chart_h, "Medical Requests by Status", statuses)
    _draw_bar_chart(document, chart_xs[1], bottom_y, chart_w, chart_h, "Top Dispensed Medicines", top)

    low_rows = [[m.name, f"{m.available_stock} {m.unit}", str(m.low_stock_threshold)] for m in low_stock]
    expiring_rows = [[m.name, f"{m.available_stock} {m.unit}",
                      m.expiration_date.strftime("%b %d, %Y") if m.expiration_date else _next_batch_expiry(m)] for m in expiring]
    page_count = max(1, math.ceil(max(len(low_rows), len(expiring_rows), 1)/15))
    for page_index in range(page_count):
        document.graphic_page(_REPORT_BG)
        document.rectangle(18, 516, 806, 61, _REPORT_CARD, _REPORT_BORDER)
        document.text(30, 552, "Reports & Analytics", 17, True, _REPORT_TEXT)
        document.text(30, 531, "Inventory Alerts", 10, True, (0.18, 0.72, 0.96))
        document.text(716, 531, f"Generated {today_label()}", 7, color=_REPORT_MUTED)
        start, end = page_index*15, (page_index+1)*15
        _draw_inventory_table(document, 18, 76, 399, 419, "Low Stock Medicines", low_rows[start:end],
                              ["Medicine", "Available", "Threshold"], [0.50, 0.26, 0.24], (0.92, 0.28, 0.30))
        _draw_inventory_table(document, 425, 76, 399, 419, "Expiring Soon", expiring_rows[start:end],
                              ["Medicine", "Available", "Expiration"], [0.48, 0.25, 0.27], (0.95, 0.68, 0.18))


def _draw_chart_card(document, x, y, width, height, title):
    document.rectangle(x, y, width, height, _REPORT_CARD, _REPORT_BORDER)
    document.text(x+12, y+height-19, title, 10, True, _REPORT_TEXT)
    document.rectangle(x+12, y+height-28, width-24, 0.7, _REPORT_BORDER)


def _draw_bar_chart(document, x, y, width, height, title, values):
    _draw_chart_card(document, x, y, width, height, title)
    values = list(values)[:8]
    px, py, pw, ph = x+32, y+29, width-48, height-65
    for step in range(4):
        gy = py + ph*step/3
        document.rectangle(px, gy, pw, 0.5, _REPORT_BORDER)
    if not values or max([value for _, value in values] or [0]) <= 0:
        document.text(px+8, py+ph/2, "No data available", 8, color=_REPORT_MUTED)
        return
    maximum = max(value for _, value in values)
    slot = pw / len(values)
    bar_w = min(26, slot*0.48)
    for index, (label, value) in enumerate(values):
        bx = px + index*slot + (slot-bar_w)/2
        bh = max(1.5, ph*value/maximum)
        accent = _REPORT_ACCENTS[index % len(_REPORT_ACCENTS)]
        document.rectangle(bx, py, bar_w, bh, accent)
        document.text(bx, py+bh+5, str(value), 6.5, True, _REPORT_TEXT)
        label = str(label)
        max_chars = max(6, int(slot/4.2))
        if len(label) > max_chars:
            label = label[:max_chars-1] + "…"
        document.text(bx-4, py-12, label, 5.5, color=_REPORT_MUTED)


def _draw_donut_chart(document, x, y, width, height, title, values):
    _draw_chart_card(document, x, y, width, height, title)
    values = [(label, value) for label, value in values if value > 0][:8]
    if not values:
        document.text(x+30, y+height/2, "No data available", 8, color=_REPORT_MUTED)
        return
    cx, cy, radius = x+133, y+80, 48
    total = sum(value for _, value in values)
    angle = 90
    for index, (label, value) in enumerate(values):
        sweep = 360 * value / total
        points = [(cx, cy)]
        segments = max(3, int(sweep/5))
        points.extend((cx+radius*math.cos(math.radians(angle-sweep*i/segments)),
                       cy+radius*math.sin(math.radians(angle-sweep*i/segments))) for i in range(segments+1))
        document.polygon(points, _REPORT_ACCENTS[index % len(_REPORT_ACCENTS)])
        angle -= sweep
    document.circle(cx, cy, 27, _REPORT_CARD)
    document.text(cx-14, cy-2, str(total), 12, True, _REPORT_TEXT)
    legend_x, legend_y = x+220, y+height-58
    for index, (label, value) in enumerate(values):
        yy = legend_y-index*20
        document.rectangle(legend_x, yy-3, 7, 7, _REPORT_ACCENTS[index % len(_REPORT_ACCENTS)])
        document.text(legend_x+13, yy, f"{label}: {value}", 7.5, color=_REPORT_TEXT)


def _draw_inventory_table(document, x, y, width, height, title, rows, headers, widths, accent):
    document.rectangle(x, y, width, height, _REPORT_CARD, _REPORT_BORDER)
    document.rectangle(x, y+height-4, width, 4, accent)
    document.text(x+15, y+height-28, title, 13, True, _REPORT_TEXT)
    document.text(x+width-58, y+height-27, f"{len(rows)} items", 7, color=_REPORT_MUTED)
    headers_y = y+height-58
    document.rectangle(x+12, headers_y-9, width-24, 21, (0.13, 0.19, 0.28))
    positions = [x+17]
    for fraction in widths:
        positions.append(positions[-1]+(width-34)*fraction)
    for index, label in enumerate(headers):
        document.text(positions[index], headers_y, label, 7, True, _REPORT_MUTED)
    if not rows:
        document.circle(x+width/2, y+height/2+2, 9, (0.06, 0.35, 0.29))
        document.text(x+width/2-3, y+height/2-1, "✓", 9, True, (0.22, 0.88, 0.62))
        document.text(x+width/2-65, y+height/2-23, "No items to report", 8, color=_REPORT_MUTED)
        return
    row_y = headers_y-23
    for row_index, row in enumerate(rows[:20]):
        if row_index % 2 == 0:
            document.rectangle(x+12, row_y-7, width-24, 20, (0.105, 0.16, 0.23))
        for column, value in enumerate(row):
            text = str(value)
            max_chars = max(8, int((width-34)*widths[column]/4.5))
            if len(text) > max_chars:
                text = text[:max_chars-1]+"…"
            document.text(positions[column], row_y, text, 7.5, color=_REPORT_TEXT)
        row_y -= 23


def _next_batch_expiry(medicine):
    batch = medicine.batches.filter(quantity_in_stock__gt=0, expiration_date__isnull=False).order_by("expiration_date").first()
    return batch.expiration_date.strftime("%b %d, %Y") if batch else "Not recorded"
