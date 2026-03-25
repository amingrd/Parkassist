from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SecretResolver:
    region_name: str

    def _boto3(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised only in deployed environments
            raise RuntimeError("boto3 is required when fetching secrets from AWS.") from exc
        return boto3

    def parameter(self, name: str, *, decrypt: bool = True) -> str:
        boto3 = self._boto3()
        client = boto3.client("ssm", region_name=self.region_name)
        response = client.get_parameter(Name=name, WithDecryption=decrypt)
        return response["Parameter"]["Value"]

    def secret_string(self, secret_id: str) -> str:
        boto3 = self._boto3()
        client = boto3.client("secretsmanager", region_name=self.region_name)
        response = client.get_secret_value(SecretId=secret_id)
        secret_value = response.get("SecretString")
        if not secret_value:
            raise RuntimeError(f"Secret {secret_id} did not contain a SecretString payload.")
        return secret_value

    def secret_json(self, secret_id: str) -> dict[str, Any]:
        payload = self.secret_string(secret_id)
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Secret {secret_id} did not contain valid JSON.") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Secret {secret_id} must decode to a JSON object.")
        return value


def resolve_plain_or_parameter(
    plain_value: Optional[str],
    parameter_name: Optional[str],
    resolver: Optional[SecretResolver],
) -> Optional[str]:
    if plain_value:
        return plain_value
    if parameter_name:
        if resolver is None:
            raise RuntimeError(f"Cannot resolve SSM parameter {parameter_name} without a resolver.")
        return resolver.parameter(parameter_name)
    return None


def build_postgres_dsn_from_secret(secret_payload: dict[str, Any]) -> str:
    direct_url = str(secret_payload.get("url") or secret_payload.get("database_url") or "").strip()
    if direct_url:
        return direct_url
    username = str(secret_payload.get("username") or secret_payload.get("user") or "").strip()
    password = str(secret_payload.get("password") or "").strip()
    host = str(secret_payload.get("host") or "").strip()
    database = str(secret_payload.get("dbname") or secret_payload.get("database") or "").strip()
    port = int(secret_payload.get("port") or 5432)
    sslmode = str(secret_payload.get("sslmode") or "require").strip()
    missing = [name for name, value in {"username": username, "password": password, "host": host, "database": database}.items() if not value]
    if missing:
        raise RuntimeError(f"Database secret is missing required keys: {', '.join(missing)}")
    return f"postgresql://{username}:{password}@{host}:{port}/{database}?sslmode={sslmode}"
