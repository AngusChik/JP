import csv

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .models import (
    AvailabilityRule,
    Barber,
    Booking,
    BookingAudit,
    CustomerAccount,
    OTPChallenge,
    Service,
)


@admin.register(Barber)
class BarberAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "title", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "duration_minutes", "price_cents", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(AvailabilityRule)
class AvailabilityRuleAdmin(admin.ModelAdmin):
    list_display = ("barber", "day_of_week", "start_time", "end_time", "slot_minutes", "is_active")
    list_filter = ("barber", "day_of_week", "is_active")


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "phone_e164", "preferred_barber", "preferred_style", "created_at")
    list_select_related = ("preferred_barber",)
    search_fields = ("full_name", "phone_e164", "email", "preferred_style", "profile_notes")


@admin.register(OTPChallenge)
class OTPChallengeAdmin(admin.ModelAdmin):
    list_display = ("phone_e164", "purpose", "attempts", "expires_at", "consumed_at", "created_at")
    list_filter = ("purpose",)
    search_fields = ("phone_e164",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "barber",
        "service",
        "start_time",
        "status",
        "payment_status",
        "amount_paid_cents",
        "created_at",
    )
    list_filter = ("status", "barber", "service")
    search_fields = ("customer__phone_e164", "customer__full_name", "barber__name", "service__name")
    actions = ("mark_completed", "mark_missed", "export_csv")

    @admin.action(description="Mark selected bookings as completed")
    def mark_completed(self, request: HttpRequest, queryset):
        count = 0
        for booking in queryset:
            if booking.status not in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED}:
                continue
            booking.status = Booking.STATUS_COMPLETED
            booking.amount_paid_cents = booking.price_cents
            booking.payment_status = Booking.PAYMENT_PAID if booking.price_cents > 0 else Booking.PAYMENT_UNPAID
            booking.checked_out_at = timezone.now()
            booking.save(update_fields=["status", "amount_paid_cents", "payment_status", "checked_out_at", "updated_at"])
            BookingAudit.objects.create(
                booking=booking,
                actor_type="staff",
                actor_identifier=request.user.username,
                event="booking_completed",
                details={"source": "django_admin", "amount_paid_cents": booking.amount_paid_cents},
            )
            count += 1
        self.message_user(request, f"Marked {count} booking(s) as completed.")

    @admin.action(description="Mark selected bookings as missed")
    def mark_missed(self, request: HttpRequest, queryset):
        count = 0
        for booking in queryset:
            if booking.status not in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED}:
                continue
            booking.status = Booking.STATUS_MISSED
            booking.amount_paid_cents = 0
            booking.payment_status = Booking.PAYMENT_UNPAID
            booking.checked_out_at = None
            booking.save(update_fields=["status", "amount_paid_cents", "payment_status", "checked_out_at", "updated_at"])
            BookingAudit.objects.create(
                booking=booking,
                actor_type="staff",
                actor_identifier=request.user.username,
                event="booking_marked_missed",
                details={"source": "django_admin"},
            )
            count += 1
        self.message_user(request, f"Marked {count} booking(s) as missed.")

    @admin.action(description="Export selected bookings as CSV")
    def export_csv(self, request: HttpRequest, queryset):
        response = HttpResponse(content_type="text/csv")
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        response["Content-Disposition"] = f'attachment; filename="bookings_{timestamp}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "booking_id",
                "status",
                "customer_name",
                "customer_phone",
                "barber",
                "service",
                "start_time",
                "end_time",
                "created_at",
            ]
        )
        for booking in queryset.select_related("customer", "barber", "service"):
            writer.writerow(
                [
                    booking.id,
                    booking.status,
                    booking.customer.full_name,
                    booking.customer.phone_e164,
                    booking.barber.name,
                    booking.service.name,
                    booking.start_time.isoformat(),
                    booking.end_time.isoformat(),
                    booking.created_at.isoformat(),
                ]
            )
        return response


@admin.register(BookingAudit)
class BookingAuditAdmin(admin.ModelAdmin):
    list_display = ("booking", "actor_type", "actor_identifier", "event", "created_at")
    list_filter = ("actor_type", "event")
