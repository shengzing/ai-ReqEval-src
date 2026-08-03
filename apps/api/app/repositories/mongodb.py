"""MongoDB provider utilities."""

from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from src.apps.api.app.core.config import get_settings


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MongoDB settings are incomplete. Configure MONGODB_URI or "
            "MONGODB_USER, MONGODB_PASSWORD, MONGODB_HOST, MONGODB_PORT, "
            "DATABASE_NAME, and MONGODB_AUTH_SOURCE."
        )
    return MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=5000,
    )


def get_mongo_database() -> Database:
    client = get_mongo_client()
    settings = get_settings()
    return client[settings.mongodb_database]
