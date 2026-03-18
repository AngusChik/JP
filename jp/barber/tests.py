import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .booking import bootstrap_reference_data
from .models import Barber, Booking, CustomerAccount, Service


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
        self.assertContains(response, "Continue In-House Booking")

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
        self._authenticate_client(self.client)
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
        self._authenticate_client(first_client, phone="+14165550123")
        self._authenticate_client(second_client, phone="+14165550124")

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

        ics_response = self.client.get("/api/admin/bookings/export.ics")
        self.assertEqual(ics_response.status_code, 200)
        self.assertIn("text/calendar", ics_response["Content-Type"])
        self.assertIn("BEGIN:VCALENDAR", ics_response.content.decode("utf-8"))

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
            },
        )
        self.assertEqual(update_response.status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.preferred_style, "Low taper fade")
        self.assertEqual(account.preferred_barber, self.barber)
