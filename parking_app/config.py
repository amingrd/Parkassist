from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from parking_app.secrets import SecretResolver, build_postgres_dsn_from_secret, resolve_plain_or_parameter


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    static_dir: Path
    data_dir: Path
    app_env: str
    host: str
    port: int
    base_url: str
    aws_region: str
    auth_mode: str
    session_secret: str
    session_cookie_secure: bool
    database_url: Optional[str]
    seed_demo_data: bool
    slack_webhook_url: Optional[str]
    smtp_host: Optional[str]
    smtp_port: int
    smtp_username: Optional[str]
    smtp_password: Optional[str]
    smtp_use_tls: bool
    sender_email: Optional[str]
    guide_url: Optional[str]
    okta_issuer: Optional[str]
    okta_client_id: Optional[str]
    okta_client_secret: Optional[str]
    okta_redirect_uri: Optional[str]
    bootstrap_admin_emails: tuple[str, ...]

    @property
    def is_local_auth(self) -> bool:
        return self.auth_mode == "local"

    @property
    def is_okta_auth(self) -> bool:
        return self.auth_mode == "okta"

    @classmethod
    def from_env(cls, base_dir: Path) -> "Settings":
        app_env = os.environ.get("APP_ENV", "local").strip().lower() or "local"
        aws_region = os.environ.get("AWS_REGION", "eu-west-1").strip() or "eu-west-1"
        resolver = SecretResolver(aws_region)

        host = os.environ.get("HOST", "127.0.0.1" if app_env == "local" else "0.0.0.0").strip() or "127.0.0.1"
        port = int(os.environ.get("PORT", "8000"))
        base_url = os.environ.get("BASE_URL", f"http://127.0.0.1:{port}" if host == "127.0.0.1" else f"http://localhost:{port}").strip()

        auth_mode = os.environ.get("AUTH_MODE", "local").strip().lower() or "local"
        if auth_mode not in {"local", "okta"}:
            raise RuntimeError("AUTH_MODE must be either 'local' or 'okta'.")

        session_secret = resolve_plain_or_parameter(
            os.environ.get("SESSION_SECRET"),
            os.environ.get("SESSION_SECRET_PARAMETER"),
            resolver,
        )
        if not session_secret:
            session_secret = "dev-session-secret"
        session_cookie_secure = _env_flag("SESSION_COOKIE_SECURE", app_env not in {"local", "development"})

        database_url = os.environ.get("DATABASE_URL", "").strip() or None
        database_secret_id = os.environ.get("DATABASE_SECRET_ID", "").strip() or None
        if not database_url and database_secret_id:
            database_url = build_postgres_dsn_from_secret(resolver.secret_json(database_secret_id))

        slack_webhook_url = resolve_plain_or_parameter(
            os.environ.get("SLACK_WEBHOOK_URL"),
            os.environ.get("SLACK_WEBHOOK_URL_PARAMETER"),
            resolver,
        )
        smtp_password = resolve_plain_or_parameter(
            os.environ.get("SMTP_PASSWORD"),
            os.environ.get("SMTP_PASSWORD_PARAMETER"),
            resolver,
        )

        okta_issuer = os.environ.get("OKTA_ISSUER", "").strip() or None
        okta_client_id = os.environ.get("OKTA_CLIENT_ID", "").strip() or None
        okta_client_secret = resolve_plain_or_parameter(
            os.environ.get("OKTA_CLIENT_SECRET"),
            os.environ.get("OKTA_CLIENT_SECRET_PARAMETER"),
            resolver,
        )
        okta_redirect_uri = os.environ.get("OKTA_REDIRECT_URI", "").strip() or None
        if auth_mode == "okta":
            missing = [name for name, value in {"OKTA_ISSUER": okta_issuer, "OKTA_CLIENT_ID": okta_client_id, "OKTA_CLIENT_SECRET": okta_client_secret}.items() if not value]
            if missing:
                raise RuntimeError(f"Okta auth mode requires: {', '.join(missing)}")
            if not okta_redirect_uri:
                okta_redirect_uri = f"{base_url.rstrip('/')}/auth/okta/callback"

        seed_demo_data = _env_flag("SEED_DEMO_DATA", app_env == "local")
        return cls(
            base_dir=base_dir,
            static_dir=base_dir / "assets" / "web",
            data_dir=base_dir / "runtime" / "data",
            app_env=app_env,
            host=host,
            port=port,
            base_url=base_url,
            aws_region=aws_region,
            auth_mode=auth_mode,
            session_secret=session_secret,
            session_cookie_secure=session_cookie_secure,
            database_url=database_url,
            seed_demo_data=seed_demo_data,
            slack_webhook_url=slack_webhook_url,
            smtp_host=os.environ.get("SMTP_HOST"),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_username=os.environ.get("SMTP_USERNAME"),
            smtp_password=smtp_password,
            smtp_use_tls=_env_flag("SMTP_USE_TLS", True),
            sender_email=os.environ.get("EMAIL_FROM"),
            guide_url=os.environ.get("PARKING_GUIDE_URL"),
            okta_issuer=okta_issuer,
            okta_client_id=okta_client_id,
            okta_client_secret=okta_client_secret,
            okta_redirect_uri=okta_redirect_uri,
            bootstrap_admin_emails=tuple(
                value.strip().lower()
                for value in os.environ.get("BOOTSTRAP_ADMIN_EMAILS", os.environ.get("ADMIN_EMAILS", "")).split(",")
                if value.strip()
            ),
        )
