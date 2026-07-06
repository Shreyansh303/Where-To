"""SQLite-backed response cache.

Every external API call is cached under a *request signature*:
sha256 over (service name + canonical JSON of the request params). Canonical
means sorted keys and compact separators, so logically-identical requests
always collide onto the same row regardless of dict ordering.

TTL is per-service (flights/hotels ~1h to mirror SerpApi's own cache window;
places/routes ~24h since that data drifts slowly). Expired rows are treated
as misses and deleted lazily on read.

A fresh sqlite3 connection is opened per operation: this workload is a handful
of reads/writes per trip plan, and per-op connections keep the store safe to
use from FastAPI worker threads without shared-connection locking.
"""

import hashlib
import json
import sqlite3
import time
from typing import Any


def make_signature(service: str, params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{service}|{canonical}".encode()).hexdigest()


class Cache:
    def __init__(self, path: str, ttls: dict[str, int] | None = None, default_ttl: int = 3600):
        self.path = path
        self.ttls = ttls or {}
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS responses (
                       signature TEXT PRIMARY KEY,
                       service   TEXT NOT NULL,
                       payload   TEXT NOT NULL,
                       created_at REAL NOT NULL
                   )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ttl(self, service: str) -> int:
        return self.ttls.get(service, self.default_ttl)

    def get(self, service: str, params: dict[str, Any]) -> Any | None:
        sig = make_signature(service, params)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM responses WHERE signature = ?", (sig,)
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            payload, created_at = row
            if time.time() - created_at > self._ttl(service):
                conn.execute("DELETE FROM responses WHERE signature = ?", (sig,))
                self.misses += 1
                return None
        self.hits += 1
        return json.loads(payload)

    def set(self, service: str, params: dict[str, Any], payload: Any) -> None:
        sig = make_signature(service, params)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (signature, service, payload, created_at)"
                " VALUES (?, ?, ?, ?)",
                (sig, service, json.dumps(payload), time.time()),
            )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM responses")
