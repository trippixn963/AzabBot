"""
Azab Discord Bot - Shared Cache Utilities
==========================================

Provides reusable TTL-based caching classes to eliminate code duplication
across services that implement similar caching patterns.

Author: John Hamwi
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Generic, Optional, Tuple, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """
    A simple TTL-based cache with automatic expiration.

    Thread-safe for single-threaded async use.
    For multi-threaded use, wrap in asyncio.Lock().
    """

    def __init__(self, ttl: timedelta, max_size: int = 100):
        """
        Initialize the TTL cache.

        Args:
            ttl: Time-to-live for cached items.
            max_size: Maximum number of items to store (LRU eviction).
        """
        self._ttl = ttl
        self._max_size = max_size
        self._cache: Dict[K, Tuple[V, datetime]] = {}

    def get(self, key: K) -> Optional[V]:
        """
        Get an item from the cache if it exists and hasn't expired.

        Args:
            key: The cache key.

        Returns:
            The cached value or None if not found/expired.
        """
        if key not in self._cache:
            return None

        value, cached_at = self._cache[key]
        if datetime.now() - cached_at > self._ttl:
            # Expired - remove and return None
            try:
                del self._cache[key]
            except KeyError:
                pass  # Already removed by another coroutine
            return None

        return value

    def set(self, key: K, value: V) -> None:
        """
        Set an item in the cache.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._evict_oldest()

        self._cache[key] = (value, datetime.now())

    def delete(self, key: K) -> bool:
        """
        Delete an item from the cache.

        Args:
            key: The cache key.

        Returns:
            True if item was deleted, False if not found.
        """
        if key in self._cache:
            try:
                del self._cache[key]
                return True
            except KeyError:
                pass  # Already removed by another coroutine
        return False

    def clear(self) -> None:
        """Clear all items from the cache."""
        self._cache.clear()

    def _evict_oldest(self) -> None:
        """Evict the oldest item from the cache."""
        if not self._cache:
            return
        try:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
        except (KeyError, ValueError):
            pass  # Cache modified by another coroutine

    def cleanup_expired(self) -> int:
        """
        Remove all expired items from the cache.

        Returns:
            Number of items removed.
        """
        now = datetime.now()
        expired_keys = [
            k for k, (_, cached_at) in self._cache.items()
            if now - cached_at > self._ttl
        ]
        removed = 0
        for key in expired_keys:
            try:
                del self._cache[key]
                removed += 1
            except KeyError:
                pass  # Already removed by another coroutine
        return removed

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: K) -> bool:
        return self.get(key) is not None


class ThreadCache(TTLCache[int, Any]):
    """
    Specialized cache for Discord thread objects.

    Commonly used across case_log, tickets, modmail, appeal services.
    Default TTL is 5 minutes with max 50 threads cached.
    """

    def __init__(
        self,
        ttl: timedelta = timedelta(minutes=5),
        max_size: int = 50,
    ):
        super().__init__(ttl=ttl, max_size=max_size)


class ForumCache:
    """
    Specialized cache for Discord forum channel with single-value TTL.

    Commonly used for caching a reference to a forum channel.
    """

    def __init__(self, ttl: timedelta = timedelta(minutes=5)):
        self._ttl = ttl
        self._forum: Any = None
        self._cached_at: Optional[datetime] = None

    def get(self) -> Any:
        """Get the cached forum if not expired."""
        if self._forum is None or self._cached_at is None:
            return None
        if datetime.now() - self._cached_at > self._ttl:
            self._forum = None
            self._cached_at = None
            return None
        return self._forum

    def set(self, forum: Any) -> None:
        """Set the cached forum."""
        self._forum = forum
        self._cached_at = datetime.now()

    def clear(self) -> None:
        """Clear the cached forum."""
        self._forum = None
        self._cached_at = None
