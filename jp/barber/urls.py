from django.urls import path

from .views import (
    account_portal,
    account_dashboard,
    api_account_me_endpoint,
    api_admin_bookings_feed,
    api_admin_customer_detail,
    api_admin_customers,
    api_admin_create_booking,
    api_admin_export_bookings_csv,
    api_admin_mark_completed,
    api_admin_mark_missed,
    api_admin_overview,
    api_admin_reports,
    api_admin_staff_profile,
    api_auth_logout,
    api_auth_send_otp,
    api_auth_verify_otp,
    api_staff_login,
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
    path("account/", account_portal, name="account_portal"),
    path("account/dashboard/", account_dashboard, name="account_dashboard"),
    path("ops/", ops_dashboard, name="ops_dashboard"),
    path("api/auth/send-otp", api_auth_send_otp, name="api_auth_send_otp"),
    path("api/auth/verify-otp", api_auth_verify_otp, name="api_auth_verify_otp"),
    path("api/auth/logout", api_auth_logout, name="api_auth_logout"),
    path("api/staff/login", api_staff_login, name="api_staff_login"),
    path("api/account/me", api_account_me_endpoint, name="api_account_me_endpoint"),
    path("api/availability", api_availability, name="api_availability"),
    path("api/bookings", api_bookings, name="api_bookings"),
    path("api/bookings/<int:booking_id>/cancel", api_cancel_booking, name="api_cancel_booking"),
    path("api/admin/overview", api_admin_overview, name="api_admin_overview"),
    path("api/admin/reports", api_admin_reports, name="api_admin_reports"),
    path("api/admin/bookings-feed", api_admin_bookings_feed, name="api_admin_bookings_feed"),
    path("api/admin/customers", api_admin_customers, name="api_admin_customers"),
    path("api/admin/customers/<int:customer_id>", api_admin_customer_detail, name="api_admin_customer_detail"),
    path("api/admin/staff/profile", api_admin_staff_profile, name="api_admin_staff_profile"),
    path("api/admin/bookings", api_admin_create_booking, name="api_admin_create_booking"),
    path("api/admin/bookings/<int:booking_id>/complete", api_admin_mark_completed, name="api_admin_complete"),
    path("api/admin/bookings/<int:booking_id>/mark-missed", api_admin_mark_missed, name="api_admin_missed"),
    path("api/admin/bookings/export.csv", api_admin_export_bookings_csv, name="api_admin_export_bookings_csv"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
