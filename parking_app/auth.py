from __future__ import annotations

from dataclasses import dataclass
from http import cookies
import hashlib
import hmac
import os
from typing import Optional

COOKIE_NAME = "parking_user_id"


@dataclass(frozen=True)
class SessionUser:
    id: int
    name: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def parse_user_cookie(cookie_header: Optional[str]) -> Optional[int]:
    if not cookie_header:
        return None
    jar = cookies.SimpleCookie()
    jar.load(cookie_header)
    morsel = jar.get(COOKIE_NAME)
    if morsel is None:
        return None
    try:
        return int(morsel.value)
    except ValueError:
        return None


def make_session_cookie(user_id: int) -> str:
    jar = cookies.SimpleCookie()
    jar[COOKIE_NAME] = str(user_id)
    jar[COOKIE_NAME]["path"] = "/"
    jar[COOKIE_NAME]["httponly"] = True
    jar[COOKIE_NAME]["samesite"] = "Lax"
    return jar.output(header="").strip()


def clear_session_cookie() -> str:
    jar = cookies.SimpleCookie()
    jar[COOKIE_NAME] = ""
    jar[COOKIE_NAME]["path"] = "/"
    jar[COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    jar[COOKIE_NAME]["max-age"] = 0
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
