from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, Optional

from parking_app.auth import hash_password, verify_password


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  role TEXT NOT NULL CHECK(role IN ('admin', 'employee')),
  auth_provider TEXT NOT NULL DEFAULT 'local',
  external_subject TEXT NOT NULL DEFAULT '',
  email_verified INTEGER NOT NULL DEFAULT 0,
  is_banned INTEGER NOT NULL DEFAULT 0,
  profile_image TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS parking_spots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL UNIQUE,
  zone TEXT NOT NULL DEFAULT 'UG2',
  kind TEXT NOT NULL DEFAULT 'standard',
  is_active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  max_length_cm INTEGER,
  max_width_cm INTEGER,
  max_height_cm INTEGER,
  max_weight_kg INTEGER,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rule_sets (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  max_days_per_week INTEGER NOT NULL,
  max_consecutive_days INTEGER NOT NULL,
  booking_window_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS overrides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('weekly_limit', 'consecutive_limit', 'all_rules')),
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  spot_id INTEGER NOT NULL,
  booking_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active', 'cancelled')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cancelled_at TEXT,
  cancelled_by_user_id INTEGER,
  source TEXT NOT NULL DEFAULT 'web',
  vehicle_height_cm INTEGER,
  channel_notice_sent INTEGER NOT NULL DEFAULT 0,
  half_day INTEGER NOT NULL DEFAULT 0,
  guest_name TEXT NOT NULL DEFAULT '',
  guest_email TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (spot_id) REFERENCES parking_spots(id),
  FOREIGN KEY (cancelled_by_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS waitlist_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  booking_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active', 'promoted', 'cancelled')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  promoted_booking_id INTEGER,
  vehicle_height_cm INTEGER,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (promoted_booking_id) REFERENCES bookings(id)
);

CREATE TABLE IF NOT EXISTS notification_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  delivered_at TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  details TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_user_id) REFERENCES users(id)
);
"""


SEED_USERS = [
    ("Alex Morgan", "alex.morgan@example.com", "admin", 1, 0),
    ("Jamie Chen", "jamie.chen@example.com", "employee", 1, 0),
    ("Taylor Singh", "taylor.singh@example.com", "employee", 1, 0),
    ("Morgan Reed", "morgan.reed@example.com", "employee", 1, 0),
]

LM_SPOTS = [
    ("P5", "UG2", "elevator-bottom", 1, 5, 500, 190, 165, 2000, "Lower double-parker. Max height 165 cm."),
    ("P6", "UG2", "elevator-top", 1, 6, 500, 190, 150, 2000, "Upper double-parker. Max height 150 cm."),
    ("P14", "UG2", "standard", 1, 14, None, None, None, None, ""),
    ("P15", "UG2", "standard", 1, 15, None, None, None, None, ""),
    ("P16", "UG2", "standard", 1, 16, None, None, None, None, ""),
    ("P17", "UG2", "standard", 1, 17, None, None, None, None, ""),
    ("P18", "UG2", "standard", 1, 18, None, None, None, None, ""),
    ("P19", "UG2", "standard", 1, 19, None, None, None, None, ""),
    ("P20", "UG2", "standard", 1, 20, None, None, None, None, ""),
    ("P21", "UG2", "standard", 1, 21, None, None, None, None, ""),
]


class Repository:
    def __init__(self, db_path: Path, *, seed_demo_data: bool = True) -> None:
        self.db_path = db_path
        self.seed_demo_data = seed_demo_data
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._migrate_schema(conn)
            if conn.execute("SELECT COUNT(*) AS count FROM rule_sets").fetchone()["count"] == 0:
                conn.execute(
                    "INSERT INTO rule_sets (id, max_days_per_week, max_consecutive_days, booking_window_days) VALUES (1, 3, 2, 8)"
                )
            else:
                conn.execute("UPDATE rule_sets SET booking_window_days = 8 WHERE booking_window_days = 7")
            if conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"] == 0:
                conn.executemany(
                    """
                    INSERT INTO users (
                      name, email, password_hash, role, auth_provider, external_subject, email_verified, is_banned
                    ) VALUES (?, ?, ?, ?, 'local', '', ?, ?)
                    """,
                    [(name, email, hash_password("parking123"), role, verified, banned) for name, email, role, verified, banned in SEED_USERS],
                )
            else:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE password_hash IS NULL AND auth_provider = 'local'",
                    (hash_password("parking123"),),
                )
                conn.execute("UPDATE parking_spots SET notes = '' WHERE label IN ('P14','P15','P16','P17','P18','P19','P20','P21')")
                conn.execute(
                    """
                    UPDATE parking_spots
                    SET notes = CASE
                      WHEN label = 'P5' THEN 'Lower double-parker. Max height 165 cm.'
                      WHEN label = 'P6' THEN 'Upper double-parker. Max height 150 cm.'
                      ELSE notes
                    END
                    WHERE label IN ('P5', 'P6')
                    """
                )
            if self._needs_spot_reset(conn):
                conn.execute("DELETE FROM waitlist_entries")
                conn.execute("DELETE FROM bookings")
                conn.execute("DELETE FROM parking_spots")
            if conn.execute("SELECT COUNT(*) AS count FROM parking_spots").fetchone()["count"] == 0:
                conn.executemany(
                    """
                    INSERT INTO parking_spots (
                      label, zone, kind, is_active, sort_order, max_length_cm, max_width_cm, max_height_cm, max_weight_kg, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    LM_SPOTS,
                )
            if self.seed_demo_data:
                if conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"] == 0:
                    self._seed_demo_bookings(conn)
                else:
                    self._ensure_waitlist_demo_day(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        for name, definition in {
            "password_hash": "TEXT",
            "auth_provider": "TEXT NOT NULL DEFAULT 'local'",
            "external_subject": "TEXT NOT NULL DEFAULT ''",
            "email_verified": "INTEGER NOT NULL DEFAULT 0",
            "is_banned": "INTEGER NOT NULL DEFAULT 0",
            "profile_image": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

        spot_columns = {row["name"] for row in conn.execute("PRAGMA table_info(parking_spots)").fetchall()}
        for name, definition in {
            "kind": "TEXT NOT NULL DEFAULT 'standard'",
            "sort_order": "INTEGER NOT NULL DEFAULT 0",
            "max_length_cm": "INTEGER",
            "max_width_cm": "INTEGER",
            "max_height_cm": "INTEGER",
            "max_weight_kg": "INTEGER",
            "notes": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in spot_columns:
                conn.execute(f"ALTER TABLE parking_spots ADD COLUMN {name} {definition}")

        booking_columns = {row["name"] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()}
        for name, definition in {
            "vehicle_height_cm": "INTEGER",
            "channel_notice_sent": "INTEGER NOT NULL DEFAULT 0",
            "half_day": "INTEGER NOT NULL DEFAULT 0",
            "guest_name": "TEXT NOT NULL DEFAULT ''",
            "guest_email": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in booking_columns:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {name} {definition}")

        waitlist_columns = {row["name"] for row in conn.execute("PRAGMA table_info(waitlist_entries)").fetchall()}
        if "vehicle_height_cm" not in waitlist_columns:
            conn.execute("ALTER TABLE waitlist_entries ADD COLUMN vehicle_height_cm INTEGER")

    def _needs_spot_reset(self, conn: sqlite3.Connection) -> bool:
        labels = {row["label"] for row in conn.execute("SELECT label FROM parking_spots").fetchall()}
        legacy = {"A-01", "A-02", "VIP-01", "B-01", "P5 oben", "P5 unten", "P6 oben", "P6 unten"}
        return bool(labels) and ("P14" not in labels or bool(labels & legacy))

    def _seed_demo_bookings(self, conn: sqlite3.Connection) -> None:
        today = date.today()
        workdays: list[str] = []
        cursor = today
        while len(workdays) < 3:
            if cursor.weekday() < 5:
                workdays.append(cursor.isoformat())
            cursor += timedelta(days=1)
        spot_ids = {
            row["label"]: row["id"]
            for row in conn.execute("SELECT id, label FROM parking_spots WHERE label IN ('P14', 'P15', 'P18')").fetchall()
        }
        conn.execute("INSERT INTO bookings (user_id, spot_id, booking_date, status, source) VALUES (2, ?, ?, 'active', 'seed')", (spot_ids["P14"], workdays[0]))
        conn.execute("INSERT INTO bookings (user_id, spot_id, booking_date, status, source) VALUES (3, ?, ?, 'active', 'seed')", (spot_ids["P15"], workdays[0]))
        conn.execute("INSERT INTO bookings (user_id, spot_id, booking_date, status, source) VALUES (4, ?, ?, 'active', 'seed')", (spot_ids["P18"], workdays[1]))
        self._ensure_waitlist_demo_day(conn)

    def _ensure_waitlist_demo_day(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT 1 FROM bookings WHERE source = 'seed-waitlist' LIMIT 1").fetchone()
        if existing:
            return
        target_day = date.today()
        workdays_seen = 0
        while workdays_seen < 3:
            if target_day.weekday() < 5:
                workdays_seen += 1
            if workdays_seen < 3:
                target_day += timedelta(days=1)
        spots = conn.execute("SELECT id, label FROM parking_spots WHERE is_active = 1 ORDER BY sort_order ASC").fetchall()
        owners = [2, 3, 4, 1]
        for index, spot in enumerate(spots):
            owner = owners[index % len(owners)]
            conn.execute(
                """
                INSERT INTO bookings (
                  user_id, spot_id, booking_date, status, source, guest_name, guest_email
                ) VALUES (?, ?, ?, 'active', 'seed-waitlist', ?, ?)
                """,
                (
                    owner,
                    spot["id"],
                    target_day.isoformat(),
                    f"Guest {index + 1}",
                    f"guest{index + 1}@example.com",
                ),
            )

    def list_users(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM users ORDER BY role DESC, name ASC").fetchall()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get_user_by_email(self, email: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()

    def get_user_by_subject(self, auth_provider: str, external_subject: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE auth_provider = ? AND external_subject = ?",
                (auth_provider, external_subject),
            ).fetchone()

    def create_user(
        self,
        name: str,
        email: str,
        password: str | None,
        role: str = "employee",
        *,
        auth_provider: str = "local",
        external_subject: str = "",
    ) -> sqlite3.Row:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                  name, email, password_hash, role, auth_provider, external_subject, email_verified, is_banned
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                """,
                (name, email, hash_password(password) if password else None, role, auth_provider, external_subject),
            )
            return conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()

    def authenticate_user(self, email: str, password: str) -> Optional[sqlite3.Row]:
        user = self.get_user_by_email(email)
        if user and user["auth_provider"] == "local" and verify_password(password, user["password_hash"]):
            return user
        return None

    def find_or_create_sso_user(
        self,
        *,
        name: str,
        email: str,
        auth_provider: str,
        external_subject: str,
    ) -> sqlite3.Row:
        existing_by_subject = self.get_user_by_subject(auth_provider, external_subject)
        if existing_by_subject:
            with self.connection() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET name = ?, email = ?, email_verified = 1
                    WHERE id = ?
                    """,
                    (name, email, existing_by_subject["id"]),
                )
                return conn.execute("SELECT * FROM users WHERE id = ?", (existing_by_subject["id"],)).fetchone()

        existing_by_email = self.get_user_by_email(email)
        if existing_by_email:
            with self.connection() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET name = ?, auth_provider = ?, external_subject = ?, email_verified = 1
                    WHERE id = ?
                    """,
                    (name, auth_provider, external_subject, existing_by_email["id"]),
                )
                return conn.execute("SELECT * FROM users WHERE id = ?", (existing_by_email["id"],)).fetchone()

        return self.create_user(
            name,
            email,
            None,
            auth_provider=auth_provider,
            external_subject=external_subject,
        )

    def update_profile_image(self, user_id: int, profile_image: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE users SET profile_image = ? WHERE id = ?", (profile_image, user_id))

    def update_user_profile(self, user_id: int, name: str, email: str, profile_image: str) -> sqlite3.Row:
        with self.connection() as conn:
            conn.execute(
                "UPDATE users SET name = ?, email = ?, profile_image = ? WHERE id = ?",
                (name, email, profile_image, user_id),
            )
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def set_user_role(self, user_id: int, role: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def remove_user(self, user_id: int) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM waitlist_entries WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM overrides WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM bookings WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM notification_events WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM audit_log WHERE actor_user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def get_rules(self) -> sqlite3.Row:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM rule_sets WHERE id = 1").fetchone()

    def update_rules(self, max_days_per_week: int, max_consecutive_days: int, booking_window_days: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE rule_sets SET max_days_per_week = ?, max_consecutive_days = ?, booking_window_days = ? WHERE id = 1",
                (max_days_per_week, max_consecutive_days, booking_window_days),
            )

    def list_spots(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM parking_spots ORDER BY sort_order ASC, label ASC").fetchall()

    def get_spot(self, spot_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM parking_spots WHERE id = ?", (spot_id,)).fetchone()

    def get_spot_by_label(self, label: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM parking_spots WHERE label = ?", (label,)).fetchone()

    def set_spot_active(self, spot_id: int, is_active: bool) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE parking_spots SET is_active = ? WHERE id = ?", (1 if is_active else 0, spot_id))

    def list_available_spots(self, booking_date: str, vehicle_height_cm: Optional[int] = None) -> list[sqlite3.Row]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT s.*
                FROM parking_spots s
                WHERE s.is_active = 1
                  AND s.id NOT IN (
                    SELECT b.spot_id FROM bookings b WHERE b.booking_date = ? AND b.status = 'active'
                  )
                ORDER BY s.sort_order ASC, s.label ASC
                """,
                (booking_date,),
            ).fetchall()
        if vehicle_height_cm is None:
            return rows
        return [row for row in rows if row["max_height_cm"] is None or vehicle_height_cm <= row["max_height_cm"]]

    def list_unavailable_spots_for_vehicle(self, booking_date: str, vehicle_height_cm: Optional[int]) -> list[sqlite3.Row]:
        if vehicle_height_cm is None:
            return []
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT s.*
                FROM parking_spots s
                WHERE s.is_active = 1
                  AND s.id NOT IN (
                    SELECT b.spot_id FROM bookings b WHERE b.booking_date = ? AND b.status = 'active'
                  )
                  AND s.max_height_cm IS NOT NULL
                  AND s.max_height_cm < ?
                ORDER BY s.sort_order ASC
                """,
                (booking_date, vehicle_height_cm),
            ).fetchall()

    def get_booking(self, booking_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()

    def get_user_booking_for_date(self, user_id: int, booking_date: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM bookings WHERE user_id = ? AND booking_date = ? AND status = 'active'", (user_id, booking_date)).fetchone()

    def create_booking(
        self,
        user_id: int,
        spot_id: int,
        booking_date: str,
        source: str = "web",
        vehicle_height_cm: Optional[int] = None,
        half_day: bool = False,
        guest_name: str = "",
        guest_email: str = "",
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO bookings (
                  user_id, spot_id, booking_date, status, source, vehicle_height_cm, half_day, guest_name, guest_email
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (user_id, spot_id, booking_date, source, vehicle_height_cm, 1 if half_day else 0, guest_name, guest_email),
            )
            return int(cursor.lastrowid)

    def cancel_booking(self, booking_id: int, cancelled_by_user_id: int, channel_notice_sent: bool) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE bookings
                SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP, cancelled_by_user_id = ?, channel_notice_sent = ?
                WHERE id = ? AND status = 'active'
                """,
                (cancelled_by_user_id, 1 if channel_notice_sent else 0, booking_id),
            )

    def list_bookings_for_user(self, user_id: int) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT b.*, s.label AS spot_label, s.zone AS spot_zone, s.kind AS spot_kind
                FROM bookings b JOIN parking_spots s ON s.id = b.spot_id
                WHERE b.user_id = ?
                ORDER BY b.booking_date DESC, b.created_at DESC
                """,
                (user_id,),
            ).fetchall()

    def list_bookings_for_date(self, booking_date: str) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT
                  b.*,
                  u.name AS user_name,
                  u.email AS user_email,
                  CASE
                    WHEN trim(b.guest_name) != '' THEN b.guest_name
                    ELSE u.name
                  END AS booking_name,
                  CASE
                    WHEN trim(b.guest_email) != '' THEN b.guest_email
                    ELSE u.email
                  END AS booking_email,
                  s.label AS spot_label,
                  s.zone AS spot_zone,
                  s.kind AS spot_kind
                FROM bookings b
                JOIN users u ON u.id = b.user_id
                JOIN parking_spots s ON s.id = b.spot_id
                WHERE b.booking_date = ? AND b.status = 'active'
                ORDER BY s.sort_order ASC, s.label ASC
                """,
                (booking_date,),
            ).fetchall()

    def list_active_booking_dates_for_user(self, user_id: int, start_date: str, end_date: str) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT booking_date FROM bookings WHERE user_id = ? AND status = 'active' AND booking_date BETWEEN ? AND ? ORDER BY booking_date ASC",
                (user_id, start_date, end_date),
            ).fetchall()
            return [row["booking_date"] for row in rows]

    def list_all_active_bookings(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT
                  b.*,
                  u.name AS user_name,
                  CASE
                    WHEN trim(b.guest_name) != '' THEN b.guest_name
                    ELSE u.name
                  END AS booking_name,
                  s.label AS spot_label,
                  s.zone AS spot_zone
                FROM bookings b
                JOIN users u ON u.id = b.user_id
                JOIN parking_spots s ON s.id = b.spot_id
                WHERE b.status = 'active'
                ORDER BY b.booking_date ASC, s.sort_order ASC
                """
            ).fetchall()

    def find_guest_booking_for_date(self, guest_name: str, guest_email: str, booking_date: str) -> Optional[sqlite3.Row]:
        guest_name = guest_name.strip()
        guest_email = guest_email.strip().lower()
        if not guest_name and not guest_email:
            return None
        with self.connection() as conn:
            if guest_email:
                return conn.execute(
                    """
                    SELECT * FROM bookings
                    WHERE lower(guest_email) = lower(?) AND booking_date = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (guest_email, booking_date),
                ).fetchone()
            return conn.execute(
                """
                SELECT * FROM bookings
                WHERE lower(guest_name) = lower(?) AND booking_date = ? AND status = 'active'
                LIMIT 1
                """,
                (guest_name, booking_date),
            ).fetchone()

    def list_overrides(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT o.*, u.name AS user_name FROM overrides o JOIN users u ON u.id = o.user_id ORDER BY o.start_date ASC, u.name ASC"
            ).fetchall()

    def list_active_overrides_for_date(self, user_id: int, booking_date: str) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM overrides WHERE user_id = ? AND start_date <= ? AND end_date >= ? ORDER BY created_at ASC",
                (user_id, booking_date, booking_date),
            ).fetchall()

    def create_override(self, user_id: int, start_date: str, end_date: str, scope: str, reason: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO overrides (user_id, start_date, end_date, scope, reason) VALUES (?, ?, ?, ?, ?)",
                (user_id, start_date, end_date, scope, reason),
            )

    def find_active_waitlist_entry(self, user_id: int, booking_date: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM waitlist_entries WHERE user_id = ? AND booking_date = ? AND status = 'active' ORDER BY created_at ASC LIMIT 1",
                (user_id, booking_date),
            ).fetchone()

    def add_waitlist_entry(self, user_id: int, booking_date: str, vehicle_height_cm: Optional[int]) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO waitlist_entries (user_id, booking_date, status, vehicle_height_cm) VALUES (?, ?, 'active', ?)",
                (user_id, booking_date, vehicle_height_cm),
            )
            return int(cursor.lastrowid)

    def cancel_waitlist_entry(self, entry_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE waitlist_entries SET status = 'cancelled' WHERE id = ? AND status = 'active'", (entry_id,))

    def promote_waitlist_entry(self, entry_id: int, booking_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE waitlist_entries SET status = 'promoted', promoted_booking_id = ? WHERE id = ?", (booking_id, entry_id))

    def list_waitlist_for_date(self, booking_date: str) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT w.*, u.name AS user_name
                FROM waitlist_entries w JOIN users u ON u.id = w.user_id
                WHERE w.booking_date = ? AND w.status = 'active'
                ORDER BY w.created_at ASC
                """,
                (booking_date,),
            ).fetchall()

    def list_all_active_waitlist_entries(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT w.*, u.name AS user_name
                FROM waitlist_entries w JOIN users u ON u.id = w.user_id
                WHERE w.status = 'active'
                ORDER BY w.booking_date ASC, w.created_at ASC
                """
            ).fetchall()

    def create_notification_event(self, kind: str, user_id: int, title: str, message: str, delivery_status: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO notification_events (kind, user_id, title, message, delivery_status) VALUES (?, ?, ?, ?, ?)",
                (kind, user_id, title, message, delivery_status),
            )

    def mark_latest_notification_delivered(self, user_id: int, kind: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE notification_events
                SET delivery_status = 'delivered', delivered_at = CURRENT_TIMESTAMP
                WHERE id = (
                  SELECT id FROM notification_events WHERE user_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1
                )
                """,
                (user_id, kind),
            )

    def list_notification_events(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT n.*, u.name AS user_name
                FROM notification_events n JOIN users u ON u.id = n.user_id
                ORDER BY n.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def log_audit(self, actor_user_id: int, action: str, details: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO audit_log (actor_user_id, action, details) VALUES (?, ?, ?)", (actor_user_id, action, details))

    def list_audit_log(self, limit: int = 30) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT a.*, u.name AS actor_name
                FROM audit_log a JOIN users u ON u.id = a.actor_user_id
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
