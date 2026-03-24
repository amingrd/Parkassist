from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps
from parking_app.notifications import Notification, NotificationSink


class BookingError(Exception):
    pass


class BannerError(Exception):
    def __init__(self, message: str, *, field_errors: Optional[dict[str, str]] = None) -> None:
        super().__init__(message)
        self.field_errors = field_errors or {}


@dataclass
class ValidationResult:
    allowed: bool
    reasons: list[str]


@dataclass
class UploadedBannerImage:
    filename: str
    content_type: str
    body: bytes


@dataclass
class BannerImageDetails:
    mime_type: str
    width_px: int
    height_px: int
    size_bytes: int
    extension: str


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def workweek_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=4)
    return start, end


def build_calendar_days(window_days: int) -> list[date]:
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = today + timedelta(days=window_days)
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
        latest = date.today() + timedelta(days=rules["booking_window_days"])
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
            self.notifier.send(
                Notification(
                    kind="waitlist_promoted",
                    user_id=entry["user_id"],
                    title="Waitlist promotion",
                    message=f"A parking space opened up and was assigned to you for {booking_date_str}.",
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


class BannerService:
    def __init__(self, repository, uploads_dir: Path, artifacts_dir: Path) -> None:
        self.repository = repository
        self.uploads_dir = uploads_dir
        self.artifacts_dir = artifacts_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def list_template_sets(self) -> list[dict]:
        return [self._template_row_to_dict(row) for row in self.repository.list_banner_template_sets()]

    def get_template_set(self, template_set_id: str) -> dict:
        row = self.repository.get_banner_template_set(template_set_id)
        if row is None:
            raise BannerError("The selected banner template set does not exist.")
        return self._template_row_to_dict(row)

    def list_runs_for_user(self, user_id: int, limit: int = 12) -> list[dict]:
        return [self._run_row_to_dict(row) for row in self.repository.list_banner_runs_for_user(user_id, limit)]

    def get_run_for_user(self, user_id: int, run_id: int) -> Optional[dict]:
        row = self.repository.get_banner_run(run_id)
        if row is None or row["user_id"] != user_id:
            return None
        return self._run_row_to_dict(row)

    def generate_banner_run(
        self,
        *,
        user_id: int,
        template_set_id: str,
        headline: str,
        subline: str,
        button_text: str,
        image: UploadedBannerImage,
    ) -> int:
        template = self.get_template_set(template_set_id)
        try:
            normalized = self._normalize_fields(headline, subline, button_text)
            field_errors = self.validate_banner_fields(template_set_id, normalized["headline"], normalized["subline"], normalized["button_text"])
            if field_errors:
                raise BannerError("Please fix the banner fields below.", field_errors=field_errors)
            image_details = self._inspect_image(image, template)
        except BannerError as exc:
            self.repository.create_banner_run(
                user_id,
                template_set_id,
                headline.strip(),
                subline.strip(),
                button_text.strip(),
                image.filename or "",
                "",
                image.content_type or "",
                0,
                0,
                len(image.body),
                "failed",
                str(exc),
            )
            raise

        stored_name = self._build_stored_image_name(image.filename, image_details.extension)
        image_path = self.uploads_dir / stored_name
        image_path.write_bytes(image.body)

        payload = self._build_plugin_payload(template, normalized, image_path.name, image_details)
        payload_filename = f"{stored_name.rsplit('.', 1)[0]}-plugin-payload.json"
        payload_path = self.artifacts_dir / payload_filename
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        export_paths = self._render_banner_exports(template, normalized, image_path)
        zip_filename = f"{stored_name.rsplit('.', 1)[0]}-exports.zip"
        zip_path = self.artifacts_dir / zip_filename
        self._write_export_zip(zip_path, export_paths, payload, normalized)

        return self.repository.create_banner_run(
            user_id,
            template_set_id,
            normalized["headline"],
            normalized["subline"],
            normalized["button_text"],
            image.filename,
            image_path.name,
            image_details.mime_type,
            image_details.width_px,
            image_details.height_px,
            image_details.size_bytes,
            "completed",
            "",
            zip_path.name,
            payload_path.name,
        )

    def rerun_banner(self, user_id: int, run_id: int) -> int:
        existing = self.get_run_for_user(user_id, run_id)
        if existing is None:
            raise BannerError("That banner export could not be found.")
        source_path = self.uploads_dir / existing["stored_image_name"]
        if not source_path.exists():
            raise BannerError("The original image for this export is no longer available.")
        return self.generate_banner_run(
            user_id=user_id,
            template_set_id=existing["template_set_id"],
            headline=existing["headline"],
            subline=existing["subline"],
            button_text=existing["button_text"],
            image=UploadedBannerImage(
                filename=existing["original_image_name"],
                content_type=existing["image_mime_type"],
                body=source_path.read_bytes(),
            ),
        )

    def _template_row_to_dict(self, row) -> dict:
        config = json.loads(row["config_json"])
        return {
            "id": row["id"],
            "display_name": row["display_name"],
            "figma_file_key": row["figma_file_key"],
            "figma_file_url": row["figma_file_url"],
            "config": config,
        }

    def _run_row_to_dict(self, row) -> dict:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "template_set_id": row["template_set_id"],
            "template_display_name": row["template_display_name"],
            "headline": row["headline"],
            "subline": row["subline"],
            "button_text": row["button_text"],
            "original_image_name": row["original_image_name"],
            "stored_image_name": row["stored_image_name"],
            "image_mime_type": row["image_mime_type"],
            "image_width_px": row["image_width_px"],
            "image_height_px": row["image_height_px"],
            "image_size_bytes": row["image_size_bytes"],
            "status": row["status"],
            "error_message": row["error_message"],
            "export_artifact_path": row["export_artifact_path"],
            "plugin_payload_path": row["plugin_payload_path"],
            "created_at": row["created_at"],
        }

    def _normalize_fields(self, headline: str, subline: str, button_text: str) -> dict[str, str]:
        return {
            "headline": headline.strip(),
            "subline": subline.strip(),
            "button_text": button_text.strip(),
        }

    def _inspect_image(self, image: UploadedBannerImage, template: dict) -> BannerImageDetails:
        if not image.body:
            raise BannerError("Please upload an image file.", field_errors={"image_upload": "Please upload an image file."})

        config = template["config"]
        max_size = int(config["max_file_size_bytes"])
        if len(image.body) > max_size:
            raise BannerError(
                f"Image must be {max_size // (1024 * 1024)} MB or smaller.",
                field_errors={"image_upload": "The uploaded image is too large."},
            )

        try:
            with Image.open(io.BytesIO(image.body)) as opened:
                mime_type = Image.MIME.get(opened.format or "", "")
                width_px, height_px = opened.size
        except Exception as exc:
            raise BannerError("The uploaded file is not a supported image.") from exc

        allowed = set(config["allowed_mime_types"])
        if mime_type not in allowed:
            raise BannerError("Only PNG, JPEG, or WebP images are supported.", field_errors={"image_upload": "Unsupported image format."})
        if width_px < int(config["min_width_px"]) or height_px < int(config["min_height_px"]):
            raise BannerError(
                f"Image must be at least {config['min_width_px']} x {config['min_height_px']} pixels.",
                field_errors={"image_upload": "The uploaded image is too small for this banner set."},
            )

        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime_type]
        return BannerImageDetails(mime_type, width_px, height_px, len(image.body), extension)

    def validate_banner_fields(self, template_set_id: str, headline: str, subline: str, button_text: str) -> dict[str, str]:
        template = self.get_template_set(template_set_id)
        config = template["config"]
        normalized = self._normalize_fields(headline, subline, button_text)
        errors: dict[str, str] = {}
        if not normalized["headline"]:
            errors["headline"] = "Headline is required."
        elif len(normalized["headline"]) > int(config["headline_max_chars"]):
            errors["headline"] = f"Headline must be {config['headline_max_chars']} characters or fewer."
        if not normalized["subline"]:
            errors["subline"] = "Subline is required."
        elif len(normalized["subline"]) > int(config["subline_max_chars"]):
            errors["subline"] = f"Subline must be {config['subline_max_chars']} characters or fewer."
        if not normalized["button_text"]:
            errors["button_text"] = "Button text is required."
        elif len(normalized["button_text"]) > int(config["button_text_max_chars"]):
            errors["button_text"] = f"Button text must be {config['button_text_max_chars']} characters or fewer."
        return errors

    def _build_stored_image_name(self, original_filename: str, extension: str) -> str:
        stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(original_filename or "banner-image").stem).strip("-") or "banner-image"
        return f"{stem}-{uuid4().hex[:10]}.{extension}"

    def _build_plugin_payload(self, template: dict, fields: dict[str, str], stored_image_name: str, image_details: BannerImageDetails) -> dict:
        config = template["config"]
        return {
            "template_set_id": template["id"],
            "template_display_name": template["display_name"],
            "figma_file_key": template["figma_file_key"],
            "figma_file_url": template["figma_file_url"],
            "fields": fields,
            "image": {
                "stored_image_name": stored_image_name,
                "mime_type": image_details.mime_type,
                "width_px": image_details.width_px,
                "height_px": image_details.height_px,
                "size_bytes": image_details.size_bytes,
            },
            "figma_nodes": config["figma_nodes"],
            "variants": config["variants"],
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def _render_banner_exports(self, template: dict, fields: dict[str, str], image_path: Path) -> list[Path]:
        exports: list[Path] = []
        source_image = Image.open(image_path).convert("RGB")
        for variant in template["config"]["variants"]:
            canvas = Image.new("RGB", (int(variant["width"]), int(variant["height"])), "#f2f6fb")
            fitted = ImageOps.fit(source_image, canvas.size, method=Image.Resampling.LANCZOS)
            overlay = Image.new("RGBA", canvas.size, (16, 37, 66, 0))
            draw = ImageDraw.Draw(overlay)
            gradient_height = int(canvas.height * 0.58)
            for index in range(gradient_height):
                alpha = int(210 * (index / max(gradient_height, 1)))
                draw.rectangle((0, canvas.height - gradient_height + index, canvas.width, canvas.height - gradient_height + index + 1), fill=(18, 34, 59, alpha))
            canvas = Image.alpha_composite(fitted.convert("RGBA"), overlay)
            draw = ImageDraw.Draw(canvas)

            margin = max(32, canvas.width // 20)
            button_height = max(54, canvas.height // 10)
            button_width = min(canvas.width // 3, 320)
            button_top = canvas.height - margin - button_height
            draw.rounded_rectangle(
                (margin, button_top, margin + button_width, button_top + button_height),
                radius=button_height // 2,
                fill=(255, 212, 0, 255),
            )
            draw.text((margin + 22, button_top + 16), fields["button_text"], fill=(18, 34, 59, 255))
            draw.text((margin, margin), fields["headline"], fill=(255, 255, 255, 255))
            draw.text((margin, margin + 62), fields["subline"], fill=(232, 238, 247, 255))
            export_path = self.artifacts_dir / f"{uuid4().hex[:8]}-{variant['export_name']}"
            canvas.convert("RGB").save(export_path, format="PNG")
            exports.append(export_path)
        source_image.close()
        return exports

    def _write_export_zip(self, zip_path: Path, export_paths: list[Path], plugin_payload: dict, fields: dict[str, str]) -> None:
        manifest = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "fields": fields,
            "exports": [path.name.split("-", 1)[1] if "-" in path.name else path.name for path in export_paths],
            "plugin_payload_file": "plugin-payload.json",
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("plugin-payload.json", json.dumps(plugin_payload, indent=2))
            for path in export_paths:
                archive.write(path, arcname=path.name.split("-", 1)[1] if "-" in path.name else path.name)
