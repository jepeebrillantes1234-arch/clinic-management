from django.contrib import admin
from .models import (
    Profile,
    Student,
    Medicine,
    MedicineRecord,
    MedicineBatch,
    MedicineRecordBatch,
    StudentMedicalRequest,
    Nurse,
    PasswordResetCode,
    LoginActivity,
    ActivityLog,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role')
    list_filter = ('role',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        'student_id',
        'full_name',
        'course',
        'year_level',
        'section',
        'contact_number',
    )
    search_fields = ('student_id', 'full_name')
    list_filter = ('course', 'year_level')


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'minimum_suggested_age',
        'maximum_suggested_age',
        'approved_dosage_instructions',
        'quantity_in_stock',
        'unit',
        'expiration_date',
    )
    search_fields = ('name', 'generic_name', 'brand_name', 'category')


@admin.register(MedicineBatch)
class MedicineBatchAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'batch_number', 'supplier', 'date_received', 'quantity_in_stock', 'unit', 'expiration_date')
    search_fields = ('medicine__name', 'batch_number', 'supplier')
    list_filter = ('expiration_date',)


@admin.register(MedicineRecordBatch)
class MedicineRecordBatchAdmin(admin.ModelAdmin):
    list_display = ('medicine_record', 'batch', 'quantity')


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'code', 'created_at', 'is_used')


@admin.register(MedicineRecord)
class MedicineRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'medicine_name', 'quantity', 'date_released', 'dispensed_by')
    search_fields = ('student__full_name', 'medicine_name')


@admin.register(StudentMedicalRequest)
class StudentMedicalRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'medicine_name', 'requested_at', 'requested_by')
    search_fields = ('student__full_name', 'reason', 'medicine_name')


@admin.register(Nurse)
class NurseAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'position', 'contact_number')
    search_fields = ('full_name', 'position')


@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'timestamp', 'ip_address')


from django.contrib import admin
from .models import ActivityLog

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'category', 'action', 'details', 'description', 'timestamp')
    search_fields = ('action', 'details', 'description')
