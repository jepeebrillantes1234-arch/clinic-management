from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('clinic', '0028_rename_object_id_notification_related_object_id_and_more')]

    operations = [
        migrations.AddField(
            model_name='notification', name='triggered_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='triggered_clinic_notifications', to=settings.AUTH_USER_MODEL),
        ),
    ]
