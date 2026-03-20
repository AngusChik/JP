import json
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .booking import bootstrap_reference_data
from .models import Barber, Booking, CustomerAccount, Service, StaffProfile

@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class BookingSystemTests(TestCase):
    def setUp(self):
        bootstrap_reference_data()
        self.barber = Barber.objects.filter(is_active=True).first()
        self.service = Service.objects.filter(is_active=True).first()
        self.assertIsNotNone(self.barber)
        self.assertIsNotNone(self.service)

    def _json_post(self, path, payload, client=None):
        target = client or self.client
        return target.post(path, data=json.dumps(payload), content_type="application/json")

    def _json_patch(self, path, payload, client=None):
        target = client or self.client
        return target.patch(path, data=json.dumps(payload), content_type="application/json")

    def _authenticate_client(self, client, phone="+14165550123"):
        account, _ = CustomerAccount.objects.get_or_create(phone_e164=phone)
        session = client.session
        session["customer_account_id"] = account.id
        session.save()
        return account

    def _next_available_slot(self):
        next_week_start = (timezone.localdate() + timedelta(days=7)) - timedelta(
            days=(timezone.localdate() + timedelta(days=7)).weekday()
        )
        response = self.client.get(
            "/api/availability",
            {
                "barber_id": self.barber.id,
                "service_id": self.service.id,
                "week_start": next_week_start.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for day in payload["days"]:
            for slot in day["slots"]:
                if slot["available"]:
                    return slot["start"]
        self.fail("Expected at least one available slot in next week.")

    def test_homepage_contains_booking_choice_ui(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose Your Booking Path")
        self.assertContains(response, "Open My Account")
        self.assertContains(response, "Log In")
        self.assertContains(response, "21963_jp-barber-studio")
        self.assertContains(response, "26938_milo-cuts")

    def test_account_portal_renders(self):
        response = self.client.get("/account/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose your entrance")
        self.assertContains(response, "Staff / Admin")
        self.assertContains(response, "Create My Account")

    def test_account_dashboard_renders(self):
        response = self.client.get("/account/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer Dashboard")
        self.assertContains(response, "Profile Details")

    @override_settings(DEBUG=True)
    def test_send_and_verify_otp_creates_account(self):
        send_response = self._json_post("/api/auth/send-otp", {"phone": "416-555-0123"})
        self.assertEqual(send_response.status_code, 201)
        payload = send_response.json()
        self.assertIn("debug_code", payload)

        verify_response = self._json_post(
            "/api/auth/verify-otp",
            {"phone": "416-555-0123", "code": payload["debug_code"]},
        )
        self.assertEqual(verify_response.status_code, 200)
        account_payload = verify_response.json()["account"]
        self.assertEqual(account_payload["phone"], "+14165550123")
        self.assertTrue(CustomerAccount.objects.filter(phone_e164="+14165550123").exists())

        me_response = self.client.get("/api/account/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["account"]["phone"], "+14165550123")

    def test_account_patch_updates_profile(self):
        self._authenticate_client(self.client)
        response = self._json_patch(
            "/api/account/me",
            {"full_name": "Jordan Prince", "email": "jordan@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["account"]["full_name"], "Jordan Prince")
        self.assertEqual(payload["account"]["email"], "jordan@example.com")

    def test_booking_creation_sets_price_snapshot(self):
        slot_start = self._next_available_slot()
        account = self._authenticate_client(self.client)
        account.full_name = "Jordan Prince"
        account.save(update_fields=["full_name"])
        response = self._json_post(
            "/api/bookings",
            {
                "barber_id": self.barber.id,
                "service_id": self.service.id,
                "start_time": slot_start,
            },
        )
        self.assertEqual(response.status_code, 201)
        booking = Booking.objects.get(id=response.json()["booking"]["id"])
        self.assertEqual(booking.price_cents, self.service.price_cents or 0)

    def test_booking_conflict_prevented_for_same_slot(self):
        slot_start = self._next_available_slot()

        first_client = self.client
        second_client = self.client_class()
        first_account = self._authenticate_client(first_client, phone="+14165550123")
        second_account = self._authenticate_client(second_client, phone="+14165550124")
        first_account.full_name = "First Client"
        first_account.save(update_fields=["full_name"])
        second_account.full_name = "Second Client"
        second_account.save(update_fields=["full_name"])

        first_response = self._json_post(
            "/api/bookings",
            {
                "barber_id": self.barber.id,
                "service_id": self.service.id,
                "start_time": slot_start,
            },
            client=first_client,
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self._json_post(
            "/api/bookings",
            {
                "barber_id": self.barber.id,
                "service_id": self.service.id,
                "start_time": slot_start,
            },
            client=second_client,
        )
        self.assertEqual(second_response.status_code, 409)

    def test_booking_scopes_include_history_and_cancelled(self):
        account = self._authenticate_client(self.client)
        account.full_name = "Jordan Prince"
        account.save(update_fields=["full_name"])
        now = timezone.now()
        upcoming = Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, minutes=self.service.duration_minutes),
            status=Booking.STATUS_CONFIRMED,
        )
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=now - timedelta(days=7),
            end_time=now - timedelta(days=7) + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_COMPLETED,
        )
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=2) + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_MISSED,
        )

        upcoming_response = self.client.get("/api/bookings", {"scope": "upcoming"})
        self.assertEqual(upcoming_response.status_code, 200)
        upcoming_ids = [item["id"] for item in upcoming_response.json()["bookings"]]
        self.assertIn(upcoming.id, upcoming_ids)

        cancel_response = self._json_post(
            f"/api/bookings/{upcoming.id}/cancel",
            {"reason": "Schedule conflict"},
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["booking"]["status"], Booking.STATUS_CANCELLED)

        history_response = self.client.get("/api/bookings", {"scope": "history"})
        self.assertEqual(history_response.status_code, 200)
        history_statuses = {item["status"] for item in history_response.json()["bookings"]}
        self.assertIn(Booking.STATUS_COMPLETED, history_statuses)
        self.assertIn(Booking.STATUS_MISSED, history_statuses)
        self.assertIn(Booking.STATUS_CANCELLED, history_statuses)

    def test_staff_endpoints_require_staff_and_update_status(self):
        account = CustomerAccount.objects.create(phone_e164="+14165550199", full_name="Client")
        now = timezone.now() + timedelta(days=1)
        booking = Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=now,
            end_time=now + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_CONFIRMED,
            price_cents=self.service.price_cents or 0,
        )

        unauth_response = self._json_post(f"/api/admin/bookings/{booking.id}/complete", {})
        self.assertEqual(unauth_response.status_code, 403)

        User = get_user_model()
        staff_user = User.objects.create_user(username="staff", password="secret123", is_staff=True)
        self.client.force_login(staff_user)

        complete_response = self._json_post(
            f"/api/admin/bookings/{booking.id}/complete",
            {"amount_paid_cents": 4200},
        )
        self.assertEqual(complete_response.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_COMPLETED)
        self.assertEqual(booking.amount_paid_cents, 4200)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_PAID)

        booking.status = Booking.STATUS_CONFIRMED
        booking.save(update_fields=["status"])
        missed_response = self._json_post(f"/api/admin/bookings/{booking.id}/mark-missed", {})
        self.assertEqual(missed_response.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_MISSED)
        account.refresh_from_db()
        self.assertEqual(account.missed_appointments_count, 1)

    def test_staff_can_sign_in_from_account_page(self):
        User = get_user_model()
        staff_user = User.objects.create_user(username="frontdesk", password="secret123", is_staff=True)

        login_response = self._json_post(
            "/api/staff/login",
            {"username": "frontdesk", "password": "secret123", "next": "/ops/"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["redirect_url"], "/ops/")
        self.assertEqual(login_response.json()["user"]["username"], staff_user.username)

        ops_response = self.client.get("/ops/")
        self.assertEqual(ops_response.status_code, 200)

    def test_ops_redirects_to_staff_mode_on_account_page(self):
        response = self.client.get("/ops/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/?next=%2Fops%2F&mode=staff", response["Location"])

    def test_staff_customer_record_and_overview_endpoints(self):
        account = CustomerAccount.objects.create(
            phone_e164="+14165550177",
            full_name="Avery Client",
        )
        now = timezone.now() - timedelta(days=3)
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=now,
            end_time=now + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_COMPLETED,
            price_cents=self.service.price_cents or 0,
            amount_paid_cents=3900,
            payment_status=Booking.PAYMENT_PAID,
            checked_out_at=timezone.now(),
        )

        User = get_user_model()
        staff_user = User.objects.create_user(username="ops", password="secret123", is_staff=True)
        self.client.force_login(staff_user)

        ops_response = self.client.get("/ops/")
        self.assertEqual(ops_response.status_code, 200)
        self.assertContains(ops_response, "Calendar")

        overview_response = self.client.get("/api/admin/overview")
        self.assertEqual(overview_response.status_code, 200)
        self.assertIn("summary", overview_response.json())

        customers_response = self.client.get("/api/admin/customers", {"search": "Avery"})
        self.assertEqual(customers_response.status_code, 200)
        customers = customers_response.json()["customers"]
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers[0]["full_name"], "Avery Client")

        update_response = self._json_patch(
            f"/api/admin/customers/{account.id}",
            {
                "preferred_barber_id": self.barber.id,
                "preferred_style": "Low taper fade",
                "profile_notes": "Likes a sharp line-up and low chatter.",
                "booking_policy_note": "Two missed appointments. Call before booking again.",
                "is_inhouse_blocked": True,
            },
        )
        self.assertEqual(update_response.status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.preferred_style, "Low taper fade")
        self.assertEqual(account.preferred_barber, self.barber)
        self.assertTrue(account.is_inhouse_blocked)
        self.assertEqual(account.booking_policy_note, "Two missed appointments. Call before booking again.")

        reports_response = self.client.get("/api/admin/reports")
        self.assertEqual(reports_response.status_code, 200)
        self.assertIn("cards", reports_response.json())

        bookings_feed_response = self.client.get("/api/admin/bookings-feed", {"origin": "local"})
        self.assertEqual(bookings_feed_response.status_code, 200)
        self.assertIn("bookings", bookings_feed_response.json())

    def test_staff_bookings_feed_exposes_origin_and_sync_fields(self):
        account = CustomerAccount.objects.create(
            phone_e164="+14165550221",
            full_name="Feed Client",
        )
        User = get_user_model()
        staff_user = User.objects.create_user(username="scheduler", password="secret123", is_staff=True)
        self.client.force_login(staff_user)
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=timezone.now() + timedelta(days=2),
            end_time=timezone.now() + timedelta(days=2, minutes=self.service.duration_minutes),
            status=Booking.STATUS_CONFIRMED,
            origin=Booking.ORIGIN_BOOKSY,
            sync_status=Booking.SYNC_SYNCED,
            external_booking_id="bk_123",
        )
        response = self.client.get("/api/admin/bookings-feed", {"search": "bk_123"})
        self.assertEqual(response.status_code, 200)
        booking = response.json()["bookings"][0]
        self.assertEqual(booking["origin"], Booking.ORIGIN_BOOKSY)
        self.assertEqual(booking["sync_status"], Booking.SYNC_SYNCED)
        self.assertEqual(booking["external_booking_id"], "bk_123")

    def test_staff_bookings_feed_supports_calendar_date_range(self):
        account = CustomerAccount.objects.create(
            phone_e164="+14165550231",
            full_name="Calendar Client",
        )
        User = get_user_model()
        staff_user = User.objects.create_user(username="calendarops", password="secret123", is_staff=True)
        self.client.force_login(staff_user)
        start_of_week = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        in_range_start = timezone.make_aware(datetime.combine(start_of_week + timedelta(days=1), time.min)) + timedelta(hours=10)
        out_of_range_start = in_range_start + timedelta(days=10)
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=in_range_start,
            end_time=in_range_start + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_CONFIRMED,
            origin=Booking.ORIGIN_BOOKSY,
            sync_status=Booking.SYNC_SYNCED,
            external_booking_id="range_in",
        )
        Booking.objects.create(
            customer=account,
            barber=self.barber,
            service=self.service,
            start_time=out_of_range_start,
            end_time=out_of_range_start + timedelta(minutes=self.service.duration_minutes),
            status=Booking.STATUS_CONFIRMED,
            origin=Booking.ORIGIN_LOCAL,
            sync_status=Booking.SYNC_LOCAL_ONLY,
            external_booking_id="range_out",
        )
        response = self.client.get(
            "/api/admin/bookings-feed",
            {
                "start": start_of_week.isoformat(),
                "end": (start_of_week + timedelta(days=6)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        ids = {booking["external_booking_id"] for booking in response.json()["bookings"]}
        self.assertIn("range_in", ids)
        self.assertNotIn("range_out", ids)

    def test_staff_profile_endpoint_updates_profile(self):
        User = get_user_model()
        staff_user = User.objects.create_user(username="profileops", password="secret123", is_staff=True)
        self.client.force_login(staff_user)

        get_response = self.client.get("/api/admin/staff/profile")
        self.assertEqual(get_response.status_code, 200)
        self.assertIn("profile", get_response.json())

        update_response = self._json_patch(
            "/api/admin/staff/profile",
            {
                "first_name": "Jordan",
                "last_name": "Prince",
                "email": "ops@example.com",
                "phone": "+14165550000",
                "title": "Ops Lead",
                "linked_barber_id": self.barber.id,
                "bio": "Handles internal workflows.",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        staff_user.refresh_from_db()
        profile = StaffProfile.objects.get(user=staff_user)
        self.assertEqual(staff_user.first_name, "Jordan")
        self.assertEqual(profile.title, "Ops Lead")
        self.assertEqual(profile.linked_barber, self.barber)

    def test_flagged_customer_cannot_create_inhouse_booking(self):
        slot_start = self._next_available_slot()
        account = self._authenticate_client(self.client)
        account.full_name = "Blocked Client"
        account.is_inhouse_blocked = True
        account.booking_policy_note = "Please call the shop before booking again."
        account.save(update_fields=["full_name", "is_inhouse_blocked", "booking_policy_note"])

        response = self._json_post(
            "/api/bookings",
            {
                "barber_id": self.barber.id,
                "service_id": self.service.id,
                "start_time": slot_start,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Please call the shop before booking again.")
