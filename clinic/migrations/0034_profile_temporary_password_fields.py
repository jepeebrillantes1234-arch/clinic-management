from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clinic", "0033_medicine_indications"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="profile",
            name="temporary_password_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
