from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Barber(models.Model):
    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    title = models.CharField(max_length=120, blank=True)
    booksy_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Service(models.Model):
    name = models.CharField(max_length=120, unique=True)
    duration_minutes = models.PositiveIntegerField(default=30)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["duration_minutes", "name"]

    def __str__(self) -> str:
        return self.name


class AvailabilityRule(models.Model):
    barber = models.ForeignKey(Barber, on_delete=models.CASCADE, related_name="availability_rules")
    # Monday=0 through Sunday=6
    day_of_week = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["barber", "day_of_week", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="availability_day_of_week_0_6",
            ),
        ]

    def clean(self) -> None:
        if self.end_time <= self.start_time:
            raise ValidationError("end_time must be after start_time")

    def __str__(self) -> str:
        return f"{self.barber.name} ({self.day_of_week}) {self.start_time}-{self.end_time}"


class CustomerAccount(models.Model):
    phone_e164 = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    preferred_barber = models.ForeignKey(
        Barber,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preferred_clients",
    )
    preferred_style = models.CharField(max_length=120, blank=True)
    profile_notes = models.TextField(blank=True)
    is_inhouse_blocked = models.BooleanField(default=False)
    booking_policy_note = models.CharField(max_length=240, blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    missed_appointments_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.full_name or self.phone_e164


class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    phone = models.CharField(max_length=20, blank=True)
    title = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    linked_barber = models.ForeignKey(
        Barber,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return self.title or self.user.get_username()


class OTPChallenge(models.Model):
    phone_e164 = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=40, default="login")
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return (
            self.consumed_at is None
            and self.attempts < self.max_attempts
            and self.expires_at > timezone.now()
        )

    def mark_consumed(self) -> None:
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at"])

    @classmethod
    def create_expiry(cls, minutes: int = 10) -> datetime:
        return timezone.now() + timedelta(minutes=minutes)


class Booking(models.Model):
    STATUS_CONFIRMED = "confirmed"
    STATUS_COMPLETED = "completed"
    STATUS_MISSED = "missed"
    STATUS_CANCELLED = "cancelled"
    STATUS_RESCHEDULED = "rescheduled"
    PAYMENT_UNPAID = "unpaid"
    PAYMENT_PARTIAL = "partial"
    PAYMENT_PAID = "paid"
    ORIGIN_LOCAL = "local"
    ORIGIN_BOOKSY = "booksy"
    ORIGIN_SYNCED = "synced"
    SYNC_LOCAL_ONLY = "local_only"
    SYNC_PENDING = "pending"
    SYNC_SYNCED = "synced"
    SYNC_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_MISSED, "Missed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_RESCHEDULED, "Rescheduled"),
    ]
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_UNPAID, "Unpaid"),
        (PAYMENT_PARTIAL, "Partial"),
        (PAYMENT_PAID, "Paid"),
    ]
    ORIGIN_CHOICES = [
        (ORIGIN_LOCAL, "Local"),
        (ORIGIN_BOOKSY, "Booksy"),
        (ORIGIN_SYNCED, "Synced"),
    ]
    SYNC_STATUS_CHOICES = [
        (SYNC_LOCAL_ONLY, "Local Only"),
        (SYNC_PENDING, "Pending"),
        (SYNC_SYNCED, "Synced"),
        (SYNC_FAILED, "Failed"),
    ]

    customer = models.ForeignKey(
        CustomerAccount,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="bookings")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="bookings")
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONFIRMED)
    price_cents = models.PositiveIntegerField(default=0)
    amount_paid_cents = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_UNPAID,
    )
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default=ORIGIN_LOCAL)
    external_booking_id = models.CharField(max_length=120, blank=True, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_status = models.CharField(
        max_length=20,
        choices=SYNC_STATUS_CHOICES,
        default=SYNC_LOCAL_ONLY,
    )
    notes = models.TextField(blank=True)
    cancellation_reason = models.CharField(max_length=240, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=models.F("start_time")),
                name="booking_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["barber", "start_time"],
                condition=Q(status__in=["confirmed", "rescheduled"]),
                name="unique_active_slot_per_barber",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer} - {self.start_time} ({self.status})"


class BookingAudit(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="audits")
    actor_type = models.CharField(max_length=20)
    actor_identifier = models.CharField(max_length=120, blank=True)
    event = models.CharField(max_length=80)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.booking_id} {self.event}"
