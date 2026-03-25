from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from parking_app.auth import (
    clear_session_cookie,
    clear_state_cookie,
    create_oidc_state,
    make_session_cookie,
    make_state_cookie,
    parse_state_cookie,
    parse_user_cookie,
)
from parking_app.config import Settings
from parking_app.notifications import MultiChannelNotificationSink
from parking_app.oidc import OIDCClient, load_oidc_profile, safe_oidc_error_message
from parking_app.repository_factory import create_repository
from parking_app.services import BookingError, BookingService
from parking_app.templates import admin_page, dashboard_page, login_page

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class AppContext:
    settings: Settings
    repository: object
    service: BookingService
    oidc_client: OIDCClient | None


def build_app_context() -> AppContext:
    settings = Settings.from_env(BASE_DIR)
    repository = create_repository(settings)
    notifier = MultiChannelNotificationSink(
        repository,
        settings.slack_webhook_url,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_password=settings.smtp_password,
        smtp_use_tls=settings.smtp_use_tls,
        sender_email=settings.sender_email,
        guide_url=settings.guide_url,
    )
    oidc_client = None
    if settings.is_okta_auth:
        oidc_client = OIDCClient(
            issuer=settings.okta_issuer or "",
            client_id=settings.okta_client_id or "",
            client_secret=settings.okta_client_secret or "",
            redirect_uri=settings.okta_redirect_uri or "",
        )
    return AppContext(
        settings=settings,
        repository=repository,
        service=BookingService(repository, notifier),
        oidc_client=oidc_client,
    )


APP = build_app_context()


def run() -> None:
    server = ThreadingHTTPServer((APP.settings.host, APP.settings.port), ParkingHandler)
    print(f"Parking app running on {APP.settings.base_url}")
    server.serve_forever()


class ParkingHandler(BaseHTTPRequestHandler):
    @property
    def settings(self) -> Settings:
        return APP.settings

    @property
    def repo(self):
        return APP.repository

    @property
    def service(self) -> BookingService:
        return APP.service

    @property
    def oidc_client(self) -> OIDCClient | None:
        return APP.oidc_client

    @property
    def static_dir(self) -> Path:
        return self.settings.static_dir

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/static/"):
            return self.serve_static(parsed.path.removeprefix("/static/"))
        if parsed.path in {"/health", "/healthz", "/health/liveness", "/health/readiness"}:
            return self.render_json(
                {
                    "status": "ok",
                    "probe": parsed.path,
                    "auth_mode": self.settings.auth_mode,
                    "database_backend": "postgresql" if (self.settings.database_url or "").startswith(("postgres://", "postgresql://")) else "sqlite",
                    "app_env": self.settings.app_env,
                }
            )

        params = parse_qs(parsed.query)
        flash = params.get("flash", [None])[0]
        if parsed.path in {"/login", "/register"}:
            if self.settings.is_okta_auth and parsed.path == "/register":
                return self.redirect("/login")
            return self.render_html(
                login_page(
                    mode="register" if parsed.path == "/register" else "login",
                    flash=flash,
                    auth_mode=self.settings.auth_mode,
                    okta_login_href="/auth/okta/start" if self.settings.is_okta_auth else None,
                )
            )
        if parsed.path == "/auth/okta/start":
            return self.handle_oidc_start()
        if parsed.path == "/auth/okta/callback":
            return self.handle_oidc_callback(parsed)

        current_user = self.current_user()
        if not current_user:
            return self.redirect("/login")

        if parsed.path == "/":
            return self.render_dashboard(
                current_user,
                flash,
                params.get("week", [None])[0],
                params.get("date", [None])[0],
                params.get("tab", ["booking"])[0],
                params.get("booking_mode", ["self"])[0],
            )
        if parsed.path == "/admin":
            if current_user["role"] != "admin":
                return self.redirect(
                    self.dashboard_redirect(
                        self.current_week_start().isoformat(),
                        date.today().isoformat(),
                        "booking",
                        "Admin access is required.",
                    )
                )
            return self.render_admin(current_user, flash)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            return self.handle_login()
        if parsed.path == "/register":
            return self.handle_register()
        if parsed.path == "/logout":
            return self.redirect("/login", cookie=clear_session_cookie(secure=self.settings.session_cookie_secure))

        current_user = self.current_user()
        if not current_user:
            return self.redirect("/login")

        if parsed.path == "/profile/update":
            return self.handle_profile_update(current_user)
        if parsed.path == "/bookings":
            return self.handle_create_booking(current_user)
        if parsed.path.startswith("/bookings/") and parsed.path.endswith("/cancel"):
            return self.handle_cancel_booking(current_user, int(parsed.path.split("/")[2]))
        if parsed.path == "/waitlist":
            return self.handle_join_waitlist(current_user)
        if parsed.path.startswith("/waitlist/") and parsed.path.endswith("/leave"):
            return self.handle_leave_waitlist(current_user, int(parsed.path.split("/")[2]))

        if current_user["role"] != "admin":
            return self.redirect(
                self.dashboard_redirect(
                    self.current_week_start().isoformat(),
                    date.today().isoformat(),
                    "booking",
                    "Admin access is required.",
                )
            )

        if parsed.path == "/admin/rules":
            return self.handle_update_rules(current_user)
        if parsed.path == "/admin/invite":
            return self.handle_invite_user(current_user)
        if parsed.path.startswith("/admin/users/") and parsed.path.endswith("/remove"):
            return self.handle_remove_user(current_user, int(parsed.path.split("/")[3]))
        if parsed.path.startswith("/admin/users/") and parsed.path.endswith("/role"):
            return self.handle_user_role(current_user, int(parsed.path.split("/")[3]))
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_static(self, relative_path: str) -> None:
        file_path = self.static_dir / relative_path
        if not file_path.exists():
            return self.send_error(HTTPStatus.NOT_FOUND)
        content_type = "text/plain; charset=utf-8"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif file_path.suffix == ".mp4":
            content_type = "video/mp4"
        elif file_path.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            content_type = f"image/{file_path.suffix.removeprefix('.')}".replace("jpg", "jpeg")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def current_user(self):
        user_id = parse_user_cookie(self.headers.get("Cookie"), self.settings.session_secret)
        return self.repo.get_user(user_id) if user_id else None

    def handle_login(self) -> None:
        if self.settings.is_okta_auth:
            return self.redirect("/login?flash=" + self.quote_message("Use Okta to sign in to this environment."))
        payload = self.parse_form()
        user = self.repo.authenticate_user(payload.get("email", "").strip().lower(), payload.get("password", ""))
        if not user:
            return self.redirect("/login?flash=" + self.quote_message("Invalid email or password."))
        self.repo.log_audit(user["id"], "login", f"user={user['email']} auth=local")
        return self.redirect(
            "/",
            cookie=make_session_cookie(
                user["id"],
                self.settings.session_secret,
                secure=self.settings.session_cookie_secure,
            ),
        )

    def handle_register(self) -> None:
        if self.settings.is_okta_auth:
            return self.redirect("/login?flash=" + self.quote_message("Registration is handled through Okta in this environment."))
        payload = self.parse_form()
        name = payload.get("name", "").strip()
        email = payload.get("email", "").strip().lower()
        if not name or "@" not in email:
            return self.redirect("/register?flash=" + self.quote_message("Please enter a valid name and email address."))
        if email != payload.get("confirm_email", "").strip().lower():
            return self.redirect("/register?flash=" + self.quote_message("The email confirmation does not match."))
        password = payload.get("password", "")
        if password != payload.get("confirm_password", "") or len(password) < 8:
            return self.redirect("/register?flash=" + self.quote_message("Passwords must match and contain at least 8 characters."))
        if self.repo.get_user_by_email(email):
            return self.redirect("/login?flash=" + self.quote_message("That email already exists. Please log in instead."))
        user = self.repo.create_user(name, email, password)
        self.repo.log_audit(user["id"], "register", f"user={user['email']} auth=local")
        return self.redirect(
            "/",
            cookie=make_session_cookie(
                user["id"],
                self.settings.session_secret,
                secure=self.settings.session_cookie_secure,
            ),
        )

    def handle_oidc_start(self) -> None:
        if not self.settings.is_okta_auth or self.oidc_client is None:
            return self.redirect("/login")
        state = create_oidc_state()
        auth_url = self.oidc_client.build_authorization_url(state)
        return self.redirect(
            auth_url,
            cookie=make_state_cookie(
                state,
                self.settings.session_secret,
                secure=self.settings.session_cookie_secure,
            ),
        )

    def handle_oidc_callback(self, parsed) -> None:
        if not self.settings.is_okta_auth or self.oidc_client is None:
            return self.redirect("/login")
        params = parse_qs(parsed.query)
        state = params.get("state", [""])[0]
        code = params.get("code", [""])[0]
        expected_state = parse_state_cookie(self.headers.get("Cookie"), self.settings.session_secret)
        if not state or not code or state != expected_state:
            return self.redirect(
                "/login?flash=" + self.quote_message("Your sign-in session expired. Please try again."),
                cookie=clear_state_cookie(secure=self.settings.session_cookie_secure),
            )
        try:
            profile = load_oidc_profile(self.oidc_client, code)
            user = self.repo.find_or_create_sso_user(
                name=profile["name"],
                email=profile["email"],
                auth_provider="okta",
                external_subject=profile["subject"],
            )
            if profile["email"] in self.settings.bootstrap_admin_emails and user["role"] != "admin":
                self.repo.set_user_role(user["id"], "admin")
                user = self.repo.get_user(user["id"])
            self.repo.log_audit(user["id"], "login", f"user={user['email']} auth=okta")
            return self.redirect(
                "/",
                cookie=[
                    clear_state_cookie(secure=self.settings.session_cookie_secure),
                    make_session_cookie(
                        user["id"],
                        self.settings.session_secret,
                        secure=self.settings.session_cookie_secure,
                    ),
                ],
            )
        except Exception as exc:  # pragma: no cover - requires live OIDC integration
            return self.redirect(
                "/login?flash=" + self.quote_message(safe_oidc_error_message(exc)),
                cookie=clear_state_cookie(secure=self.settings.session_cookie_secure),
            )

    def handle_profile_update(self, current_user) -> None:
        payload = self.parse_form()
        week = payload.get("week", self.current_week_start().isoformat())
        selected_date = payload.get("date", date.today().isoformat())
        profile_image = payload.get("profile_image", "").strip()
        if self.settings.is_okta_auth or current_user["auth_provider"] == "okta":
            self.repo.update_profile_image(current_user["id"], profile_image)
            return self.redirect(self.dashboard_redirect(week, selected_date, "profile", "Profile updated."))

        name = payload.get("name", "").strip()
        email = payload.get("email", "").strip().lower()
        if not name or "@" not in email:
            return self.redirect(self.dashboard_redirect(week, selected_date, "profile", "Please enter a valid name and email."))
        existing = self.repo.get_user_by_email(email)
        if existing and existing["id"] != current_user["id"]:
            return self.redirect(self.dashboard_redirect(week, selected_date, "profile", "That email is already used by another account."))
        self.repo.update_user_profile(current_user["id"], name, email, profile_image)
        return self.redirect(self.dashboard_redirect(week, selected_date, "profile", "Profile updated."))

    def handle_create_booking(self, current_user) -> None:
        payload = self.parse_form()
        selected_date = payload.get("selected_date", date.today().isoformat())
        week = payload.get("week", self.current_week_start().isoformat())
        booking_mode = payload.get("booking_mode", "self")
        try:
            self.service.create_booking(
                actor_user_id=current_user["id"],
                target_user_id=current_user["id"],
                booking_date_str=payload.get("booking_date", ""),
                requested_spot_id=self.parse_int(payload.get("spot_id")),
                vehicle_height_cm=self.vehicle_height_value(payload.get("vehicle_size")),
                policy_acknowledged=payload.get("policy_acknowledged") == "yes",
                half_day=payload.get("half_day") == "yes",
                guest_name=payload.get("guest_name", "").strip(),
                guest_email=payload.get("guest_email", "").strip().lower(),
            )
            return self.redirect(self.dashboard_redirect(week, selected_date, "history", "Parking reserved successfully.", booking_mode))
        except BookingError as exc:
            return self.redirect(self.dashboard_redirect(week, selected_date, "booking", str(exc), booking_mode))

    def handle_cancel_booking(self, current_user, booking_id: int) -> None:
        payload = self.parse_form()
        selected_date = payload.get("selected_date", date.today().isoformat())
        week = payload.get("week", self.current_week_start().isoformat())
        booking = self.repo.get_booking(booking_id)
        if not booking:
            return self.redirect(self.dashboard_redirect(week, selected_date, "history", "Booking not found."))
        if current_user["role"] != "admin" and booking["user_id"] != current_user["id"]:
            return self.redirect(self.dashboard_redirect(week, selected_date, "history", "You can only cancel your own booking."))
        try:
            self.service.cancel_booking(
                current_user["id"],
                booking_id,
                channel_notice_sent=True,
                is_sick=payload.get("is_sick") == "yes",
                is_admin=current_user["role"] == "admin",
            )
            return self.redirect(self.dashboard_redirect(week, selected_date, "history", "Booking cancelled."))
        except BookingError as exc:
            return self.redirect(self.dashboard_redirect(week, selected_date, "history", str(exc)))

    def handle_join_waitlist(self, current_user) -> None:
        payload = self.parse_form()
        selected_date = payload.get("selected_date", date.today().isoformat())
        week = payload.get("week", self.current_week_start().isoformat())
        try:
            self.service.join_waitlist(
                current_user["id"],
                current_user["id"],
                payload.get("booking_date", ""),
                vehicle_height_cm=self.vehicle_height_value(payload.get("vehicle_size")),
            )
            return self.redirect(self.dashboard_redirect(week, selected_date, "booking", "You joined the waitlist."))
        except BookingError as exc:
            return self.redirect(self.dashboard_redirect(week, selected_date, "booking", str(exc)))

    def handle_leave_waitlist(self, current_user, entry_id: int) -> None:
        payload = self.parse_form()
        selected_date = payload.get("selected_date", date.today().isoformat())
        week = payload.get("week", self.current_week_start().isoformat())
        self.service.leave_waitlist(current_user["id"], entry_id)
        return self.redirect(self.dashboard_redirect(week, selected_date, "booking", "You left the waitlist."))

    def handle_update_rules(self, current_user) -> None:
        payload = self.parse_form()
        self.repo.update_rules(int(payload["max_days_per_week"]), int(payload["max_consecutive_days"]), int(payload["booking_window_days"]))
        self.repo.log_audit(current_user["id"], "rules_updated", "Updated booking rules")
        return self.redirect("/admin?flash=" + self.quote_message("Rules updated."))

    def handle_invite_user(self, current_user) -> None:
        payload = self.parse_form()
        name = payload.get("name", "").strip()
        email = payload.get("email", "").strip().lower()
        temp_password = payload.get("password", "").strip() or "parking123"
        if not name or "@" not in email:
            return self.redirect("/admin?flash=" + self.quote_message("Please enter a valid name and email."))
        if self.repo.get_user_by_email(email):
            return self.redirect("/admin?flash=" + self.quote_message("That email already exists."))
        self.repo.create_user(name, email, temp_password)
        self.repo.log_audit(current_user["id"], "user_invited", f"user={email}")
        return self.redirect("/admin?flash=" + self.quote_message("Employee created."))

    def handle_remove_user(self, current_user, user_id: int) -> None:
        if user_id == current_user["id"]:
            return self.redirect("/admin?flash=" + self.quote_message("You cannot remove your own admin account."))
        self.repo.remove_user(user_id)
        self.repo.log_audit(current_user["id"], "user_removed", f"user={user_id}")
        return self.redirect("/admin?flash=" + self.quote_message("Employee removed."))

    def handle_user_role(self, current_user, user_id: int) -> None:
        payload = self.parse_form()
        role = payload.get("role", "employee")
        self.repo.set_user_role(user_id, role)
        self.repo.log_audit(current_user["id"], "user_role_changed", f"user={user_id} role={role}")
        return self.redirect("/admin?flash=" + self.quote_message("User role updated."))

    def render_dashboard(
        self,
        current_user,
        flash: str | None,
        week_value: str | None,
        selected_date_value: str | None,
        active_tab: str,
        booking_mode: str,
    ) -> None:
        week_start = self.parse_week(week_value)
        selected_date = selected_date_value or week_start.isoformat()
        if not (week_start <= datetime.strptime(selected_date, "%Y-%m-%d").date() <= week_start + timedelta(days=6)):
            selected_date = week_start.isoformat()
        if booking_mode not in {"self", "guest"}:
            booking_mode = "self"

        week_cells = self.build_week_cells(current_user["id"], week_start, selected_date)
        available_spots = self.repo.list_available_spots(selected_date)
        total_spots = len([spot for spot in self.repo.list_spots() if spot["is_active"]])
        selected_height = None
        hidden_spots = self.repo.list_unavailable_spots_for_vehicle(selected_date, selected_height)
        day_bookings = self.repo.list_bookings_for_date(selected_date)
        booked_spots_count = len(day_bookings)
        booking_map = {row["spot_label"]: row for row in day_bookings}
        spot_map = []
        for spot in self.repo.list_spots():
            booking = booking_map.get(spot["label"])
            booked_user = self.repo.get_user(booking["user_id"]) if booking else None
            spot_map.append(
                {
                    "label": spot["label"],
                    "kind": self.spot_kind_label(spot),
                    "status": "booked" if booking else "available",
                    "state": "Booked" if booking else "Available",
                    "booked_by_name": booking["booking_name"] if booking else "",
                    "booked_by_image": booked_user["profile_image"] if booked_user else "",
                    "detail": booking["booking_name"] if booking else "",
                }
            )

        own_bookings = []
        booking_rows = sorted(
            self.repo.list_bookings_for_user(current_user["id"]),
            key=lambda row: (
                0 if row["status"] == "active" else 1,
                row["booking_date"] if row["status"] == "active" else f"z{row['booking_date']}",
            ),
        )
        for row in booking_rows:
            action_html = ""
            if row["status"] == "active":
                action_html = (
                    f"<form method='post' action='/bookings/{row['id']}/cancel' class='history-actions'>"
                    f"<input type='hidden' name='selected_date' value='{selected_date}'>"
                    f"<input type='hidden' name='week' value='{week_start.isoformat()}'>"
                    "<button class='ghost-button' type='submit'>Cancel</button>"
                    "</form>"
                )
            own_bookings.append(
                {
                    "formatted_date": self.format_date(row["booking_date"]),
                    "spot_label": row["spot_label"],
                    "duration_label": "Half day" if row["half_day"] else "Full day",
                    "status_label": "Active" if row["status"] == "active" else "Cancelled",
                    "booking_for_label": row["guest_name"] if row["guest_name"] else "You",
                    "is_active": row["status"] == "active",
                    "action_html": action_html,
                }
            )

        selected_booking = next(
            (
                row
                for row in self.repo.list_bookings_for_user(current_user["id"])
                if row["booking_date"] == selected_date and row["status"] == "active"
            ),
            None,
        )
        waitlist_entry = self.repo.find_active_waitlist_entry(current_user["id"], selected_date)
        garage_video_available = (self.static_dir / "assets" / "guide" / "garage-guide.mp4").exists()
        self.render_html(
            dashboard_page(
                current_user=current_user,
                week_label=f"{self.format_date(week_start.isoformat())} - {self.format_date((week_start + timedelta(days=6)).isoformat())}",
                prev_week_href="/?" + urlencode({"week": (week_start - timedelta(days=7)).isoformat(), "date": (week_start - timedelta(days=7)).isoformat(), "tab": active_tab}),
                next_week_href="/?" + urlencode({"week": (week_start + timedelta(days=7)).isoformat(), "date": (week_start + timedelta(days=7)).isoformat(), "tab": active_tab}),
                week_cells=week_cells,
                selected_date=selected_date,
                selected_day_summary=f"{len(available_spots)} of {total_spots} spots available.",
                booked_spots_count=booked_spots_count,
                selected_booking=selected_booking,
                waitlist_entry=waitlist_entry,
                spot_map=spot_map,
                day_booking_rows=[],
                compatible_spots=available_spots,
                own_bookings=own_bookings,
                flash=flash,
                active_tab=active_tab,
                booking_mode=booking_mode,
                show_waitlist=len(available_spots) == 0,
                hidden_spots=hidden_spots,
                current_week=week_start.isoformat(),
                garage_video_available=garage_video_available,
                formatted_selected_date=self.format_date(selected_date),
                auth_mode=self.settings.auth_mode,
            )
        )

    def render_admin(self, current_user, flash: str | None) -> None:
        self.render_html(
            admin_page(
                current_user=current_user,
                rules=self.repo.get_rules(),
                spots=self.repo.list_spots(),
                users=self.repo.list_users(),
                bookings=self.repo.list_all_active_bookings(),
                waitlist_entries=self.repo.list_all_active_waitlist_entries(),
                overrides=self.repo.list_overrides(),
                notifications=self.repo.list_notification_events(),
                audit_entries=self.repo.list_audit_log(),
                flash=flash,
            )
        )

    def build_week_cells(self, user_id: int, week_start: date, selected_date: str) -> list[dict[str, str | bool]]:
        today = date.today()
        rules = self.repo.get_rules()
        latest = today + timedelta(days=max(rules["booking_window_days"] - 1, 0))
        active_spots = len([spot for spot in self.repo.list_spots() if spot["is_active"]])
        cells = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            free = len(self.repo.list_available_spots(day.isoformat())) if day.weekday() < 5 else 0
            own_booking = self.repo.get_user_booking_for_date(user_id, day.isoformat())
            bookable = day.weekday() < 5 and today <= day <= latest
            if day.weekday() >= 5:
                state = "Weekend"
                hover_note = "Weekend spaces are not bookable in the tool. If needed, the spots can still be used over the weekend."
            elif day < today or day > latest:
                state = "Outside booking window"
                hover_note = "Bookings are only available for the current work week window."
            else:
                state = f"{free}/{active_spots} free"
                hover_note = ""
            cells.append(
                {
                    "date": day.isoformat(),
                    "week": week_start.isoformat(),
                    "selected": day.isoformat() == selected_date,
                    "dimmed": not (today <= day <= latest),
                    "bookable": bookable,
                    "weekday": day.strftime("%a"),
                    "day_number": str(day.day),
                    "date_label": day.strftime("%b"),
                    "state": state,
                    "meta": "Your booking" if own_booking else ("Full" if free == 0 and day.weekday() < 5 else ""),
                    "fill_width": "0%" if active_spots == 0 else f"{int(((active_spots - free) / active_spots) * 100)}%",
                    "hover_note": hover_note,
                }
            )
        return cells

    def spot_kind_label(self, spot) -> str:
        if spot["kind"] == "elevator-bottom":
            return "Lower double-parker"
        if spot["kind"] == "elevator-top":
            return "Upper double-parker"
        return "Standard"

    def current_week_start(self) -> date:
        today = date.today()
        return today - timedelta(days=today.weekday())

    def parse_week(self, value: str | None) -> date:
        if value:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
                return parsed - timedelta(days=parsed.weekday())
            except ValueError:
                pass
        return self.current_week_start()

    def format_date(self, value: str) -> str:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")

    def vehicle_height_value(self, selection: str | None) -> int | None:
        mapping = {"small": 149, "medium": 166, "large": 176}
        return mapping.get(selection or "")

    def parse_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(raw).items()}

    def parse_int(self, value: str | None) -> int | None:
        try:
            return int(value) if value else None
        except ValueError:
            return None

    def render_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def render_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str, cookie: str | list[str] | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if cookie:
            if isinstance(cookie, list):
                for item in cookie:
                    self.send_header("Set-Cookie", item)
            else:
                self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def quote_message(self, message: str) -> str:
        return urlencode({"flash": message}).split("=", 1)[1]

    def dashboard_redirect(self, week: str, selected_date: str, tab: str, message: str, booking_mode: str | None = None) -> str:
        params = {"week": week, "date": selected_date, "tab": tab, "flash": message}
        if booking_mode:
            params["booking_mode"] = booking_mode
        return "/?" + urlencode(params)

    def log_message(self, format: str, *args) -> None:
        payload = {
            "event": "http_request",
            "client": self.address_string(),
            "request_line": self.requestline,
            "message": format % args if args else format,
        }
        print(json.dumps(payload), file=sys.stderr)
