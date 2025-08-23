"""
Caching System for AzabBot
==========================

LRU cache with TTL support for frequently accessed data.
"""

import asyncio
import time
from typing import Any, Dict, Optional, Callable
from functools import wraps
import weakref
from src.core.logger import get_logger

class TTLCache:
    """Time-based LRU cache."""
    
    def __init__(self, max_size: int = 100, default_ttl: int = 300):
        """
        Initialize cache.
        
        Args:
            max_size: Maximum number of items
            default_ttl: Default TTL in seconds (5 minutes)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cache: Dict[str, tuple[Any, float]] = {}
        self.access_times: Dict[str, float] = {}
        self.logger = get_logger()
        self._lock = asyncio.Lock()
        
    async def get(self, key: str) -> Optional[Any]:
        """Get item from cache."""
        async with self._lock:
            if key in self.cache:
                value, expiry = self.cache[key]
                if time.time() < expiry:
                    self.access_times[key] = time.time()
                    return value
                else:
                    # Expired
                    del self.cache[key]
                    del self.access_times[key]
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set item in cache."""
        async with self._lock:
            ttl = ttl or self.default_ttl
            expiry = time.time() + ttl
            
            # Check if we need to evict
            if len(self.cache) >= self.max_size and key not in self.cache:
                # Evict least recently used
                lru_key = min(self.access_times, key=self.access_times.get)
                del self.cache[lru_key]
                del self.access_times[lru_key]
                self.logger.log_debug(f"Evicted {lru_key} from cache (LRU)")
            
            self.cache[key] = (value, expiry)
            self.access_times[key] = time.time()
    
    async def delete(self, key: str) -> None:
        """Delete item from cache."""
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
                del self.access_times[key]
    
    async def clear(self) -> None:
        """Clear all cache."""
        async with self._lock:
            self.cache.clear()
            self.access_times.clear()
            self.logger.log_info("Cache cleared")
    
    async def cleanup_expired(self) -> int:
        """Remove expired items."""
        async with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, expiry) in self.cache.items()
                if current_time >= expiry
            ]
            
            for key in expired_keys:
                del self.cache[key]
                del self.access_times[key]
            
            if expired_keys:
                self.logger.log_debug(f"Cleaned up {len(expired_keys)} expired cache entries")
            
            return len(expired_keys)
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_rate": 0,  # Would need to track hits/misses
            "oldest_entry": min(self.access_times.values()) if self.access_times else None
        }

class CacheManager:
    """Manages multiple caches for different data types."""
    
    def __init__(self):
        """Initialize cache manager."""
        self.caches = {
            "prisoners": TTLCache(max_size=50, default_ttl=300),  # 5 min
            "profiles": TTLCache(max_size=30, default_ttl=600),   # 10 min
            "sessions": TTLCache(max_size=20, default_ttl=1800),  # 30 min
            "responses": TTLCache(max_size=100, default_ttl=60),  # 1 min
        }
        self.logger = get_logger()
        self._cleanup_task = None
        
    async def start(self):
        """Start cache cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.logger.log_info("Cache manager started")
    
    async def stop(self):
        """Stop cache cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clear all caches
        for cache in self.caches.values():
            await cache.clear()
        
        self.logger.log_info("Cache manager stopped")
    
    async def _cleanup_loop(self):
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                total_cleaned = 0
                for name, cache in self.caches.items():
                    cleaned = await cache.cleanup_expired()
                    total_cleaned += cleaned
                
                if total_cleaned > 0:
                    self.logger.log_debug(f"Cleaned {total_cleaned} expired cache entries")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Error in cache cleanup: {e}")
    
    def get_cache(self, name: str) -> Optional[TTLCache]:
        """Get a specific cache."""
        return self.caches.get(name)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all caches."""
        stats = {}
        for name, cache in self.caches.items():
            stats[name] = cache.stats()
        return stats

# Decorator for caching async functions
def cached(cache_name: str, ttl: Optional[int] = None, key_func: Optional[Callable] = None):
    """
    Decorator to cache async function results.
    
    Args:
        cache_name: Name of cache to use
        ttl: TTL in seconds
        key_func: Function to generate cache key from args
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Get cache manager
            if not hasattr(self, '_cache_manager'):
                return await func(self, *args, **kwargs)
            
            cache = self._cache_manager.get_cache(cache_name)
            if not cache:
                return await func(self, *args, **kwargs)
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Simple key from args
                cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Check cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Call function
            result = await func(self, *args, **kwargs)
            
            # Cache result
            await cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator

# Global cache manager instance
_cache_manager = CacheManager()

def get_cache_manager() -> CacheManager:
    """Get global cache manager."""
    return _cache_manager