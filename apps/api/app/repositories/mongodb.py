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
    # The MongoDB host is remote and shared (kgweb.roardata.cn:37017). After
    # idle, the network/NAT reaps the TCP socket; the driver's next read then
    # hangs on a dead socket until socketTimeoutMS fires _OperationCancelled
    # (an AutoReconnect subclass). maxIdleTimeMS retires idle connections
    # client-side before the server/NAT does, retryReads/retryWrites let the
    # driver transparently re-run on a fresh socket, and the larger
    # socketTimeoutMS avoids false cancellations on a momentarily slow hop.
    return MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000,
        maxIdleTimeMS=30000,
        retryReads=True,
        retryWrites=True,
    )


def get_mongo_database() -> Database:
    client = get_mongo_client()
    settings = get_settings()
    return client[settings.mongodb_database]
