from django.urls import path

from .views import (
    api_account_me_endpoint,
    api_admin_customer_detail,
    api_admin_customers,
    api_admin_export_bookings_csv,
    api_admin_export_bookings_ics,
    api_admin_mark_completed,
    api_admin_mark_missed,
    api_admin_overview,
    api_auth_send_otp,
    api_auth_verify_otp,
    api_availability,
    api_bookings,
    api_cancel_booking,
    home,
    ops_dashboard,
)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", home, name="home"),
    path("ops/", ops_dashboard, name="ops_dashboard"),
    path("api/auth/send-otp", api_auth_send_otp, name="api_auth_send_otp"),
    path("api/auth/verify-otp", api_auth_verify_otp, name="api_auth_verify_otp"),
    path("api/account/me", api_account_me_endpoint, name="api_account_me_endpoint"),
    path("api/availability", api_availability, name="api_availability"),
    path("api/bookings", api_bookings, name="api_bookings"),
    path("api/bookings/<int:booking_id>/cancel", api_cancel_booking, name="api_cancel_booking"),
    path("api/admin/overview", api_admin_overview, name="api_admin_overview"),
    path("api/admin/customers", api_admin_customers, name="api_admin_customers"),
    path("api/admin/customers/<int:customer_id>", api_admin_customer_detail, name="api_admin_customer_detail"),
    path("api/admin/bookings/<int:booking_id>/complete", api_admin_mark_completed, name="api_admin_complete"),
    path("api/admin/bookings/<int:booking_id>/mark-missed", api_admin_mark_missed, name="api_admin_missed"),
    path("api/admin/bookings/export.csv", api_admin_export_bookings_csv, name="api_admin_export_bookings_csv"),
    path("api/admin/bookings/export.ics", api_admin_export_bookings_ics, name="api_admin_export_bookings_ics"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
