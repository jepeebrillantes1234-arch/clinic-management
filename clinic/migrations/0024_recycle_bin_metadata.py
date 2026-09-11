from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('clinic', '0023_student_recycle_bin_metadata')]
    operations = []
    for model in ('medicine', 'medicinerecord', 'nurse', 'activitylog', 'dispenserecord'):
        operations.append(migrations.AddField(model_name=model, name='deleted_at', field=models.DateTimeField(blank=True, null=True)))
    for model, related_name in (
        ('medicine', 'medicines_moved_to_recycle_bin'),
        ('medicinerecord', 'medicine_records_moved_to_recycle_bin'),
        ('nurse', 'assistants_moved_to_recycle_bin'),
        ('activitylog', 'activity_logs_moved_to_recycle_bin'),
        ('dispenserecord', 'dispense_records_moved_to_recycle_bin'),
    ):
        operations.append(migrations.AddField(model_name=model, name='deleted_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name=related_name, to=settings.AUTH_USER_MODEL)))
