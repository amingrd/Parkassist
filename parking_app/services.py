from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from parking_app.notifications import Notification, NotificationSink


class BookingError(Exception):
    pass


@dataclass
class ValidationResult:
    allowed: bool
    reasons: list[str]


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def workweek_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=4)
    return start, end


def build_calendar_days(window_days: int) -> list[date]:
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = today + timedelta(days=max(window_days - 1, 0))
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_next_workdays(window_days: int) -> list[date]:
    return [day for day in build_calendar_days(window_days) if day.weekday() < 5 and day >= date.today()]


class BookingService:
    def __init__(self, repository, notifier: NotificationSink) -> None:
        self.repository = repository
        self.notifier = notifier

    def validate_booking(
        self,
        user_id: int,
        booking_date_str: str,
        vehicle_height_cm: Optional[int] = None,
        requested_spot_id: Optional[int] = None,
        guest_name: str = "",
        guest_email: str = "",
    ) -> ValidationResult:
        user = self.repository.get_user(user_id)
        if user and user["is_banned"]:
            return ValidationResult(False, ["You are currently blocked from booking parking. Please contact Office Management."])

        rules = self.repository.get_rules()
        booking_date = parse_iso_date(booking_date_str)
        reasons: list[str] = []
        guest_name = guest_name.strip()
        guest_email = guest_email.strip().lower()
        is_guest_booking = bool(guest_name or guest_email)

        if booking_date.weekday() >= 5:
            reasons.append("Parking can only be booked for Monday to Friday.")

        earliest = date.today()
        latest = date.today() + timedelta(days=max(rules["booking_window_days"] - 1, 0))
        if booking_date < earliest or booking_date > latest:
            reasons.append(f"You may only book up to {rules['booking_window_days']} days in advance.")

        if not is_guest_booking and self.repository.get_user_booking_for_date(user_id, booking_date_str):
            reasons.append("You already have a parking booking for this day.")

        if is_guest_booking:
            if not guest_name:
                reasons.append("Please enter a guest name.")
            if self.repository.find_guest_booking_for_date(guest_name, guest_email, booking_date_str):
                reasons.append("That guest already has a parking booking for this day.")

        active_overrides = {row["scope"] for row in self.repository.list_active_overrides_for_date(user_id, booking_date_str)}

        if not is_guest_booking:
            week_start, week_end = workweek_bounds(booking_date)
            dates_in_week = self.repository.list_active_booking_dates_for_user(
                user_id, week_start.isoformat(), week_end.isoformat()
            )
            weekly_total = len(dates_in_week) + 1
            if (
                weekly_total > rules["max_days_per_week"]
                and "weekly_limit" not in active_overrides
                and "all_rules" not in active_overrides
            ):
                reasons.append(f"You may only book {rules['max_days_per_week']} days per work week.")

            streak_range_start = booking_date - timedelta(days=rules["max_consecutive_days"] + 3)
            streak_range_end = booking_date + timedelta(days=rules["max_consecutive_days"] + 3)
            booked_dates = self.repository.list_active_booking_dates_for_user(
                user_id, streak_range_start.isoformat(), streak_range_end.isoformat()
            )
            all_days = {parse_iso_date(value) for value in booked_dates}
            all_days.add(booking_date)
            streak = self._max_consecutive_streak(all_days)
            if (
                streak > rules["max_consecutive_days"]
                and "consecutive_limit" not in active_overrides
                and "all_rules" not in active_overrides
            ):
                reasons.append(f"You may only book {rules['max_consecutive_days']} consecutive days in a row.")

        available = self.repository.list_available_spots(booking_date_str, vehicle_height_cm)
        if requested_spot_id:
            requested_spot = self.repository.get_spot(requested_spot_id)
            if requested_spot is None or not requested_spot["is_active"]:
                reasons.append("The selected parking space is not available.")
            elif vehicle_height_cm and requested_spot["max_height_cm"] and vehicle_height_cm > requested_spot["max_height_cm"]:
                reasons.append(
                    f"{requested_spot['label']} is too low for a vehicle height of {vehicle_height_cm} cm."
                )
            elif all(spot["id"] != requested_spot_id for spot in available):
                reasons.append("The selected parking space is already booked.")

        return ValidationResult(allowed=not reasons, reasons=reasons)

    def create_booking(
        self,
        actor_user_id: int,
        target_user_id: int,
        booking_date_str: str,
        requested_spot_id: Optional[int] = None,
        source: str = "web",
        vehicle_height_cm: Optional[int] = None,
        policy_acknowledged: bool = False,
        half_day: bool = False,
        guest_name: str = "",
        guest_email: str = "",
    ) -> int:
        if not policy_acknowledged:
            raise BookingError("Please confirm that you need the space for a full office day and that you accept the parking rules.")

        validation = self.validate_booking(
            target_user_id,
            booking_date_str,
            vehicle_height_cm,
            requested_spot_id,
            guest_name=guest_name,
            guest_email=guest_email,
        )
        if not validation.allowed:
            raise BookingError(" ".join(validation.reasons))

        available = self.repository.list_available_spots(booking_date_str, vehicle_height_cm)
        if not available:
            raise BookingError("No parking spaces are available for that date. Join the waitlist instead.")

        if requested_spot_id:
            spot = next((candidate for candidate in available if candidate["id"] == requested_spot_id), None)
            if spot is None:
                raise BookingError("The selected parking space is no longer available.")
        else:
            spot = available[0]

        booking_id = self.repository.create_booking(
            target_user_id,
            spot["id"],
            booking_date_str,
            source,
            vehicle_height_cm=vehicle_height_cm,
            half_day=half_day,
            guest_name=guest_name.strip(),
            guest_email=guest_email.strip().lower(),
        )
        self.repository.log_audit(actor_user_id, "booking_created", f"user={target_user_id} date={booking_date_str} spot={spot['label']}")
        self.notifier.send(
            Notification(
                kind="booking_created",
                user_id=target_user_id,
                title="Parking confirmed",
                message=f"Your parking space {spot['label']} is confirmed for {booking_date_str}.",
            )
        )
        if guest_email.strip():
            booker = self.repository.get_user(actor_user_id)
            booked_by = booker["name"] if booker else "A colleague"
            self.notifier.send(
                Notification(
                    kind="guest_booking_created",
                    user_id=target_user_id,
                    recipient_email=guest_email.strip().lower(),
                    title="Guest parking booked for you",
                    message=f"{booked_by} booked parking space {spot['label']} for you on {booking_date_str}. You can also find the parking guide video below.",
                )
            )
        return booking_id

    def cancel_booking(
        self,
        actor_user_id: int,
        booking_id: int,
        *,
        channel_notice_sent: bool = False,
        is_sick: bool = False,
        is_admin: bool = False,
    ) -> Optional[int]:
        booking = self.repository.get_booking(booking_id)
        if booking is None or booking["status"] != "active":
            raise BookingError("That booking is no longer active.")
        booking_day = parse_iso_date(booking["booking_date"])
        today = date.today()
        if not is_admin:
            if booking_day == today and not is_sick:
                raise BookingError("Same-day cancellations are only allowed when you are sick or when Office Management handles it.")
            if booking_day > today and not channel_notice_sent:
                raise BookingError("Please confirm that you posted the release in the parking channel before cancelling.")
        self.repository.cancel_booking(booking_id, actor_user_id, channel_notice_sent or is_sick or is_admin)
        self.repository.log_audit(actor_user_id, "booking_cancelled", f"booking={booking_id} date={booking['booking_date']}")
        self.notifier.send(
            Notification(
                kind="booking_cancelled",
                user_id=booking["user_id"],
                title="Parking cancelled",
                message=f"Your booking for {booking['booking_date']} has been cancelled.",
            )
        )
        return self.promote_waitlist(booking["booking_date"], actor_user_id)

    def join_waitlist(
        self,
        actor_user_id: int,
        target_user_id: int,
        booking_date_str: str,
        vehicle_height_cm: Optional[int] = None,
    ) -> int:
        validation = self.validate_booking(target_user_id, booking_date_str, vehicle_height_cm)
        if not validation.allowed:
            raise BookingError(" ".join(validation.reasons))

        if self.repository.list_available_spots(booking_date_str, vehicle_height_cm):
            raise BookingError("A compatible parking space is still available for that date, so no waitlist is needed.")
        existing = self.repository.find_active_waitlist_entry(target_user_id, booking_date_str)
        if existing:
            raise BookingError("You are already on the waitlist for this date.")
        waitlist_id = self.repository.add_waitlist_entry(target_user_id, booking_date_str, vehicle_height_cm)
        self.repository.log_audit(actor_user_id, "waitlist_joined", f"user={target_user_id} date={booking_date_str}")
        self.notifier.send(
            Notification(
                kind="waitlist_joined",
                user_id=target_user_id,
                title="You joined the parking waitlist",
                message=f"You are on the waitlist for {booking_date_str}. We will email you if a matching spot opens up.",
            )
        )
        return waitlist_id

    def leave_waitlist(self, actor_user_id: int, entry_id: int) -> None:
        self.repository.cancel_waitlist_entry(entry_id)
        self.repository.log_audit(actor_user_id, "waitlist_left", f"entry={entry_id}")

    def promote_waitlist(self, booking_date_str: str, actor_user_id: int) -> Optional[int]:
        for entry in self.repository.list_waitlist_for_date(booking_date_str):
            validation = self.validate_booking(entry["user_id"], booking_date_str, entry["vehicle_height_cm"])
            compatible_spots = self.repository.list_available_spots(booking_date_str, entry["vehicle_height_cm"])
            if not validation.allowed or not compatible_spots:
                continue
            booking_id = self.create_booking(
                actor_user_id=actor_user_id,
                target_user_id=entry["user_id"],
                booking_date_str=booking_date_str,
                source="waitlist",
                vehicle_height_cm=entry["vehicle_height_cm"],
                policy_acknowledged=True,
            )
            self.repository.promote_waitlist_entry(entry["id"], booking_id)
            self.repository.log_audit(actor_user_id, "waitlist_promoted", f"entry={entry['id']} booking={booking_id}")
            booked_spot = self.repository.get_booking(booking_id)
            spot = self.repository.get_spot(booked_spot["spot_id"]) if booked_spot else None
            self.notifier.send(
                Notification(
                    kind="waitlist_promoted",
                    user_id=entry["user_id"],
                    title="Waitlist promotion",
                    message=f"A parking space opened up and was assigned to you for {booking_date_str}{f' at {spot['label']}' if spot else ''}.",
                )
            )
            return booking_id
        return None

    def _max_consecutive_streak(self, dates: Iterable[date]) -> int:
        ordered = sorted(dates)
        if not ordered:
            return 0
        longest = 1
        current = 1
        for previous, current_day in zip(ordered, ordered[1:]):
            if (current_day - previous).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        return longest
