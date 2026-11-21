"""Redis Caching Layer with Transparent In-Memory Fallback.

Implements the Redis caching requirement from Project 2 technical stack:
- If REDIS_URL environment variable is provided and Redis is reachable, stores live state in Redis.
- If REDIS_URL is not configured or Redis server is not running, falls back to in-memory dictionary.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

REDIS_URL = os.environ.get("REDIS_URL")


class Cache:
    """Unified cache supporting Redis and In-Memory fallback."""

    def __init__(self):
        self._memory: dict[str, Any] = {}
        self._lock = threading.RLock()
        self.client = None
        self.is_redis = False

        if REDIS_URL:
            try:
                import redis
                self.client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
                self.client.ping()
                self.is_redis = True
            except Exception:
                self.client = None
                self.is_redis = False

    def get(self, key: str) -> Any | None:
        if self.is_redis and self.client:
            try:
                val = self.client.get(key)
                return json.loads(val) if val is not None else None
            except Exception:
                pass
        with self._lock:
            return self._memory.get(key)

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        if self.is_redis and self.client:
            try:
                payload = json.dumps(value)
                self.client.set(key, payload, ex=ex)
                return
            except Exception:
                pass
        with self._lock:
            self._memory[key] = value

    def delete(self, key: str) -> None:
        if self.is_redis and self.client:
            try:
                self.client.delete(key)
                return
            except Exception:
                pass
        with self._lock:
            self._memory.pop(key, None)

    def status(self) -> dict:
        return dict(
            backend="Redis" if self.is_redis else "In-Memory (Redis-compatible fallback)",
            connected=self.is_redis,
            redis_url=REDIS_URL if self.is_redis else None,
        )


cache = Cache()
