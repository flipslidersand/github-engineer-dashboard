"""SQLite-backed TTL cache for GitHub API responses (Issue #1).

Caching responses keeps the dashboard usable when the GitHub rate limit is
exhausted: a stale-but-present entry beats an error screen. TTL defaults to
5 minutes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Callable, Optional


class SQLiteCache:
    def __init__(
        self,
        path: str,
        ttl_seconds: int = 300,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        # check_same_thread=False: FastAPI serves requests across a threadpool;
        # a process-wide lock serializes access to this single connection.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  expires_at REAL NOT NULL"
            ")"
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value, or None if missing or expired."""
        now = self._clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, expires_at = row
            if expires_at <= now:
                self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._conn.commit()
                return None
        return json.loads(value)

    def set(self, key: str, value: Any) -> None:
        expires_at = self._clock() + self._ttl
        payload = json.dumps(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache (key, value, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "expires_at = excluded.expires_at",
                (key, payload, expires_at),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
