import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from parking_app.notifications import LocalNotificationSink
from parking_app.repository import Repository
from parking_app.services import BookingError, BookingService


def next_workday(offset: int = 0) -> str:
    cursor = date.today()
    seen = -1
    while True:
        if cursor.weekday() < 5:
            seen += 1
        if seen == offset:
            return cursor.isoformat()
        cursor += timedelta(days=1)


def spaced_workdays_in_same_week(count: int) -> list[str]:
    cursor = date.today()
    while True:
        week_start = cursor - timedelta(days=cursor.weekday())
        candidates = [
            week_start.isoformat(),
            (week_start + timedelta(days=2)).isoformat(),
            (week_start + timedelta(days=4)).isoformat(),
        ]
        valid = [day for day in candidates if day >= date.today().isoformat()]
        if len(valid) >= count:
            return valid[:count]
        cursor = week_start + timedelta(days=7)


def consecutive_workdays(count: int) -> list[str]:
    cursor = date.today()
    while cursor.weekday() > 2:
        cursor += timedelta(days=1)
    days = []
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


class BookingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp_dir.name) / "test.db", seed_demo_data=False)
        self.repo.update_rules(3, 2, 7)
        self.service = BookingService(self.repo, LocalNotificationSink(self.repo))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_booking_succeeds_within_limits(self) -> None:
        booking_id = self.service.create_booking(2, 2, next_workday(2), policy_acknowledged=True)
        self.assertGreater(booking_id, 0)

    def test_weekly_limit_is_enforced(self) -> None:
        self.repo.update_rules(2, 2, 14)
        day_one, day_two, day_three = spaced_workdays_in_same_week(3)
        self.service.create_booking(2, 2, day_one, policy_acknowledged=True)
        self.service.create_booking(2, 2, day_two, policy_acknowledged=True)
        with self.assertRaises(BookingError):
            self.service.create_booking(2, 2, day_three, policy_acknowledged=True)

    def test_consecutive_limit_is_enforced(self) -> None:
        self.service.create_booking(2, 2, next_workday(1), policy_acknowledged=True)
        self.service.create_booking(2, 2, next_workday(2), policy_acknowledged=True)
        with self.assertRaises(BookingError):
            self.service.create_booking(2, 2, next_workday(3), policy_acknowledged=True)

    def test_policy_acknowledgement_is_required(self) -> None:
        with self.assertRaises(BookingError):
            self.service.create_booking(2, 2, next_workday(2), policy_acknowledged=False)

    def test_user_cannot_book_two_spots_for_same_day(self) -> None:
        target_day = next_workday(2)
        self.service.create_booking(2, 2, target_day, policy_acknowledged=True)
        with self.assertRaises(BookingError):
            self.service.create_booking(2, 2, target_day, policy_acknowledged=True)

    def test_guest_booking_can_be_added_for_same_day(self) -> None:
        target_day = next_workday(2)
        self.service.create_booking(2, 2, target_day, policy_acknowledged=True)
        guest_booking_id = self.service.create_booking(
            2,
            2,
            target_day,
            policy_acknowledged=True,
            guest_name="Guest Driver",
            guest_email="guest.driver@example.com",
        )
        self.assertGreater(guest_booking_id, 0)

    def test_guest_cannot_book_two_spots_for_same_day(self) -> None:
        target_day = next_workday(2)
        self.service.create_booking(
            2,
            2,
            target_day,
            policy_acknowledged=True,
            guest_name="Guest Driver",
            guest_email="guest.driver@example.com",
        )
        with self.assertRaises(BookingError):
            self.service.create_booking(
                2,
                2,
                target_day,
                policy_acknowledged=True,
                guest_name="Guest Driver",
                guest_email="guest.driver@example.com",
            )

    def test_override_allows_otherwise_blocked_booking(self) -> None:
        target_day = next_workday(2)
        self.repo.create_override(2, target_day, target_day, "all_rules", "Executive exception")
        self.service.create_booking(2, 2, next_workday(1), policy_acknowledged=True)
        booking_id = self.service.create_booking(2, 2, target_day, policy_acknowledged=True)
        self.assertGreater(booking_id, 0)

    def test_elevator_height_limit_is_enforced(self) -> None:
        target_day = next_workday(2)
        p5_upper = self.repo.get_spot_by_label("P6")
        with self.assertRaises(BookingError):
            self.service.create_booking(
                2,
                2,
                target_day,
                requested_spot_id=p5_upper["id"],
                vehicle_height_cm=160,
                policy_acknowledged=True,
            )

    def test_day_before_channel_notice_is_required_for_cancellation(self) -> None:
        target_day = next_workday(2)
        booking_id = self.service.create_booking(2, 2, target_day, policy_acknowledged=True)
        with self.assertRaises(BookingError):
            self.service.cancel_booking(2, booking_id, channel_notice_sent=False, is_admin=False)
        self.service.cancel_booking(2, booking_id, channel_notice_sent=True, is_admin=False)
        self.assertEqual(self.repo.get_booking(booking_id)["status"], "cancelled")

    def test_waitlist_join_and_promotion(self) -> None:
        target_day = next_workday(1)
        for spot in self.repo.list_available_spots(target_day):
            self.repo.create_booking(4, spot["id"], target_day, "test-fill")
        entry_id = self.service.join_waitlist(2, 2, target_day)
        self.assertGreater(entry_id, 0)
        booking_to_cancel = self.repo.list_bookings_for_date(target_day)[0]["id"]
        promoted_booking_id = self.service.cancel_booking(1, booking_to_cancel, is_admin=True)
        self.assertIsNotNone(promoted_booking_id)

    def test_waitlist_promotion_skips_newly_ineligible_users(self) -> None:
        first_day, second_day, third_day = consecutive_workdays(3)
        for spot in self.repo.list_available_spots(third_day):
            self.repo.create_booking(4, spot["id"], third_day, "test-fill")
        self.service.join_waitlist(3, 3, third_day)
        self.service.join_waitlist(2, 2, third_day)
        self.repo.create_booking(3, self.repo.get_spot_by_label("P14")["id"], first_day, "test-seed")
        self.repo.create_booking(3, self.repo.get_spot_by_label("P15")["id"], second_day, "test-seed")
        cancelled = self.repo.list_bookings_for_date(third_day)[0]["id"]
        self.service.cancel_booking(1, cancelled, is_admin=True)
        promoted = self.repo.get_user_booking_for_date(2, third_day)
        skipped = self.repo.get_user_booking_for_date(3, third_day)
        self.assertIsNotNone(promoted)
        self.assertIsNone(skipped)

    def test_notification_events_are_recorded(self) -> None:
        self.service.create_booking(2, 2, next_workday(2), policy_acknowledged=True)
        notifications = self.repo.list_notification_events()
        self.assertTrue(any(event["kind"] == "booking_created" for event in notifications))


if __name__ == "__main__":
    unittest.main()
