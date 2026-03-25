import unittest

from parking_app.auth import (
    clear_session_cookie,
    create_oidc_state,
    make_session_cookie,
    make_state_cookie,
    parse_state_cookie,
    parse_user_cookie,
)


class AuthCookieTests(unittest.TestCase):
    def test_session_cookie_round_trip(self) -> None:
        cookie = make_session_cookie(42, "test-secret")
        self.assertEqual(parse_user_cookie(cookie, "test-secret"), 42)

    def test_session_cookie_rejects_tampering(self) -> None:
        cookie = make_session_cookie(42, "test-secret")
        name, value = cookie.split("=", 1)
        encoded_payload, signature = value.split(".", 1)
        tampered_signature = ("a" if signature[0] != "a" else "b") + signature[1:]
        tampered = f"{name}={encoded_payload}.{tampered_signature}"
        self.assertIsNone(parse_user_cookie(tampered, "test-secret"))

    def test_state_cookie_round_trip(self) -> None:
        state = create_oidc_state()
        cookie = make_state_cookie(state, "state-secret")
        self.assertEqual(parse_state_cookie(cookie, "state-secret"), state)

    def test_cleared_session_cookie_is_invalid(self) -> None:
        cookie = clear_session_cookie()
        self.assertIsNone(parse_user_cookie(cookie, "test-secret"))


if __name__ == "__main__":
    unittest.main()
