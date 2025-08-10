"""
Caching system for AzabBot.
Provides in-memory and persistent caching with TTL support.
"""

import asyncio
import json
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union
from functools import wraps
from dataclasses import dataclass, field
from collections import OrderedDict
import hashlib

from src.core.logger import get_logger

logger = get_logger()


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    key: str
    value: Any
    created_at: float
    ttl: Optional[float]
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl
    
    def access(self):
        """Record access to this entry."""
        self.hits += 1
        self.last_accessed = time.time()


class CacheStats:
    """Cache statistics tracker."""
    
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0
        
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "hit_rate": f"{self.hit_rate:.2%}"
        }


class LRUCache:
    """Least Recently Used cache implementation."""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self.stats = CacheStats()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            if key not in self._cache:
                self.stats.misses += 1
                return None
            
            entry = self._cache[key]
            
            # Check expiration
            if entry.is_expired:
                del self._cache[key]
                self.stats.expirations += 1
                self.stats.misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.access()
            self.stats.hits += 1
            
            return entry.value
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None
    ):
        """Set value in cache."""
        async with self._lock:
            # Remove old entry if exists
            if key in self._cache:
                del self._cache[key]
            
            # Check if we need to evict
            if len(self._cache) >= self.max_size:
                # Remove least recently used
                evicted_key = next(iter(self._cache))
                del self._cache[evicted_key]
                self.stats.evictions += 1
            
            # Add new entry
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl or self.default_ttl
            )
            self._cache[key] = entry
    
    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
            logger.log_info("Cache cleared")
    
    async def cleanup_expired(self):
        """Remove expired entries."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            
            for key in expired_keys:
                del self._cache[key]
                self.stats.expirations += 1
            
            if expired_keys:
                logger.log_debug(
                    f"Cleaned up {len(expired_keys)} expired cache entries",
                    context={"expired_count": len(expired_keys)}
                )
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            **self.stats.to_dict(),
            "size": len(self._cache),
            "max_size": self.max_size
        }


class PersistentCache:
    """Persistent cache using file storage."""
    
    def __init__(
        self,
        cache_dir: str = "cache",
        max_size: int = 10000,
        default_ttl: Optional[float] = None
    ):
        """
        Initialize persistent cache.
        
        Args:
            cache_dir: Directory for cache files
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.index_file = self.cache_dir / "index.json"
        self._index: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self.stats = CacheStats()
        
        # Load existing index
        self._load_index()
    
    def _load_index(self):
        """Load cache index from disk."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r") as f:
                    self._index = json.load(f)
            except Exception as e:
                logger.log_warning(f"Failed to load cache index: {e}")
                self._index = {}
    
    def _save_index(self):
        """Save cache index to disk."""
        try:
            with open(self.index_file, "w") as f:
                json.dump(self._index, f)
        except Exception as e:
            logger.log_error(f"Failed to save cache index: {e}")
    
    def _get_cache_path(self, key: str) -> Path:
        """Get file path for cache key."""
        # Use hash to avoid filesystem issues
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            if key not in self._index:
                self.stats.misses += 1
                return None
            
            meta = self._index[key]
            
            # Check expiration
            if meta.get("ttl"):
                if (time.time() - meta["created_at"]) > meta["ttl"]:
                    await self.delete(key)
                    self.stats.expirations += 1
                    self.stats.misses += 1
                    return None
            
            # Load from disk
            cache_path = self._get_cache_path(key)
            if not cache_path.exists():
                # Index out of sync
                del self._index[key]
                self._save_index()
                self.stats.misses += 1
                return None
            
            try:
                with open(cache_path, "rb") as f:
                    value = pickle.load(f)
                
                # Update access metadata
                self._index[key]["hits"] = meta.get("hits", 0) + 1
                self._index[key]["last_accessed"] = time.time()
                self._save_index()
                
                self.stats.hits += 1
                return value
                
            except Exception as e:
                logger.log_error(f"Failed to load cache entry: {e}")
                await self.delete(key)
                self.stats.misses += 1
                return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None
    ):
        """Set value in cache."""
        async with self._lock:
            # Check size limit
            if len(self._index) >= self.max_size:
                # Evict least recently used
                lru_key = min(
                    self._index.keys(),
                    key=lambda k: self._index[k].get("last_accessed", 0)
                )
                await self.delete(lru_key)
                self.stats.evictions += 1
            
            # Save to disk
            cache_path = self._get_cache_path(key)
            try:
                with open(cache_path, "wb") as f:
                    pickle.dump(value, f)
                
                # Update index
                self._index[key] = {
                    "created_at": time.time(),
                    "ttl": ttl or self.default_ttl,
                    "hits": 0,
                    "last_accessed": time.time()
                }
                self._save_index()
                
            except Exception as e:
                logger.log_error(f"Failed to save cache entry: {e}")
    
    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        async with self._lock:
            if key not in self._index:
                return False
            
            # Delete file
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                cache_path.unlink()
            
            # Update index
            del self._index[key]
            self._save_index()
            return True
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            # Delete all cache files
            for cache_file in self.cache_dir.glob("*.cache"):
                cache_file.unlink()
            
            # Clear index
            self._index.clear()
            self._save_index()
            logger.log_info("Persistent cache cleared")
    
    async def cleanup_expired(self):
        """Remove expired entries."""
        async with self._lock:
            current_time = time.time()
            expired_keys = []
            
            for key, meta in self._index.items():
                if meta.get("ttl"):
                    if (current_time - meta["created_at"]) > meta["ttl"]:
                        expired_keys.append(key)
            
            for key in expired_keys:
                cache_path = self._get_cache_path(key)
                if cache_path.exists():
                    cache_path.unlink()
                del self._index[key]
                self.stats.expirations += 1
            
            if expired_keys:
                self._save_index()
                logger.log_debug(
                    f"Cleaned up {len(expired_keys)} expired persistent cache entries",
                    context={"expired_count": len(expired_keys)}
                )


class CacheManager:
    """Central cache manager for the application."""
    
    def __init__(self):
        """Initialize cache manager."""
        self.memory_cache = LRUCache(max_size=1000, default_ttl=300)
        self.persistent_cache = PersistentCache(
            cache_dir="cache",
            max_size=10000,
            default_ttl=3600
        )
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start cache manager."""
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.log_info("Cache manager started")
    
    async def stop(self):
        """Stop cache manager."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.log_info("Cache manager stopped")
    
    async def _cleanup_loop(self):
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await self.memory_cache.cleanup_expired()
                await self.persistent_cache.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.log_error(f"Cache cleanup error: {e}")
    
    def get_stats(self) -> dict:
        """Get combined cache statistics."""
        return {
            "memory_cache": self.memory_cache.get_stats(),
            "persistent_cache": {
                **self.persistent_cache.stats.to_dict(),
                "size": len(self.persistent_cache._index),
                "max_size": self.persistent_cache.max_size
            }
        }


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


def cached(
    ttl: Optional[float] = None,
    key_prefix: Optional[str] = None,
    use_persistent: bool = False
):
    """
    Decorator for caching function results.
    
    Args:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache keys
        use_persistent: Use persistent cache instead of memory
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = _generate_cache_key(func, args, kwargs, key_prefix)
            
            # Get cache
            cache_manager = get_cache_manager()
            cache = (
                cache_manager.persistent_cache if use_persistent
                else cache_manager.memory_cache
            )
            
            # Check cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await cache.set(cache_key, result, ttl)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, run in event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(async_wrapper(*args, **kwargs))
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


def _generate_cache_key(
    func: Callable,
    args: tuple,
    kwargs: dict,
    prefix: Optional[str] = None
) -> str:
    """Generate cache key for function call."""
    key_parts = [
        prefix or func.__module__,
        func.__name__,
        str(args),
        str(sorted(kwargs.items()))
    ]
    key_str = ":".join(key_parts)
    return hashlib.sha256(key_str.encode()).hexdigest()