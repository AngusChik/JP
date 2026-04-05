from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List

from django.utils import timezone

from .models import AvailabilityRule, Barber, Service


DEFAULT_BARBERS = [
    {
        "slug": "jp",
        "name": "JP",
        "title": "Owner / Lead Barber",
        "booksy_url": "https://booksy.com/en-ca/21963_jp-barber-studio_barbershop_870806_mississauga#ba_s=sh_1",
    },
]

DEFAULT_SERVICES = [
    {"name": "Skin Fade", "duration_minutes": 40, "price_cents": 4000},
    {"name": "Buzz Cut", "duration_minutes": 25, "price_cents": 2500},
    {"name": "Classic Taper", "duration_minutes": 40, "price_cents": 3500},
    {"name": "Fade + Beard", "duration_minutes": 55, "price_cents": 5500},
]


def bootstrap_reference_data() -> None:
    for barber_data in DEFAULT_BARBERS:
        barber, _ = Barber.objects.get_or_create(
            slug=barber_data["slug"],
            defaults={
                "name": barber_data["name"],
                "title": barber_data["title"],
                "booksy_url": barber_data["booksy_url"],
                "is_active": True,
            },
        )
        changed = False
        if barber.name != barber_data["name"]:
            barber.name = barber_data["name"]
            changed = True
        if barber.title != barber_data["title"]:
            barber.title = barber_data["title"]
            changed = True
        if barber.booksy_url != barber_data["booksy_url"]:
            barber.booksy_url = barber_data["booksy_url"]
            changed = True
        if changed:
            barber.save(update_fields=["name", "title", "booksy_url", "updated_at"])

    for service_data in DEFAULT_SERVICES:
        Service.objects.get_or_create(
            name=service_data["name"],
            defaults={
                "duration_minutes": service_data["duration_minutes"],
                "price_cents": service_data["price_cents"],
                "is_active": True,
            },
        )

    # Default to Monday-Saturday 9am-6pm in 30-minute increments if no rules exist.
    if AvailabilityRule.objects.exists():
        return

    for barber in Barber.objects.filter(is_active=True):
        for day_of_week in range(0, 6):
            AvailabilityRule.objects.create(
                barber=barber,
                day_of_week=day_of_week,
                start_time=time(hour=9, minute=0),
                end_time=time(hour=18, minute=0),
                slot_minutes=30,
                is_active=True,
            )


def normalize_phone(raw_phone: str) -> str:
    digits = "".join(ch for ch in (raw_phone or "") if ch.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    if len(digits) != 11 or not digits.startswith("1"):
        raise ValueError("Please enter a valid North American phone number.")
    return f"+{digits}"


def parse_week_start(raw_week_start: str | None) -> date:
    if raw_week_start:
        try:
            selected = date.fromisoformat(raw_week_start)
        except ValueError as exc:
            raise ValueError("Invalid week_start date format. Use YYYY-MM-DD.") from exc
    else:
        selected = timezone.localdate()
    return selected - timedelta(days=selected.weekday())


def _make_aware(day: date, time_value: time) -> datetime:
    naive = datetime.combine(day, time_value)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def generate_week_slots(barber: Barber, week_start: date) -> Dict[str, List[datetime]]:
    rules = (
        AvailabilityRule.objects.filter(barber=barber, is_active=True)
        .order_by("day_of_week", "start_time")
    )
    slots_by_day: Dict[str, List[datetime]] = {}

    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_key = day.isoformat()
        slots_by_day[day_key] = []

        day_rules = [rule for rule in rules if rule.day_of_week == day.weekday()]
        for rule in day_rules:
            slot_start = _make_aware(day, rule.start_time)
            rule_end = _make_aware(day, rule.end_time)
            step = timedelta(minutes=rule.slot_minutes)
            while slot_start + step <= rule_end:
                slots_by_day[day_key].append(slot_start)
                slot_start += step

    for key in slots_by_day:
        slots_by_day[key].sort()

    return slots_by_day
