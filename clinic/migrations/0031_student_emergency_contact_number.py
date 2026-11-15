import re
from django.core.validators import RegexValidator
from django.db import migrations, models


def split_legacy_emergency_contacts(apps, schema_editor):
    Student = apps.get_model("clinic", "Student")
    for student in Student.objects.all().iterator():
        value = student.emergency_contact or ""
        match = re.search(r"\s*-\s*(\d{11})\s*$", value)
        if match:
            student.emergency_contact = value[:match.start()].strip()
            student.emergency_contact_number = match.group(1)
            student.save(update_fields=["emergency_contact", "emergency_contact_number"])


def restore_legacy_emergency_contacts(apps, schema_editor):
    Student = apps.get_model("clinic", "Student")
    for student in Student.objects.exclude(emergency_contact_number="").iterator():
        student.emergency_contact = f"{student.emergency_contact} - {student.emergency_contact_number}"
        student.save(update_fields=["emergency_contact"])


class Migration(migrations.Migration):
    dependencies = [("clinic", "0030_profile_failed_login_attempts")]

    operations = [
        migrations.AddField(
            model_name="student",
            name="emergency_contact_number",
            field=models.CharField(
                blank=True,
                default="",
                help_text="11-digit mother or emergency contact number",
                max_length=11,
                validators=[RegexValidator(message="Enter exactly 11 digits.", regex="^\\d{11}$")],
            ),
        ),
        migrations.RunPython(split_legacy_emergency_contacts, restore_legacy_emergency_contacts),
    ]
