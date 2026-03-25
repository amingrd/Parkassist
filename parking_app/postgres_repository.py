from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from parking_app.auth import hash_password
from parking_app.repository import LM_SPOTS, SEED_USERS, Repository


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
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
  id BIGSERIAL PRIMARY KEY,
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
  id INTEGER PRIMARY KEY,
  max_days_per_week INTEGER NOT NULL,
  max_consecutive_days INTEGER NOT NULL,
  booking_window_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS overrides (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('weekly_limit', 'consecutive_limit', 'all_rules')),
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS bookings (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  spot_id BIGINT NOT NULL,
  booking_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active', 'cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cancelled_at TIMESTAMPTZ,
  cancelled_by_user_id BIGINT,
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
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  booking_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active', 'promoted', 'cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  promoted_booking_id BIGINT,
  vehicle_height_cm INTEGER,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (promoted_booking_id) REFERENCES bookings(id)
);

CREATE TABLE IF NOT EXISTS notification_events (
  id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  user_id BIGINT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  delivered_at TIMESTAMPTZ,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_user_id BIGINT NOT NULL,
  action TEXT NOT NULL,
  details TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_subject
ON users (auth_provider, external_subject)
WHERE external_subject <> '';
"""


def _convert_placeholders(query: str) -> str:
    return query.replace("?", "%s")


class PostgresCursorAdapter:
    def __init__(self, cursor) -> None:
        self.cursor = cursor

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class PostgresConnectionAdapter:
    def __init__(self, connection) -> None:
        self.connection = connection

    def execute(self, query: str, params: tuple | list | None = None) -> PostgresCursorAdapter:
        cursor = self.connection.cursor()
        cursor.execute(_convert_placeholders(query), tuple(params or ()))
        return PostgresCursorAdapter(cursor)

    def executemany(self, query: str, rows) -> None:
        cursor = self.connection.cursor()
        cursor.executemany(_convert_placeholders(query), rows)

    def executescript(self, script: str) -> None:
        for statement in [part.strip() for part in script.split(";") if part.strip()]:
            self.connection.cursor().execute(statement)


class PostgresRepository(Repository):
    schema_sql = POSTGRES_SCHEMA

    def __init__(self, dsn: str, *, seed_demo_data: bool = False) -> None:
        self.dsn = dsn
        self.seed_demo_data = seed_demo_data
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[PostgresConnectionAdapter]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised in deployed environments
            raise RuntimeError("psycopg is required when using PostgreSQL.") from exc

        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            yield PostgresConnectionAdapter(conn)
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(self.schema_sql)
            if conn.execute("SELECT COUNT(*) AS count FROM rule_sets").fetchone()["count"] == 0:
                conn.execute(
                    "INSERT INTO rule_sets (id, max_days_per_week, max_consecutive_days, booking_window_days) VALUES (1, 3, 2, 8)"
                )
            else:
                conn.execute("UPDATE rule_sets SET booking_window_days = 8 WHERE booking_window_days = 7")
            if conn.execute("SELECT COUNT(*) AS count FROM parking_spots").fetchone()["count"] == 0:
                conn.executemany(
                    """
                    INSERT INTO parking_spots (
                      label, zone, kind, is_active, sort_order, max_length_cm, max_width_cm, max_height_cm, max_weight_kg, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    LM_SPOTS,
                )
            if self.seed_demo_data and conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"] == 0:
                conn.executemany(
                    """
                    INSERT INTO users (
                      name, email, password_hash, role, auth_provider, external_subject, email_verified, is_banned
                    ) VALUES (?, ?, ?, ?, 'local', '', ?, ?)
                    """,
                    [(name, email, hash_password("parking123"), role, verified, banned) for name, email, role, verified, banned in SEED_USERS],
                )
            if self.seed_demo_data:
                if conn.execute("SELECT COUNT(*) AS count FROM bookings").fetchone()["count"] == 0:
                    self._seed_demo_bookings(conn)
                else:
                    self._ensure_waitlist_demo_day(conn)

    def _migrate_schema(self, conn) -> None:
        return

    def create_user(
        self,
        name: str,
        email: str,
        password: str | None,
        role: str = "employee",
        *,
        auth_provider: str = "local",
        external_subject: str = "",
    ):
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (
                  name, email, password_hash, role, auth_provider, external_subject, email_verified, is_banned
                ) VALUES (%s, %s, %s, %s, %s, %s, 1, 0)
                RETURNING id
                """,
                (name, email, hash_password(password) if password else None, role, auth_provider, external_subject),
            ).fetchone()
            return conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()

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
            row = conn.execute(
                """
                INSERT INTO bookings (
                  user_id, spot_id, booking_date, status, source, vehicle_height_cm, half_day, guest_name, guest_email
                )
                VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, spot_id, booking_date, source, vehicle_height_cm, 1 if half_day else 0, guest_name, guest_email),
            ).fetchone()
            return int(row["id"])

    def add_waitlist_entry(self, user_id: int, booking_date: str, vehicle_height_cm: Optional[int]) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO waitlist_entries (user_id, booking_date, status, vehicle_height_cm)
                VALUES (%s, %s, 'active', %s)
                RETURNING id
                """,
                (user_id, booking_date, vehicle_height_cm),
            ).fetchone()
            return int(row["id"])
