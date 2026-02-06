"""
AzabBot - User Lookup Cache
===========================

TTL-based cache for user lookups.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional


LOOKUP_CACHE_TTL = 60  # 1 minute cache


class LookupCache:
    """Simple TTL cache for user lookups."""

    def __init__(self):
        self._cache: dict[int, tuple[float, dict]] = {}  # user_id -> (timestamp, data)

    def get(self, user_id: int) -> Optional[dict]:
        """Get cached data if still valid."""
        if user_id not in self._cache:
            return None
        cached_at, data = self._cache[user_id]
        if time.time() - cached_at > LOOKUP_CACHE_TTL:
            try:
                del self._cache[user_id]
            except KeyError:
                pass
            return None
        return data

    def set(self, user_id: int, data: dict) -> None:
        """Cache lookup result."""
        self._cache[user_id] = (time.time(), data)

    def invalidate(self, user_id: int) -> None:
        """Remove cached data."""
        self._cache.pop(user_id, None)


# Module-level cache instance
lookup_cache = LookupCache()


__all__ = ["LookupCache", "lookup_cache", "LOOKUP_CACHE_TTL"]
