from __future__ import annotations

from parking_app.postgres_repository import PostgresRepository
from parking_app.repository import Repository


def create_repository(settings):
    database_url = settings.database_url or ""
    if database_url.startswith(("postgres://", "postgresql://")):
        return PostgresRepository(database_url, seed_demo_data=settings.seed_demo_data)
    return Repository(settings.data_dir / "parking.db", seed_demo_data=settings.seed_demo_data)
