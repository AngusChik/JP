from __future__ import annotations

import csv
import io
import json
import random
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Count, Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .booking import bootstrap_reference_data, generate_week_slots, normalize_phone, parse_week_start
from .models import (
    AvailabilityRule,
    Barber,
    Booking,
    BookingAudit,
    CustomerAccount,
    OTPChallenge,
    StaffProfile,
    Service,
)


BOOKSY_GLOBAL_URL = getattr(settings, "BOOKSY_GLOBAL_URL", "https://booksy.com/your-link")
BOOKSY_WIDGET_SCRIPT_URL = getattr(settings, "BOOKSY_WIDGET_SCRIPT_URL", "")
GOOGLE_BOOKING_URL = getattr(settings, "GOOGLE_BOOKING_URL", "")
PUBLIC_BARBER_SLUG = "jp"
SESSION_ACCOUNT_KEY = "customer_account_id"
OTP_PURPOSE_LOGIN = "login"
OTP_TTL_MINUTES = 10
OTP_SEND_LIMIT = 5
OTP_SEND_WINDOW_SECONDS = 15 * 60
STAFF_LOGIN_LIMIT = 10
STAFF_LOGIN_WINDOW_SECONDS = 15 * 60


def _public_barbers_queryset():
    return Barber.objects.filter(is_active=True, slug=PUBLIC_BARBER_SLUG)


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _parse_json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_next_path(value: str | None, default: str) -> str:
    candidate = str(value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return default


def _client_ip(request: HttpRequest) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _rate_limit_exceeded(key: str, limit: int, window_seconds: int) -> bool:
    if cache.add(key, 1, timeout=window_seconds):
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        return False
    return count > limit


def _serialize_account(account: CustomerAccount) -> dict:
    return {
        "id": account.id,
        "phone": account.phone_e164,
        "full_name": account.full_name,
        "email": account.email,
        "preferred_barber_id": account.preferred_barber_id,
        "preferred_style": account.preferred_style,
        "profile_notes": account.profile_notes,
        "is_profile_complete": bool(account.full_name.strip()),
        "is_inhouse_blocked": account.is_inhouse_blocked,
        "booking_policy_note": account.booking_policy_note,
        "blocked_at": account.blocked_at.isoformat() if account.blocked_at else None,
        "missed_appointments_count": account.missed_appointments_count,
        "created_at": account.created_at.isoformat(),
    }


def _serialize_booking(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "status": booking.status,
        "start_time": booking.start_time.isoformat(),
        "end_time": booking.end_time.isoformat(),
        "barber": {
            "id": booking.barber.id,
            "slug": booking.barber.slug,
            "name": booking.barber.name,
        },
        "customer": {
            "id": booking.customer_id,
            "full_name": booking.customer.full_name,
            "phone": booking.customer.phone_e164,
            "is_inhouse_blocked": booking.customer.is_inhouse_blocked,
        },
        "service": {
            "id": booking.service.id,
            "name": booking.service.name,
            "duration_minutes": booking.service.duration_minutes,
        },
        "price_cents": booking.price_cents,
        "amount_paid_cents": booking.amount_paid_cents,
        "payment_status": booking.payment_status,
        "origin": booking.origin,
        "external_booking_id": booking.external_booking_id,
        "last_synced_at": booking.last_synced_at.isoformat() if booking.last_synced_at else None,
        "sync_status": booking.sync_status,
        "notes": booking.notes,
        "cancellation_reason": booking.cancellation_reason,
        "can_cancel": booking.status in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED},
        "created_at": booking.created_at.isoformat(),
    }


def _payment_status_for_amount(price_cents: int, amount_paid_cents: int) -> str:
    if amount_paid_cents <= 0:
        return Booking.PAYMENT_UNPAID
    if amount_paid_cents < price_cents:
        return Booking.PAYMENT_PARTIAL
    return Booking.PAYMENT_PAID


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _customer_record_summary(account: CustomerAccount) -> dict:
    bookings = account.bookings.all()
    completed = bookings.filter(status=Booking.STATUS_COMPLETED)
    last_visit = completed.order_by("-start_time").first()
    total_spend = completed.aggregate(total=Sum("amount_paid_cents"))["total"] or 0
    return {
        "id": account.id,
        "phone": account.phone_e164,
        "full_name": account.full_name,
        "email": account.email,
        "preferred_style": account.preferred_style,
        "profile_notes": account.profile_notes,
        "is_inhouse_blocked": account.is_inhouse_blocked,
        "booking_policy_note": account.booking_policy_note,
        "blocked_at": account.blocked_at.isoformat() if account.blocked_at else None,
        "preferred_barber": (
            {
                "id": account.preferred_barber.id,
                "name": account.preferred_barber.name,
                "slug": account.preferred_barber.slug,
            }
            if account.preferred_barber
            else None
        ),
        "stats": {
            "total_bookings": bookings.count(),
            "completed_visits": completed.count(),
            "cancelled_visits": bookings.filter(status=Booking.STATUS_CANCELLED).count(),
            "missed_visits": bookings.filter(status=Booking.STATUS_MISSED).count(),
            "missed_appointments_count": account.missed_appointments_count,
            "upcoming_visits": bookings.filter(
                status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
                start_time__gte=timezone.now(),
            ).count(),
            "total_spend_cents": total_spend,
            "last_visit_at": last_visit.start_time.isoformat() if last_visit else None,
        },
    }


def _serialize_staff_profile(profile: StaffProfile) -> dict:
    user = profile.user
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return {
        "id": profile.id,
        "username": user.username,
        "full_name": full_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone": profile.phone,
        "title": profile.title,
        "bio": profile.bio,
        "linked_barber": (
            {
                "id": profile.linked_barber.id,
                "name": profile.linked_barber.name,
                "slug": profile.linked_barber.slug,
            }
            if profile.linked_barber
            else None
        ),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "joined_at": user.date_joined.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def _month_start(value: datetime) -> datetime:
    localized = timezone.localtime(value)
    return localized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_month(month_start: datetime, offset: int) -> datetime:
    month = month_start.month - 1 + offset
    year = month_start.year + month // 12
    month = month % 12 + 1
    return month_start.replace(year=year, month=month, day=1)


def _get_authenticated_account(request: HttpRequest) -> CustomerAccount | None:
    account_id = request.session.get(SESSION_ACCOUNT_KEY)
    if not account_id:
        return None
    return CustomerAccount.objects.filter(id=account_id).first()


def _require_account(request: HttpRequest) -> CustomerAccount | JsonResponse:
    account = _get_authenticated_account(request)
    if account is None:
        return _json_error("Authentication required.", status=401)
    return account


def _require_staff(request: HttpRequest) -> JsonResponse | None:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return _json_error("Staff authentication required.", status=403)
    return None


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_iso_date_boundary(value: str, end_of_day: bool = False) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    if len(value.strip()) == 10:
        if end_of_day:
            parsed = parsed + timedelta(days=1)
    return parsed


def _build_rule_windows(barber: Barber, week_start) -> dict[str, list[tuple[datetime, datetime]]]:
    windows: dict[str, list[tuple[datetime, datetime]]] = {}
    rules = (
        AvailabilityRule.objects.filter(barber=barber, is_active=True)
        .order_by("day_of_week", "start_time")
    )
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_key = day.isoformat()
        windows[day_key] = []
        for rule in rules:
            if rule.day_of_week != day.weekday():
                continue
            start_dt = timezone.make_aware(
                datetime.combine(day, rule.start_time),
                timezone.get_current_timezone(),
            )
            end_dt = timezone.make_aware(
                datetime.combine(day, rule.end_time),
                timezone.get_current_timezone(),
            )
            windows[day_key].append((start_dt, end_dt))
    return windows


def _slot_fits_any_window(start_time: datetime, end_time: datetime, windows: list[tuple[datetime, datetime]]) -> bool:
    for window_start, window_end in windows:
        if start_time >= window_start and end_time <= window_end:
            return True
    return False


def _send_sms(phone_number: str, message: str) -> bool:
    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_number = getattr(settings, "TWILIO_FROM_NUMBER", "")

    if not account_sid or not auth_token or not from_number:
        print(f"[OTP fallback] {phone_number}: {message}")
        return False

    endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = urlencode(
        {
            "From": from_number,
            "To": phone_number,
            "Body": message,
        }
    ).encode("utf-8")
    request = Request(endpoint, method="POST", data=payload)
    auth_bytes = f"{account_sid}:{auth_token}".encode("utf-8")
    import base64

    request.add_header("Authorization", f"Basic {base64.b64encode(auth_bytes).decode('ascii')}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=10) as response:
            return response.status in {200, 201}
    except Exception:
        return False


def _build_reports_payload() -> dict:
    now = timezone.now()
    current_month = _month_start(now)
    months = [_shift_month(current_month, offset) for offset in range(-5, 1)]
    labels = [month.strftime("%b") for month in months]
    appointments_series = []
    occupancy_series = []
    revenue_series = []
    for month_start in months:
        month_end = _shift_month(month_start, 1)
        month_bookings = Booking.objects.filter(start_time__gte=month_start, start_time__lt=month_end)
        active_count = month_bookings.filter(
            status__in=[
                Booking.STATUS_CONFIRMED,
                Booking.STATUS_RESCHEDULED,
                Booking.STATUS_COMPLETED,
                Booking.STATUS_MISSED,
            ]
        ).count()
        completed = month_bookings.filter(status=Booking.STATUS_COMPLETED)
        completed_count = completed.count()
        booked_minutes = sum(
            booking.service.duration_minutes
            for booking in completed.select_related("service")
        )
        capacity_minutes = (
            AvailabilityRule.objects.filter(is_active=True).count()
            * 60
            * 4
        )
        occupancy = 0
        if capacity_minutes:
            occupancy = round(min(100, (booked_minutes / capacity_minutes) * 100), 1)
        appointments_series.append(active_count)
        occupancy_series.append(occupancy)
        revenue_series.append((completed.aggregate(total=Sum("amount_paid_cents"))["total"] or 0) / 100)

    thirty_days_ago = now - timedelta(days=30)
    recent_bookings = Booking.objects.filter(start_time__gte=thirty_days_ago)
    returning_clients = (
        Booking.objects.filter(status=Booking.STATUS_COMPLETED)
        .values("customer_id")
        .annotate(visits=Count("id"))
        .filter(visits__gt=1)
        .count()
    )
    new_clients = CustomerAccount.objects.filter(created_at__gte=thirty_days_ago).count()
    return {
        "labels": labels,
        "appointments": appointments_series,
        "occupancy": occupancy_series,
        "revenue": revenue_series,
        "cards": {
            "appointments": recent_bookings.count(),
            "time_booked_hours": round(sum(
                booking.service.duration_minutes
                for booking in recent_bookings.select_related("service")
            ) / 60, 1),
            "confirmed": recent_bookings.filter(status=Booking.STATUS_CONFIRMED).count(),
            "finished": recent_bookings.filter(status=Booking.STATUS_COMPLETED).count(),
            "no_shows": recent_bookings.filter(status=Booking.STATUS_MISSED).count(),
            "cancelled": recent_bookings.filter(status=Booking.STATUS_CANCELLED).count(),
            "services_revenue": recent_bookings.filter(status=Booking.STATUS_COMPLETED).aggregate(
                total=Sum("amount_paid_cents")
            )["total"] or 0,
            "clients_total": CustomerAccount.objects.count(),
            "new_clients": new_clients,
            "returning_clients": returning_clients,
        },
    }


def _build_home_data() -> tuple[list[dict], list[dict]]:
    cuts = [
        {
            "name": "Beard Outline",
            "time": "35 min",
            "price": "$25",
            "desc": "Clean fade from skin up with a sharp, blended finish. Our most popular cut.",
            "category": "Fade",
            "image_url": static("Cuts/BO.jpeg"),
            "gallery": "|".join(
                [
                    static("Cuts/BO.jpeg"),
                    static("Cuts/BO2.jpeg"),
                ]
            ),
        },
        {
            "name": "Precision Cut",
            "time": "50 min",
            "price": "$50",
            "desc": "Simple, sharp, and low-maintenance. Even length all around with a crisp lineup.",
            "category": "Classic",
            "image_url": static("Cuts/PC.webp"),
            "gallery": "|".join(
                [
                    static("Cuts/PC.webp"),
                    static("Cuts/PC3.webp"),
                    static("Cuts/PC4.webp"),
                    static("Cuts/PC5.webp"),
                ]
            ),
        },
        {
            "name": "Fade + Beard",
            "time": "1.5 hours",
            "price": "$65",
            "desc": "Full fade with detailed beard shaping, lineup, and hot towel finish.",
            "category": "Combo",
            "image_url": static("Cuts/HCB2.webp"),
            "gallery": "|".join(
                [
                    static("Cuts/HCB2.webp"),
                    static("Cuts/HCB1.webp"),
                ]
            ),
        },
    ]

    barbers = [
        {
            "id": "jp",
            "name": "JP",
            "title": "Owner / Lead Barber",
            "photo_url": static("profile/jppic-main.jpg"),
            "gallery": [
                static("profile/jppic5.jpg"),
                static("profile/jppic-main.jpg"),
                static("profile/jppic4.jpg"),
            ],
            "booksy_url": BOOKSY_GLOBAL_URL,
            "bio": "I started cutting hair in high school just for fun, but in 2019 "
            "I decided to take it seriously and go all in. What started as a "
            "hobby turned into something I really love doing every day.\n\n"
            "Barbering lets me be creative while helping people feel good about "
            "themselves. Whether it's a fresh fade, a clean lineup, or just "
            "tightening things up, I enjoy the whole process and take pride in "
            "getting every detail right.\n\n"
            "I've always liked the idea of being my own boss and building "
            "something of my own. This shop is exactly that \u2014 a space with "
            "good vibes, no pressure, and quality work every time.",
            "reviews": [
                {
                    "author": "Marcus T.",
                    "text": "Best fade I've ever had. JP actually listens to what you want and delivers every single time.",
                },
                {
                    "author": "David L.",
                    "text": "Been coming here for two years now. Never once left disappointed. The man is consistent.",
                },
                {
                    "author": "Ryan K.",
                    "text": "JP fixed a haircut another barber messed up. Didn't even charge extra. That's the kind of guy he is.",
                },
            ],
        },
    ]
    return cuts, barbers


def _build_shop_media() -> list[dict]:
    return [
        {
            "type": "image",
            "src": static("bg/BG7.JPG"),
            "alt": "JP Studio interior view",
        },
        {
            "type": "image",
            "src": static("bg/BG8.JPG"),
            "alt": "JP Studio barber chair area",
        },
        {
            "type": "image",
            "src": static("bg/BG10.JPG"),
            "alt": "JP Studio suite sign",
        },
    ]


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    cuts, barbers = _build_home_data()
    shop_media = _build_shop_media()

    model_barbers = {}
    default_barber = None
    default_service = None
    try:
        bootstrap_reference_data()
        model_barbers = {barber.slug: barber for barber in _public_barbers_queryset()}
        default_barber = _public_barbers_queryset().order_by("name").first()
        default_service = Service.objects.filter(is_active=True).order_by("duration_minutes", "name").first()
    except (OperationalError, ProgrammingError):
        # Supports static build mode where migrations may not have run.
        model_barbers = {}

    for barber in barbers:
        model = model_barbers.get(barber["id"])
        if model and model.booksy_url:
            barber["booksy_url"] = model.booksy_url

        barber["data_json"] = json.dumps(
            {
                "photo": barber["photo_url"],
                "gallery": barber.get("gallery", []),
                "name": barber["name"],
                "title": barber["title"],
                "bio": barber["bio"],
                "booksy_url": barber.get("booksy_url", ""),
                "reviews": barber["reviews"],
            }
        )

    return render(
        request,
        "home.html",
        {
            "cuts": cuts,
            "barbers": barbers,
            "shop_media": shop_media,
            "background_image": "",
            "booksy_global_url": BOOKSY_GLOBAL_URL,
            "booksy_widget_script_url": BOOKSY_WIDGET_SCRIPT_URL,
            "google_booking_url": GOOGLE_BOOKING_URL,
            "account_portal_url": "/account/",
            "booking_defaults_json": json.dumps(
                {
                    "default_barber_id": default_barber.id if default_barber else None,
                    "default_service_id": default_service.id if default_service else None,
                }
            ),
        },
    )


@ensure_csrf_cookie
def account_portal(request: HttpRequest) -> HttpResponse:
    staff_next_url = _safe_next_path(request.GET.get("next"), "/ops/")
    return render(
        request,
        "account.html",
        {
            "home_url": "/",
            "dashboard_url": "/account/dashboard/",
            "staff_dashboard_url": "/ops/",
            "staff_next_url": staff_next_url,
            "initial_mode": "staff" if request.GET.get("mode") == "staff" else "customer",
        },
    )


@ensure_csrf_cookie
def account_dashboard(request: HttpRequest) -> HttpResponse:
    bootstrap_reference_data()
    barbers = list(
        _public_barbers_queryset()
        .order_by("name")
        .values("id", "name", "slug", "title")
    )
    return render(
        request,
        "account_dashboard.html",
        {
            "home_url": "/",
            "booksy_global_url": BOOKSY_GLOBAL_URL,
            "barbers_json": json.dumps(barbers),
        },
    )


@require_http_methods(["POST"])
def api_auth_send_otp(request: HttpRequest) -> JsonResponse:
    body = _parse_json_body(request)
    try:
        phone_e164 = normalize_phone(body.get("phone", ""))
    except ValueError as exc:
        return _json_error(str(exc))

    ip_address = _client_ip(request)
    if _rate_limit_exceeded(f"otp-send:ip:{ip_address}", OTP_SEND_LIMIT, OTP_SEND_WINDOW_SECONDS):
        return _json_error("Too many verification attempts. Please wait a few minutes.", status=429)
    if _rate_limit_exceeded(f"otp-send:phone:{phone_e164}", OTP_SEND_LIMIT, OTP_SEND_WINDOW_SECONDS):
        return _json_error("Too many verification attempts. Please wait a few minutes.", status=429)

    OTPChallenge.objects.filter(
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_LOGIN,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    code = f"{random.randint(0, 999999):06d}"
    challenge = OTPChallenge.objects.create(
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_LOGIN,
        code_hash=make_password(code),
        expires_at=OTPChallenge.create_expiry(minutes=OTP_TTL_MINUTES),
    )

    sent = _send_sms(phone_e164, f"Your JP Studio verification code is {code}. It expires in 10 minutes.")

    response_data = {
        "ok": True,
        "sms_sent": sent,
        "expires_at": challenge.expires_at.isoformat(),
    }
    if settings.DEBUG:
        response_data["debug_code"] = code
    return JsonResponse(response_data, status=201)


@require_http_methods(["POST"])
def api_auth_verify_otp(request: HttpRequest) -> JsonResponse:
    body = _parse_json_body(request)
    try:
        phone_e164 = normalize_phone(body.get("phone", ""))
    except ValueError as exc:
        return _json_error(str(exc))

    code = str(body.get("code", "")).strip()
    if len(code) != 6 or not code.isdigit():
        return _json_error("Code must be a 6-digit number.")

    challenge = (
        OTPChallenge.objects.filter(
            phone_e164=phone_e164,
            purpose=OTP_PURPOSE_LOGIN,
            consumed_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if challenge is None:
        return _json_error("No active code found. Request a new code.")
    if challenge.expires_at <= timezone.now():
        return _json_error("Code expired. Request a new code.")
    if challenge.attempts >= challenge.max_attempts:
        return _json_error("Too many attempts. Request a new code.", status=429)

    if not check_password(code, challenge.code_hash):
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        return _json_error("Invalid code.")

    challenge.mark_consumed()
    account, _ = CustomerAccount.objects.get_or_create(phone_e164=phone_e164)
    if request.user.is_authenticated:
        auth_logout(request)
    request.session.cycle_key()
    request.session[SESSION_ACCOUNT_KEY] = account.id
    request.session.modified = True

    return JsonResponse({"ok": True, "account": _serialize_account(account)})


@require_http_methods(["POST"])
def api_staff_login(request: HttpRequest) -> JsonResponse:
    body = _parse_json_body(request)
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    next_url = _safe_next_path(body.get("next"), "/ops/")
    ip_address = _client_ip(request)

    if not username or not password:
        return _json_error("Username and password are required.")

    ip_key = f"staff-login:ip:{ip_address}"
    user_key = f"staff-login:user:{username.lower()}"
    if _rate_limit_exceeded(ip_key, STAFF_LOGIN_LIMIT, STAFF_LOGIN_WINDOW_SECONDS):
        return _json_error("Too many login attempts. Please wait a few minutes.", status=429)
    if _rate_limit_exceeded(user_key, STAFF_LOGIN_LIMIT, STAFF_LOGIN_WINDOW_SECONDS):
        return _json_error("Too many login attempts. Please wait a few minutes.", status=429)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return _json_error("Invalid staff credentials.", status=401)
    if not user.is_staff:
        return _json_error("This account does not have staff access.", status=403)

    cache.delete(ip_key)
    cache.delete(user_key)
    request.session.pop(SESSION_ACCOUNT_KEY, None)
    auth_login(request, user)

    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip() or user.username
    return JsonResponse(
        {
            "ok": True,
            "redirect_url": next_url,
            "user": {
                "username": user.username,
                "full_name": full_name,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            },
        }
    )


@require_http_methods(["POST"])
def api_auth_logout(request: HttpRequest) -> JsonResponse:
    request.session.pop(SESSION_ACCOUNT_KEY, None)
    if request.user.is_authenticated:
        auth_logout(request)
    else:
        request.session.modified = True
    return JsonResponse({"ok": True})


@require_GET
def api_account_me(request: HttpRequest) -> JsonResponse:
    account = _require_account(request)
    if isinstance(account, JsonResponse):
        return account
    return JsonResponse({"account": _serialize_account(account)})


@require_http_methods(["PATCH"])
def api_account_update(request: HttpRequest) -> JsonResponse:
    account = _require_account(request)
    if isinstance(account, JsonResponse):
        return account

    body = _parse_json_body(request)
    full_name = str(body.get("full_name", account.full_name)).strip()
    email = str(body.get("email", account.email)).strip()
    preferred_style = str(body.get("preferred_style", account.preferred_style)).strip()
    profile_notes = str(body.get("profile_notes", account.profile_notes)).strip()
    preferred_barber = account.preferred_barber
    preferred_barber_id = body.get("preferred_barber_id", account.preferred_barber_id)
    if preferred_barber_id in {"", None}:
        preferred_barber = None
    elif preferred_barber_id:
        preferred_barber = get_object_or_404(Barber, id=preferred_barber_id, is_active=True)

    account.full_name = full_name
    account.email = email
    account.preferred_style = preferred_style
    account.profile_notes = profile_notes
    account.preferred_barber = preferred_barber
    account.save(
        update_fields=[
            "full_name",
            "email",
            "preferred_style",
            "profile_notes",
            "preferred_barber",
            "updated_at",
        ]
    )

    return JsonResponse({"ok": True, "account": _serialize_account(account)})


@require_http_methods(["GET", "PATCH"])
def api_account_me_endpoint(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return api_account_me(request)
    return api_account_update(request)


@require_GET
def api_availability(request: HttpRequest) -> JsonResponse:
    bootstrap_reference_data()

    barber_raw = request.GET.get("barber_id")
    if barber_raw and barber_raw.isdigit():
        barber = _public_barbers_queryset().filter(id=int(barber_raw)).first()
    elif barber_raw:
        barber = _public_barbers_queryset().filter(slug=barber_raw).first()
    else:
        barber = _public_barbers_queryset().order_by("name").first()

    if barber is None:
        return _json_error("No active barbers available.", status=404)

    service_raw = request.GET.get("service_id")
    if service_raw and service_raw.isdigit():
        service = Service.objects.filter(id=int(service_raw), is_active=True).first()
    else:
        service = Service.objects.filter(is_active=True).order_by("duration_minutes", "name").first()

    if service is None:
        return _json_error("No active services available.", status=404)

    try:
        week_start = parse_week_start(request.GET.get("week_start"))
    except ValueError as exc:
        return _json_error(str(exc))

    week_end = week_start + timedelta(days=7)
    week_start_dt = timezone.make_aware(
        datetime.combine(week_start, datetime.min.time()),
        timezone.get_current_timezone(),
    )
    week_end_dt = timezone.make_aware(
        datetime.combine(week_end, datetime.min.time()),
        timezone.get_current_timezone(),
    )

    slots_by_day = generate_week_slots(barber, week_start)
    rule_windows = _build_rule_windows(barber, week_start)

    blocked_slots = set(
        Booking.objects.filter(
            barber=barber,
            start_time__gte=week_start_dt,
            start_time__lt=week_end_dt,
            status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
        ).values_list("start_time", flat=True)
    )

    days = []
    service_duration = timedelta(minutes=service.duration_minutes)
    for day_key, starts in slots_by_day.items():
        day_slots = []
        windows = rule_windows.get(day_key, [])
        for start_time in starts:
            end_time = start_time + service_duration
            fits_window = _slot_fits_any_window(start_time, end_time, windows)
            is_available = fits_window and start_time not in blocked_slots and start_time >= timezone.now()
            day_slots.append(
                {
                    "start": start_time.isoformat(),
                    "label": timezone.localtime(start_time).strftime("%I:%M %p").lstrip("0"),
                    "available": is_available,
                }
            )
        days.append({"date": day_key, "slots": day_slots})

    barbers = [
        {"id": b.id, "slug": b.slug, "name": b.name, "title": b.title, "booksy_url": b.booksy_url}
        for b in _public_barbers_queryset().order_by("name")
    ]
    services = [
        {
            "id": s.id,
            "name": s.name,
            "duration_minutes": s.duration_minutes,
            "price_cents": s.price_cents,
        }
        for s in Service.objects.filter(is_active=True).order_by("duration_minutes", "name")
    ]

    return JsonResponse(
        {
            "week_start": week_start.isoformat(),
            "timezone": timezone.get_current_timezone_name(),
            "generated_at": timezone.now().isoformat(),
            "selected_barber_id": barber.id,
            "selected_service_id": service.id,
            "barbers": barbers,
            "services": services,
            "days": days,
        }
    )

@require_http_methods(["POST"])
def api_create_booking(request: HttpRequest) -> JsonResponse:
    account = _require_account(request)
    if isinstance(account, JsonResponse):
        return account
    if account.is_inhouse_blocked:
        note = account.booking_policy_note or "Please contact the shop before making another in-house booking."
        return _json_error(note, status=403)
    if not account.full_name.strip():
        return _json_error("Complete your profile before booking your in-house appointment.")

    body = _parse_json_body(request)
    barber_id = body.get("barber_id")
    service_id = body.get("service_id")
    start_time_raw = body.get("start_time")
    notes = str(body.get("notes", "")).strip()

    if not barber_id or not service_id or not start_time_raw:
        return _json_error("barber_id, service_id, and start_time are required.")

    barber = get_object_or_404(Barber, id=barber_id, is_active=True)
    service = get_object_or_404(Service, id=service_id, is_active=True)

    try:
        start_time = _parse_iso_datetime(str(start_time_raw))
    except ValueError:
        return _json_error("Invalid start_time format. Use ISO-8601.")

    end_time = start_time + timedelta(minutes=service.duration_minutes)
    if start_time < timezone.now():
        return _json_error("Cannot book a slot in the past.")

    day = timezone.localtime(start_time).date()
    windows = _build_rule_windows(barber, day - timedelta(days=day.weekday())).get(day.isoformat(), [])
    if not _slot_fits_any_window(start_time, end_time, windows):
        return _json_error("Selected slot is outside business availability.")

    try:
        with transaction.atomic():
            conflict_exists = Booking.objects.select_for_update().filter(
                barber=barber,
                start_time=start_time,
                status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
            ).exists()
            if conflict_exists:
                return _json_error("That slot is no longer available.", status=409)

            booking = Booking.objects.create(
                customer=account,
                barber=barber,
                service=service,
                start_time=start_time,
                end_time=end_time,
                status=Booking.STATUS_CONFIRMED,
                price_cents=service.price_cents or 0,
                amount_paid_cents=0,
                payment_status=Booking.PAYMENT_UNPAID,
                origin=Booking.ORIGIN_LOCAL,
                sync_status=Booking.SYNC_LOCAL_ONLY,
                notes=notes,
            )
            BookingAudit.objects.create(
                booking=booking,
                actor_type="customer",
                actor_identifier=account.phone_e164,
                event="booking_created",
                details={"notes": notes},
            )
    except IntegrityError:
        return _json_error("That slot is no longer available.", status=409)

    return JsonResponse({"ok": True, "booking": _serialize_booking(booking)}, status=201)


@require_GET
def api_list_bookings(request: HttpRequest) -> JsonResponse:
    account = _require_account(request)
    if isinstance(account, JsonResponse):
        return account

    scope = request.GET.get("scope", "upcoming").strip().lower()
    now = timezone.now()
    queryset = Booking.objects.filter(customer=account).select_related("customer", "barber", "service")

    if scope == "upcoming":
        queryset = queryset.filter(
            start_time__gte=now,
            status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
        ).order_by("start_time")
    elif scope == "history":
        queryset = queryset.filter(
            Q(start_time__lt=now)
            | Q(
                status__in=[
                    Booking.STATUS_COMPLETED,
                    Booking.STATUS_MISSED,
                    Booking.STATUS_CANCELLED,
                ]
            )
        ).order_by("-start_time")
    else:
        return _json_error("Invalid scope. Use upcoming or history.")

    return JsonResponse({"bookings": [_serialize_booking(booking) for booking in queryset]})


@require_http_methods(["GET", "POST"])
def api_bookings(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return api_list_bookings(request)
    return api_create_booking(request)


@require_http_methods(["POST"])
def api_cancel_booking(request: HttpRequest, booking_id: int) -> JsonResponse:
    account = _require_account(request)
    if isinstance(account, JsonResponse):
        return account

    body = _parse_json_body(request)
    reason = str(body.get("reason", "")).strip()
    booking = get_object_or_404(Booking.objects.select_related("customer"), id=booking_id, customer=account)

    if booking.status not in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED}:
        return _json_error("Only upcoming bookings can be cancelled.")

    booking.status = Booking.STATUS_CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])

    BookingAudit.objects.create(
        booking=booking,
        actor_type="customer",
        actor_identifier=account.phone_e164,
        event="booking_cancelled",
        details={"reason": reason},
    )
    return JsonResponse({"ok": True, "booking": _serialize_booking(booking)})


@ensure_csrf_cookie
@require_GET
def ops_dashboard(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect(f"/account/?{urlencode({'next': request.path, 'mode': 'staff'})}")

    bootstrap_reference_data()
    barbers = list(Barber.objects.filter(is_active=True).order_by("name").values("id", "name", "slug"))
    return render(
        request,
        "ops.html",
        {
            "barbers_json": json.dumps(barbers),
            "booksy_global_url": BOOKSY_GLOBAL_URL,
        },
    )


@require_GET
def api_admin_overview(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    now = timezone.now()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    upcoming = Booking.objects.filter(
        status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
        start_time__gte=now,
    )
    completed_this_month = Booking.objects.filter(
        status=Booking.STATUS_COMPLETED,
        checked_out_at__gte=month_start,
    )
    missed_this_month = Booking.objects.filter(
        status=Booking.STATUS_MISSED,
        start_time__gte=month_start,
    )
    repeat_clients = (
        Booking.objects.filter(status=Booking.STATUS_COMPLETED)
        .values("customer_id")
        .annotate(visit_count=Count("id"))
        .filter(visit_count__gt=1)
        .count()
    )
    barber_stats = []
    for barber in Barber.objects.filter(is_active=True).order_by("name"):
        barber_completed = completed_this_month.filter(barber=barber)
        barber_stats.append(
            {
                "barber_id": barber.id,
                "barber_name": barber.name,
                "completed_visits": barber_completed.count(),
                "revenue_cents": barber_completed.aggregate(total=Sum("amount_paid_cents"))["total"] or 0,
            }
        )

    recent_bookings = Booking.objects.select_related("customer", "barber", "service").order_by("-start_time")[:8]
    return JsonResponse(
        {
            "summary": {
                "upcoming_bookings": upcoming.count(),
                "monthly_revenue_cents": completed_this_month.aggregate(total=Sum("amount_paid_cents"))["total"] or 0,
                "missed_this_month": missed_this_month.count(),
                "repeat_clients": repeat_clients,
                "customers_total": CustomerAccount.objects.count(),
                "flagged_customers": CustomerAccount.objects.filter(is_inhouse_blocked=True).count(),
            },
            "barber_stats": barber_stats,
            "recent_bookings": [_serialize_booking(booking) for booking in recent_bookings],
        }
    )


@require_GET
def api_admin_reports(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error
    return JsonResponse(_build_reports_payload())


@require_GET
def api_admin_bookings_feed(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    query = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip().lower()
    origin = request.GET.get("origin", "").strip().lower()
    start = request.GET.get("start", "").strip()
    end = request.GET.get("end", "").strip()
    queryset = Booking.objects.select_related("customer", "barber", "service").order_by("-start_time")

    if query:
        queryset = queryset.filter(
            Q(customer__full_name__icontains=query)
            | Q(customer__phone_e164__icontains=query)
            | Q(barber__name__icontains=query)
            | Q(service__name__icontains=query)
            | Q(external_booking_id__icontains=query)
        )
    if status in {
        Booking.STATUS_CONFIRMED,
        Booking.STATUS_COMPLETED,
        Booking.STATUS_MISSED,
        Booking.STATUS_CANCELLED,
        Booking.STATUS_RESCHEDULED,
    }:
        queryset = queryset.filter(status=status)
    if origin in {Booking.ORIGIN_LOCAL, Booking.ORIGIN_BOOKSY, Booking.ORIGIN_SYNCED}:
        queryset = queryset.filter(origin=origin)
    if start:
        try:
            queryset = queryset.filter(start_time__gte=_parse_iso_date_boundary(start))
        except ValueError:
            return _json_error("Invalid start date.")
    if end:
        try:
            queryset = queryset.filter(start_time__lt=_parse_iso_date_boundary(end, end_of_day=True))
        except ValueError:
            return _json_error("Invalid end date.")

    limit = 200 if start or end else 80
    bookings = queryset[:limit]
    return JsonResponse({"bookings": [_serialize_booking(booking) for booking in bookings]})


@require_GET
def api_admin_customers(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    query = request.GET.get("search", "").strip()
    customers = CustomerAccount.objects.select_related("preferred_barber").order_by("-updated_at")
    if query:
        customers = customers.filter(
            Q(full_name__icontains=query)
            | Q(phone_e164__icontains=query)
            | Q(email__icontains=query)
            | Q(preferred_style__icontains=query)
        )

    payload = [_customer_record_summary(customer) for customer in customers[:50]]
    return JsonResponse({"customers": payload})


@require_http_methods(["GET", "PATCH"])
def api_admin_customer_detail(request: HttpRequest, customer_id: int) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    customer = get_object_or_404(
        CustomerAccount.objects.select_related("preferred_barber"),
        id=customer_id,
    )

    if request.method == "PATCH":
        body = _parse_json_body(request)
        preferred_barber_id = body.get("preferred_barber_id")
        preferred_barber = None
        if preferred_barber_id:
            preferred_barber = get_object_or_404(Barber, id=preferred_barber_id, is_active=True)
        customer.full_name = str(body.get("full_name", customer.full_name)).strip()
        customer.email = str(body.get("email", customer.email)).strip()
        customer.preferred_style = str(body.get("preferred_style", customer.preferred_style)).strip()
        customer.profile_notes = str(body.get("profile_notes", customer.profile_notes)).strip()
        customer.booking_policy_note = str(
            body.get("booking_policy_note", customer.booking_policy_note)
        ).strip()
        customer.preferred_barber = preferred_barber
        next_blocked = _coerce_bool(body.get("is_inhouse_blocked"), customer.is_inhouse_blocked)
        customer.is_inhouse_blocked = next_blocked
        if next_blocked and customer.blocked_at is None:
            customer.blocked_at = timezone.now()
        if not next_blocked:
            customer.blocked_at = None
        customer.save(
            update_fields=[
                "full_name",
                "email",
                "preferred_style",
                "profile_notes",
                "booking_policy_note",
                "preferred_barber",
                "is_inhouse_blocked",
                "blocked_at",
                "updated_at",
            ]
        )

    recent_bookings = customer.bookings.select_related("barber", "service").order_by("-start_time")[:20]
    return JsonResponse(
        {
            "customer": _customer_record_summary(customer),
            "bookings": [_serialize_booking(booking) for booking in recent_bookings],
        }
    )


@require_http_methods(["GET", "PATCH"])
def api_admin_staff_profile(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    profile, _ = StaffProfile.objects.get_or_create(user=request.user)
    if request.method == "PATCH":
        body = _parse_json_body(request)
        linked_barber_id = body.get("linked_barber_id")
        linked_barber = None
        if linked_barber_id:
            linked_barber = get_object_or_404(Barber, id=linked_barber_id, is_active=True)
        request.user.first_name = str(body.get("first_name", request.user.first_name)).strip()
        request.user.last_name = str(body.get("last_name", request.user.last_name)).strip()
        request.user.email = str(body.get("email", request.user.email)).strip()
        request.user.save(update_fields=["first_name", "last_name", "email"])

        profile.phone = str(body.get("phone", profile.phone)).strip()
        profile.title = str(body.get("title", profile.title)).strip()
        profile.bio = str(body.get("bio", profile.bio)).strip()
        profile.linked_barber = linked_barber
        profile.save(update_fields=["phone", "title", "bio", "linked_barber", "updated_at"])

    return JsonResponse({"profile": _serialize_staff_profile(profile)})


@require_http_methods(["POST"])
def api_admin_create_booking(request: HttpRequest) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    body = _parse_json_body(request)
    customer_id = body.get("customer_id")
    barber_id = body.get("barber_id")
    service_id = body.get("service_id")
    start_time_raw = body.get("start_time")
    notes = str(body.get("notes", "")).strip()

    if not customer_id or not barber_id or not service_id or not start_time_raw:
        return _json_error("customer_id, barber_id, service_id, and start_time are required.")

    customer = get_object_or_404(CustomerAccount, id=customer_id)
    barber = get_object_or_404(Barber, id=barber_id, is_active=True)
    service = get_object_or_404(Service, id=service_id, is_active=True)
    try:
        start_time = _parse_iso_datetime(str(start_time_raw))
    except ValueError:
        return _json_error("Invalid start_time format. Use ISO-8601.")

    end_time = start_time + timedelta(minutes=service.duration_minutes)
    day = timezone.localtime(start_time).date()
    windows = _build_rule_windows(barber, day - timedelta(days=day.weekday())).get(day.isoformat(), [])
    if not _slot_fits_any_window(start_time, end_time, windows):
        return _json_error("Selected slot is outside business availability.")

    try:
        with transaction.atomic():
            conflict_exists = Booking.objects.select_for_update().filter(
                barber=barber,
                start_time=start_time,
                status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED],
            ).exists()
            if conflict_exists:
                return _json_error("That slot is no longer available.", status=409)
            booking = Booking.objects.create(
                customer=customer,
                barber=barber,
                service=service,
                start_time=start_time,
                end_time=end_time,
                status=Booking.STATUS_CONFIRMED,
                price_cents=service.price_cents or 0,
                amount_paid_cents=0,
                payment_status=Booking.PAYMENT_UNPAID,
                origin=Booking.ORIGIN_LOCAL,
                sync_status=Booking.SYNC_LOCAL_ONLY,
                notes=notes,
            )
            BookingAudit.objects.create(
                booking=booking,
                actor_type="staff",
                actor_identifier=request.user.username,
                event="booking_created_by_staff",
                details={"notes": notes},
            )
    except IntegrityError:
        return _json_error("That slot is no longer available.", status=409)

    return JsonResponse({"ok": True, "booking": _serialize_booking(booking)}, status=201)


@require_http_methods(["POST"])
def api_admin_mark_completed(request: HttpRequest, booking_id: int) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    body = _parse_json_body(request)
    booking = get_object_or_404(Booking.objects.select_related("barber", "service", "customer"), id=booking_id)
    if booking.status not in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED}:
        return _json_error("Booking cannot be marked completed from current state.")

    amount_paid_cents = body.get("amount_paid_cents", booking.price_cents or booking.service.price_cents or 0)
    try:
        amount_paid_cents = max(0, int(amount_paid_cents))
    except (TypeError, ValueError):
        return _json_error("amount_paid_cents must be a whole number.")

    booking.status = Booking.STATUS_COMPLETED
    booking.amount_paid_cents = amount_paid_cents
    booking.payment_status = _payment_status_for_amount(booking.price_cents, amount_paid_cents)
    booking.checked_out_at = timezone.now()
    booking.save(update_fields=["status", "amount_paid_cents", "payment_status", "checked_out_at", "updated_at"])
    BookingAudit.objects.create(
        booking=booking,
        actor_type="staff",
        actor_identifier=request.user.username,
        event="booking_completed",
        details={"amount_paid_cents": amount_paid_cents},
    )
    return JsonResponse({"ok": True, "booking": _serialize_booking(booking)})


@require_http_methods(["POST"])
def api_admin_mark_missed(request: HttpRequest, booking_id: int) -> JsonResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    booking = get_object_or_404(Booking.objects.select_related("barber", "service", "customer"), id=booking_id)
    if booking.status not in {Booking.STATUS_CONFIRMED, Booking.STATUS_RESCHEDULED}:
        return _json_error("Booking cannot be marked missed from current state.")

    booking.status = Booking.STATUS_MISSED
    booking.amount_paid_cents = 0
    booking.payment_status = Booking.PAYMENT_UNPAID
    booking.checked_out_at = None
    booking.save(update_fields=["status", "amount_paid_cents", "payment_status", "checked_out_at", "updated_at"])
    customer = booking.customer
    customer.missed_appointments_count += 1
    customer.save(update_fields=["missed_appointments_count", "updated_at"])
    BookingAudit.objects.create(
        booking=booking,
        actor_type="staff",
        actor_identifier=request.user.username,
        event="booking_marked_missed",
        details={"missed_appointments_count": customer.missed_appointments_count},
    )
    return JsonResponse({"ok": True, "booking": _serialize_booking(booking)})


@require_GET
def api_admin_export_bookings_csv(request: HttpRequest) -> HttpResponse:
    staff_error = _require_staff(request)
    if staff_error:
        return staff_error

    bookings = Booking.objects.select_related("customer", "barber", "service").order_by("-start_time")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "booking_id",
            "status",
            "origin",
            "sync_status",
            "external_booking_id",
            "payment_status",
            "price_cents",
            "amount_paid_cents",
            "customer_name",
            "customer_phone",
            "barber",
            "service",
            "start_time",
            "end_time",
            "last_synced_at",
            "cancellation_reason",
            "created_at",
        ]
    )
    for booking in bookings:
        writer.writerow(
            [
                booking.id,
                booking.status,
                booking.origin,
                booking.sync_status,
                booking.external_booking_id,
                booking.payment_status,
                booking.price_cents,
                booking.amount_paid_cents,
                booking.customer.full_name,
                booking.customer.phone_e164,
                booking.barber.name,
                booking.service.name,
                booking.start_time.isoformat(),
                booking.end_time.isoformat(),
                booking.last_synced_at.isoformat() if booking.last_synced_at else "",
                booking.cancellation_reason,
                booking.created_at.isoformat(),
            ]
        )

    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="bookings_export.csv"'
    return response
