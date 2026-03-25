from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from http import cookies
from typing import Optional

SESSION_COOKIE_NAME = "parking_session"
OIDC_STATE_COOKIE_NAME = "parking_oauth_state"


@dataclass(frozen=True)
class SessionUser:
    id: int
    name: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _build_signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_payload(*parts: str) -> str:
    return base64.urlsafe_b64encode("|".join(parts).encode("utf-8")).decode("ascii")


def _decode_payload(value: str) -> Optional[list[str]]:
    try:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8").split("|")
    except (ValueError, UnicodeDecodeError):
        return None


def _parse_signed_cookie(cookie_header: Optional[str], cookie_name: str, secret: str) -> Optional[list[str]]:
    if not cookie_header:
        return None
    jar = cookies.SimpleCookie()
    jar.load(cookie_header)
    morsel = jar.get(cookie_name)
    if morsel is None:
        return None
    value = morsel.value
    if "." not in value:
        return None
    encoded_payload, signature = value.rsplit(".", 1)
    expected = _build_signature(encoded_payload, secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return _decode_payload(encoded_payload)


def parse_user_cookie(cookie_header: Optional[str], secret: str) -> Optional[int]:
    payload = _parse_signed_cookie(cookie_header, SESSION_COOKIE_NAME, secret)
    if not payload or len(payload) < 2:
        return None
    user_id, issued_at = payload[:2]
    try:
        int(issued_at)
        return int(user_id)
    except ValueError:
        return None


def make_session_cookie(
    user_id: int,
    secret: str,
    *,
    max_age: int = 60 * 60 * 12,
    secure: bool = False,
) -> str:
    issued_at = str(int(time.time()))
    encoded_payload = _encode_payload(str(user_id), issued_at)
    signature = _build_signature(encoded_payload, secret)
    jar = cookies.SimpleCookie()
    jar[SESSION_COOKIE_NAME] = f"{encoded_payload}.{signature}"
    jar[SESSION_COOKIE_NAME]["path"] = "/"
    jar[SESSION_COOKIE_NAME]["httponly"] = True
    jar[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    jar[SESSION_COOKIE_NAME]["max-age"] = max_age
    if secure:
        jar[SESSION_COOKIE_NAME]["secure"] = True
    return jar.output(header="").strip()


def clear_session_cookie(*, secure: bool = False) -> str:
    jar = cookies.SimpleCookie()
    jar[SESSION_COOKIE_NAME] = ""
    jar[SESSION_COOKIE_NAME]["path"] = "/"
    jar[SESSION_COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    jar[SESSION_COOKIE_NAME]["max-age"] = 0
    if secure:
        jar[SESSION_COOKIE_NAME]["secure"] = True
    return jar.output(header="").strip()


def create_oidc_state() -> str:
    return secrets.token_urlsafe(24)


def make_state_cookie(
    state: str,
    secret: str,
    *,
    max_age: int = 600,
    secure: bool = False,
) -> str:
    encoded_payload = _encode_payload(state)
    signature = _build_signature(encoded_payload, secret)
    jar = cookies.SimpleCookie()
    jar[OIDC_STATE_COOKIE_NAME] = f"{encoded_payload}.{signature}"
    jar[OIDC_STATE_COOKIE_NAME]["path"] = "/"
    jar[OIDC_STATE_COOKIE_NAME]["httponly"] = True
    jar[OIDC_STATE_COOKIE_NAME]["samesite"] = "Lax"
    jar[OIDC_STATE_COOKIE_NAME]["max-age"] = max_age
    if secure:
        jar[OIDC_STATE_COOKIE_NAME]["secure"] = True
    return jar.output(header="").strip()


def parse_state_cookie(cookie_header: Optional[str], secret: str) -> Optional[str]:
    payload = _parse_signed_cookie(cookie_header, OIDC_STATE_COOKIE_NAME, secret)
    if not payload:
        return None
    return payload[0]


def clear_state_cookie(*, secure: bool = False) -> str:
    jar = cookies.SimpleCookie()
    jar[OIDC_STATE_COOKIE_NAME] = ""
    jar[OIDC_STATE_COOKIE_NAME]["path"] = "/"
    jar[OIDC_STATE_COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    jar[OIDC_STATE_COOKIE_NAME]["max-age"] = 0
    if secure:
        jar[OIDC_STATE_COOKIE_NAME]["secure"] = True
    return jar.output(header="").strip()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash or ":" not in stored_hash:
        return False
    salt_hex, digest_hex = stored_hash.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return hmac.compare_digest(actual, expected)
