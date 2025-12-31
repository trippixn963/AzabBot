"""
Azab Discord Bot - Rate Limiter
===============================

Unified rate limiting with named buckets for Discord API operations.

DESIGN:
    Token bucket algorithm with per-bucket configuration.
    Automatically handles delays between operations to prevent 429s.

Usage:
    rate_limiter = get_rate_limiter()

    # Wait for rate limit before operation
    await rate_limiter.acquire("discord_api")
    await channel.send(...)

    # Or use context manager
    async with rate_limiter.limit("discord_api"):
        await channel.send(...)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, AsyncIterator
from contextlib import asynccontextmanager

from src.core.logger import logger


# =============================================================================
# Bucket Configuration
# =============================================================================

@dataclass
class BucketConfig:
    """Configuration for a rate limit bucket."""

    rate: float  # Operations per second
    burst: int = 1  # Max burst size
    name: str = ""  # For logging

    @property
    def interval(self) -> float:
        """Minimum interval between operations."""
        return 1.0 / self.rate if self.rate > 0 else 0


# Default bucket configurations
BUCKETS: Dict[str, BucketConfig] = {
    # Discord API operations
    "discord_api": BucketConfig(rate=1.0, burst=3, name="Discord API"),
    "discord_api_fast": BucketConfig(rate=2.0, burst=5, name="Discord API Fast"),
    "discord_api_slow": BucketConfig(rate=0.5, burst=1, name="Discord API Slow"),

    # Message sending
    "send_message": BucketConfig(rate=2.0, burst=5, name="Send Message"),
    "send_embed": BucketConfig(rate=1.5, burst=3, name="Send Embed"),
    "bulk_operation": BucketConfig(rate=0.2, burst=1, name="Bulk Operation"),

    # Thread operations
    "thread_create": BucketConfig(rate=0.5, burst=2, name="Thread Create"),
    "thread_edit": BucketConfig(rate=1.0, burst=3, name="Thread Edit"),

    # Role operations
    "role_modify": BucketConfig(rate=1.0, burst=2, name="Role Modify"),

    # Webhook operations
    "webhook": BucketConfig(rate=0.5, burst=2, name="Webhook"),

    # Mod tracker logging
    "mod_tracker": BucketConfig(rate=2.0, burst=5, name="Mod Tracker"),

    # Server logs
    "server_logs": BucketConfig(rate=2.0, burst=10, name="Server Logs"),
}


# =============================================================================
# Token Bucket Implementation
# =============================================================================

@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    config: BucketConfig
    tokens: float = field(default=0, init=False)
    last_update: float = field(default_factory=time.monotonic, init=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self.tokens = float(self.config.burst)

    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            Time waited in seconds.
        """
        async with self.lock:
            now = time.monotonic()

            # Refill tokens based on time elapsed
            elapsed = now - self.last_update
            self.tokens = min(
                self.config.burst,
                self.tokens + elapsed * self.config.rate
            )
            self.last_update = now

            # Calculate wait time if not enough tokens
            wait_time = 0.0
            if self.tokens < tokens:
                deficit = tokens - self.tokens
                wait_time = deficit / self.config.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
                self.last_update = time.monotonic()
            else:
                self.tokens -= tokens

            return wait_time


# =============================================================================
# Rate Limiter Service
# =============================================================================

class RateLimiter:
    """
    Unified rate limiter with named buckets.

    DESIGN:
        Singleton pattern ensures consistent rate limiting across all services.
        Each bucket tracks its own token count independently.
    """

    _instance: Optional["RateLimiter"] = None

    def __new__(cls) -> "RateLimiter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._buckets: Dict[str, TokenBucket] = {}
        self._initialized = True

        # Pre-create default buckets
        for name, config in BUCKETS.items():
            self._buckets[name] = TokenBucket(config)

        logger.tree("Rate Limiter Initialized", [
            ("Buckets", str(len(BUCKETS))),
        ], emoji="")

    def _get_bucket(self, name: str) -> TokenBucket:
        """Get or create a bucket by name."""
        if name not in self._buckets:
            # Default config for unknown buckets
            config = BucketConfig(rate=1.0, burst=1, name=name)
            self._buckets[name] = TokenBucket(config)
        return self._buckets[name]

    async def acquire(self, bucket: str = "discord_api", tokens: int = 1) -> float:
        """
        Acquire tokens from a bucket, waiting if necessary.

        Args:
            bucket: Name of the rate limit bucket.
            tokens: Number of tokens to acquire.

        Returns:
            Time waited in seconds.
        """
        b = self._get_bucket(bucket)
        wait_time = await b.acquire(tokens)

        if wait_time > 0.1:  # Only log significant waits
            logger.debug(f"Rate limit wait: {b.config.name} ({wait_time:.2f}s)")

        return wait_time

    @asynccontextmanager
    async def limit(self, bucket: str = "discord_api", tokens: int = 1) -> AsyncIterator[None]:
        """
        Context manager for rate-limited operations.

        Usage:
            async with rate_limiter.limit("discord_api"):
                await channel.send(...)
        """
        await self.acquire(bucket, tokens)
        yield

    async def wait(self, seconds: float) -> None:
        """Simple delay helper for explicit waits."""
        if seconds > 0:
            await asyncio.sleep(seconds)


# =============================================================================
# Global Instance
# =============================================================================

_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


# =============================================================================
# Convenience Functions
# =============================================================================

async def rate_limit(bucket: str = "discord_api", tokens: int = 1) -> float:
    """
    Convenience function for quick rate limiting.

    Usage:
        await rate_limit("discord_api")
        await channel.send(...)
    """
    return await get_rate_limiter().acquire(bucket, tokens)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "RateLimiter",
    "rate_limit",
    "BucketConfig",
    "BUCKETS",
]
