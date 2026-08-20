from datetime import date, timedelta
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


# ---------------------------
# 1. AUTHENTICATION (role-based)
# ---------------------------
class Profile(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('nurse', 'Nurse'),
        ('student', 'Student'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)

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
    
    emergency_contact = models.CharField(max_length=100, help_text="Name and number")
    date_registered = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_id} - {self.full_name}"


# ---------------------------
# 3. MEDICINE INVENTORY
# ---------------------------
class Medicine(models.Model):
    name = models.CharField(max_length=150, unique=True)
    category = models.CharField(max_length=100, blank=True, help_text="hal. Pain Reliever, Antibiotic")
    quantity_in_stock = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=30, default='pcs', help_text="hal. pcs, bottles, boxes")
    expiration_date = models.DateField(null=True, blank=True)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    image = models.ImageField(upload_to='medicines/', blank=True, null=True, help_text="Upload an image of the medicine")
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.quantity_in_stock} {self.unit})"

    @property
    def is_low_stock(self):
        return self.quantity_in_stock <= self.low_stock_threshold

    @property
    def is_expiring_soon(self):
        if not self.expiration_date:
            return False
        return self.expiration_date <= date.today() + timedelta(days=30)


# ---------------------------
# 4. MEDICINE RECORDS (History ng Pamimigay ng Gamot)
# ---------------------------
class MedicineRecord(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='medicine_records')
    medicine = models.ForeignKey(Medicine, on_delete=models.SET_NULL, null=True, blank=True)
    medicine_name = models.CharField(max_length=150, blank=True)
    dosage = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    expiration_date = models.DateField(null=True, blank=True)
    prescription = models.TextField(blank=True, null=True)
    dispensed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_released = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        med_name = self.medicine.name if self.medicine else (self.medicine_name or "Unknown Medicine")
        return f"{med_name} - {self.student.full_name}"


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
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {self.timestamp:%Y-%m-%d %H:%M}"


class ActivityLog(models.Model):
    ICON_CHOICES = [
        ('student', 'Student'),
        ('medicine', 'Medicine'),
        ('nurse', 'Nurse'),
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
    
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} - {self.timestamp:%Y-%m-%d %H:%M}"
    
class DispenseRecord(models.Model):
    # Palitan o idagdag ang mga fields ayon sa inyong database structure
    medicine = models.ForeignKey('Medicine', on_delete=models.CASCADE)
    quantity_dispensed = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.quantity_dispensed} dispensed"