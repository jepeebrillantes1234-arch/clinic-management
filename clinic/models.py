from datetime import date, timedelta
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


# ---------------------------
# 1. AUTHENTICATION (role-based)
# ---------------------------
class Profile(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        # Stored value remains 'nurse' to keep existing accounts and permissions working.
        ('nurse', 'Assistant'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    must_change_password = models.BooleanField(default=False)
    temporary_password_expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
    else:
        Profile.objects.get_or_create(user=instance)


# ---------------------------
# 2. STUDENT INFORMATION
# ---------------------------
class Student(models.Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='student_profile'
    )
    student_id = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    full_name = models.CharField(max_length=150)
    age = models.PositiveIntegerField()
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    address = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=20)
    course = models.CharField(max_length=100)
    year_level = models.CharField(max_length=20)
    section = models.CharField(max_length=20, blank=True)
    
    emergency_contact = models.CharField(max_length=100, help_text="Mother or emergency contact name")
    emergency_contact_number = models.CharField(
        max_length=11,
        blank=True,
        default="",
        validators=[RegexValidator(regex=r"^\d{11}$", message="Enter exactly 11 digits.")],
        help_text="11-digit mother or emergency contact number",
    )
    allergies = models.TextField(blank=True, help_text="Known allergies, comma-separated")
    allergies_reviewed = models.BooleanField(default=False)
    date_registered = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='students_moved_to_recycle_bin'
    )

    def __str__(self):
        return f"{self.student_id} - {self.full_name}"


# ---------------------------
# 3. MEDICINE INVENTORY
# ---------------------------
class Medicine(models.Model):
    name = models.CharField(max_length=150, unique=True)
    generic_name = models.CharField(max_length=150, blank=True)
    brand_name = models.CharField(max_length=150, blank=True)
    medicine_form = models.CharField(max_length=60, blank=True, help_text="Tablet, capsule, syrup, etc.")
    strength = models.CharField(max_length=60, blank=True, help_text="For example, 500 mg or 200 mg")
    category = models.CharField(max_length=100, blank=True, help_text="hal. Pain Reliever, Antibiotic")
    indications = models.CharField(max_length=500, blank=True, help_text="Clinic-approved condition keywords, comma-separated; suggestions only")
    contraindications = models.TextField(blank=True, help_text="Known allergy or other contraindication keywords, comma-separated")
    allergy_warnings = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    minimum_suggested_age = models.PositiveSmallIntegerField(null=True, blank=True)
    maximum_suggested_age = models.PositiveSmallIntegerField(null=True, blank=True)
    approved_dosage_instructions = models.TextField(blank=True, help_text="Optional clinic-approved dosage instructions; assistant must review")
    suggestion_safety_reviewed = models.BooleanField(default=False, help_text="Enable symptom suggestions only after clinic safety review")
    quantity_in_stock = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=30, default='pcs', help_text="hal. pcs, bottles, boxes")
    expiration_date = models.DateField(null=True, blank=True)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    image = models.ImageField(upload_to='medicines/', blank=True, null=True, help_text="Upload an image of the medicine")
    date_added = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='medicines_moved_to_recycle_bin')

    def clean(self):
        super().clean()
        if (
            self.minimum_suggested_age is not None
            and self.maximum_suggested_age is not None
            and self.minimum_suggested_age > self.maximum_suggested_age
        ):
            raise ValidationError({
                "maximum_suggested_age": "Maximum suggested age must be greater than or equal to minimum suggested age."
            })

    def __str__(self):
        return f"{self.name} ({self.quantity_in_stock} {self.unit})"

    @property
    def is_low_stock(self):
        available = self.available_stock
        return 0 < available <= self.low_stock_threshold

    @property
    def available_stock(self):
        if not self.pk:
            return self.quantity_in_stock
        today = timezone.localdate()
        batch_stock = self.batches.filter(quantity_in_stock__gt=0).filter(
            Q(expiration_date__isnull=True) | Q(expiration_date__gte=today)
        ).aggregate(total=Sum("quantity_in_stock"))["total"]
        if batch_stock is not None:
            return batch_stock
        if self.batches.exists():
            return 0
        if self.expiration_date and self.expiration_date < today:
            return 0
        return self.quantity_in_stock

    @property
    def expired_stock(self):
        if not self.pk:
            return 0
        batch_stock = self.batches.filter(
            quantity_in_stock__gt=0,
            expiration_date__lt=timezone.localdate(),
        ).aggregate(total=Sum("quantity_in_stock"))["total"]
        if batch_stock is not None:
            return batch_stock
        return self.quantity_in_stock if self.expiration_date and self.expiration_date < timezone.localdate() else 0

    @property
    def is_out_of_stock(self):
        return self.quantity_in_stock == 0

    @property
    def is_expired(self):
        return self.quantity_in_stock > 0 and self.available_stock == 0 and self.expired_stock > 0

    @property
    def is_expiring_soon(self):
        if not self.pk:
            return bool(self.expiration_date and self.expiration_date >= timezone.localdate() and self.expiration_date <= timezone.localdate() + timedelta(days=30))
        today = timezone.localdate()
        if self.batches.exists():
            return self.batches.filter(
            quantity_in_stock__gt=0,
            expiration_date__gte=today,
            expiration_date__lte=today + timedelta(days=30),
            ).exists()
        return bool(self.expiration_date and today <= self.expiration_date <= today + timedelta(days=30))


class MedicineBatch(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="batches")
    batch_number = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=150, blank=True)
    date_received = models.DateField(null=True, blank=True)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=30, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.medicine.name} — {self.batch_number or 'Batch details not recorded'}"


@receiver(post_save, sender=Medicine)
def create_unrecorded_batch_for_direct_medicine_stock(sender, instance, created, **kwargs):
    """Keep direct Medicine creation compatible without fabricating batch metadata."""
    if created and instance.quantity_in_stock > 0 and not instance.batches.exists():
        MedicineBatch.objects.create(
            medicine=instance,
            quantity_in_stock=instance.quantity_in_stock,
            unit=instance.unit,
            expiration_date=instance.expiration_date,
        )


# ---------------------------
# 4. MEDICINE RECORDS (History ng Pamimigay ng Gamot)
# ---------------------------
class MedicineRecord(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='medicine_records')
    medicine = models.ForeignKey(Medicine, on_delete=models.SET_NULL, null=True, blank=True)
    batches = models.ManyToManyField(MedicineBatch, through="MedicineRecordBatch", related_name="dispensing_records", blank=True)
    medicine_name = models.CharField(max_length=150, blank=True)
    dosage = models.TextField(blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    expiration_date = models.DateField(null=True, blank=True)
    prescription = models.TextField(blank=True, null=True)
    dispensed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_released = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='medicine_records_moved_to_recycle_bin')

    def __str__(self):
        med_name = self.medicine.name if self.medicine else (self.medicine_name or "Unknown Medicine")
        return f"{med_name} - {self.student.full_name}"


class MedicineRecordBatch(models.Model):
    medicine_record = models.ForeignKey(MedicineRecord, on_delete=models.CASCADE, related_name="batch_allocations")
    batch = models.ForeignKey(MedicineBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="record_allocations")
    quantity = models.PositiveIntegerField()


class StudentMedicalRequest(models.Model):
    """Student medical request outcome, separate from medicine dispensing history."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="medical_requests")
    reason = models.TextField(blank=True)
    medicine = models.ForeignKey(Medicine, on_delete=models.SET_NULL, null=True, blank=True)
    medicine_name = models.CharField(max_length=150, default="No Medicine Needed")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.full_name} - {self.medicine_name}"


# ---------------------------
# 5. NURSE MANAGEMENT
# ---------------------------
class Nurse(models.Model):
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='nurse_profile')
    full_name = models.CharField(max_length=150)
    age = models.PositiveIntegerField(null=True, blank=True)
    photo = models.ImageField(upload_to='nurse_photos/', blank=True, null=True)
    position = models.CharField(max_length=100, blank=True, help_text="hal. School Nurse, Clinic Head")
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    schedule = models.CharField(max_length=150, blank=True, help_text="hal. Mon-Fri, 8AM-5PM (Time of Duty)")
    date_added = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assistants_moved_to_recycle_bin')

    def __str__(self):
        return self.full_name


# ---------------------------
# 6. AUTH & LOGS
# ---------------------------
class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_valid(self):
        return not self.is_used and (timezone.now() - self.created_at) < timedelta(minutes=15)

    def __str__(self):
        return f"{self.user.username} - {self.code}"


class LoginActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_activities')
    role = models.CharField(max_length=20, blank=True)
    module = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, default='success')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {self.timestamp:%Y-%m-%d %H:%M}"


class ActivityLog(models.Model):
    ICON_CHOICES = [
        ('student', 'Student'),
        ('medicine', 'Medicine'),
        # Stored value remains 'nurse' to keep existing accounts and permissions working.
        ('nurse', 'Assistant'),
        ('details', 'Description'),
        ('dispense', 'Dispense'),
        ('other', 'Other'),

    ]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.CharField(max_length=20, choices=ICON_CHOICES, default='other')
    action = models.CharField(max_length=200, help_text="hal. 'New student registered'")
    details = models.CharField(max_length=255, blank=True, help_text="hal. 'Juan Dela Cruz added'")
    
    # --- IDAGDAG MO ANG LINYANG ITO ---
    description = models.TextField(blank=True, null=True, help_text="Kumpletong detalye ng aktibidad")
    # ---------------------------------
    
    role = models.CharField(max_length=20, blank=True)
    module = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, default='success')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs_moved_to_recycle_bin')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} - {self.timestamp:%Y-%m-%d %H:%M}"
    
class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clinic_notifications')
    triggered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='triggered_clinic_notifications'
    )
    title = models.CharField(max_length=150, default='Notification')
    message = models.TextField()
    notification_type = models.CharField(max_length=30, default='system')
    module = models.CharField(max_length=50, blank=True)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} - {self.recipient.username}'


class DispenseRecord(models.Model):
    # Palitan o idagdag ang mga fields ayon sa inyong database structure
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE)
    quantity_dispensed = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dispense_records_moved_to_recycle_bin')
    
    def __str__(self):
        return f"{self.quantity_dispensed} dispensed"


