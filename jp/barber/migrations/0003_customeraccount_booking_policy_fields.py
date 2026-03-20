from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("barber", "0002_booking_amount_paid_cents_booking_checked_out_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customeraccount",
            name="blocked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customeraccount",
            name="booking_policy_note",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name="customeraccount",
            name="is_inhouse_blocked",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="customeraccount",
            name="missed_appointments_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
