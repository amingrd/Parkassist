from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OIDCClient:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str

    def _fetch_json(self, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def discovery_document(self) -> dict[str, Any]:
        issuer = self.issuer.rstrip("/")
        return self._fetch_json(f"{issuer}/.well-known/openid-configuration")

    def build_authorization_url(self, state: str) -> str:
        config = self.discovery_document()
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "scope": "openid profile email",
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{config['authorization_endpoint']}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        config = self.discovery_document()
        payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        return self._fetch_json(
            config["token_endpoint"],
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        config = self.discovery_document()
        return self._fetch_json(
            config["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
        )


def load_oidc_profile(client: OIDCClient, code: str) -> dict[str, str]:
    token_response = client.exchange_code(code)
    access_token = token_response.get("access_token")
    if not access_token:
        raise RuntimeError("OIDC token response did not include an access token.")
    profile = client.fetch_userinfo(access_token)
    email = str(profile.get("email") or "").strip().lower()
    subject = str(profile.get("sub") or "").strip()
    name = str(profile.get("name") or profile.get("preferred_username") or email or "Employee").strip()
    if not email or not subject:
        raise RuntimeError("OIDC user profile did not include the required email/sub claims.")
    return {"email": email, "name": name, "subject": subject}


def safe_oidc_error_message(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"SSO sign-in failed ({exc.code}). Please try again or contact Platform Engineering."
    if isinstance(exc, urllib.error.URLError):
        return "SSO sign-in could not reach Okta. Please try again in a moment."
    return str(exc) or "SSO sign-in failed."
