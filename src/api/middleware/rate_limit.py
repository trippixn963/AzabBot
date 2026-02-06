"""
AzabBot - Rate Limiting Middleware
==================================

Token bucket rate limiting for API endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from src.core.logger import logger
from src.api.config import get_api_config


# =============================================================================
# Token Bucket
# =============================================================================

@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float = field(default=0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = 1.0  # tokens per second

    def __post_init__(self):
        self.tokens = float(self.capacity)

    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from the bucket.

        Returns:
            True if tokens were consumed, False if not enough tokens
        """
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        # Refill tokens
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Calculate seconds until a token is available."""
        if self.tokens >= 1:
            return 0
        return (1 - self.tokens) / self.refill_rate


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Manages rate limiting across multiple clients.

    Features:
    - Per-IP rate limiting
    - Per-user rate limiting (when authenticated)
    - Configurable limits per endpoint
    - Automatic cleanup of stale buckets
    """

    def __init__(
        self,
        default_limit: int = 60,
        default_window: int = 60,
    ):
        self._default_limit = default_limit
        self._default_window = default_window
        self._buckets: dict[str, TokenBucket] = {}
        self._endpoint_limits: dict[str, tuple[int, int]] = {}  # path -> (limit, window)
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes

    def set_limit(self, path: str, limit: int, window: int = 60) -> None:
        """Set a custom limit for a specific path pattern."""
        self._endpoint_limits[path] = (limit, window)

    def _get_bucket_key(
        self,
        client_ip: str,
        path: str,
        user_id: Optional[int] = None,
    ) -> str:
        """Generate a unique key for the rate limit bucket."""
        if user_id:
            return f"user:{user_id}:{path}"
        return f"ip:{client_ip}:{path}"

    def _get_limit_for_path(self, path: str) -> tuple[int, int]:
        """Get the rate limit for a path."""
        # Check for exact match
        if path in self._endpoint_limits:
            return self._endpoint_limits[path]

        # Check for prefix match
        for pattern, limits in self._endpoint_limits.items():
            if path.startswith(pattern):
                return limits

        return self._default_limit, self._default_window

    def _cleanup_stale_buckets(self) -> None:
        """Remove buckets that haven't been used recently."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        stale_threshold = now - 600  # 10 minutes

        stale_keys = [
            key for key, bucket in self._buckets.items()
            if bucket.last_update < stale_threshold
        ]

        for key in stale_keys:
            del self._buckets[key]

        if stale_keys:
            logger.debug("Rate Limit Cleanup", [
                ("Removed", str(len(stale_keys))),
                ("Remaining", str(len(self._buckets))),
            ])

    def check(
        self,
        client_ip: str,
        path: str,
        user_id: Optional[int] = None,
    ) -> tuple[bool, Optional[float], int, int]:
        """
        Check if a request should be allowed.

        Returns:
            Tuple of (allowed, retry_after, remaining, limit)
        """
        self._cleanup_stale_buckets()

        key = self._get_bucket_key(client_ip, path, user_id)
        limit, window = self._get_limit_for_path(path)

        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                capacity=limit,
                refill_rate=limit / window,
            )

        bucket = self._buckets[key]
        allowed = bucket.consume()

        return (
            allowed,
            bucket.retry_after if not allowed else None,
            int(bucket.tokens),
            limit,
        )


# =============================================================================
# Middleware
# =============================================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.

    Adds rate limit headers to responses:
    - X-RateLimit-Limit: Maximum requests allowed
    - X-RateLimit-Remaining: Requests remaining in window
    - X-RateLimit-Reset: Seconds until limit resets
    - Retry-After: Seconds to wait (only on 429)
    """

    def __init__(self, app, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(app)
        self._limiter = rate_limiter or rate_limiter_instance

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ("/health", "/api/health", "/api/v1/health"):
            return await call_next(request)

        # Get client info
        client_ip = self._get_client_ip(request)
        path = self._normalize_path(request.url.path)
        user_id = getattr(request.state, "user_id", None)

        # Check rate limit
        allowed, retry_after, remaining, limit = self._limiter.check(
            client_ip, path, user_id
        )

        if not allowed:
            logger.debug("Rate Limit Exceeded", [
                ("IP", client_ip),
                ("Path", path),
                ("Retry After", f"{retry_after:.1f}s"),
            ])

            response = Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
            response.headers["Retry-After"] = str(int(retry_after or 1))
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            return response

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, considering proxies."""
        # Check for forwarded headers (when behind proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fallback to direct client
        if request.client:
            return request.client.host
        return "unknown"

    def _normalize_path(self, path: str) -> str:
        """Normalize path for rate limiting (group similar endpoints)."""
        parts = path.rstrip("/").split("/")

        # Group by resource type, ignoring specific IDs
        normalized = []
        for part in parts:
            # Skip empty parts
            if not part:
                continue

            # Check if this looks like an ID (numeric or UUID-like)
            if part.isdigit() or (len(part) > 20 and "-" in part):
                normalized.append("{id}")
            else:
                normalized.append(part)

        return "/" + "/".join(normalized)


# =============================================================================
# Singleton
# =============================================================================

rate_limiter_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the rate limiter singleton."""
    global rate_limiter_instance
    if rate_limiter_instance is None:
        config = get_api_config()
        rate_limiter_instance = RateLimiter(
            default_limit=config.rate_limit_requests,
            default_window=config.rate_limit_window,
        )

        # Set stricter limits for auth endpoints
        rate_limiter_instance.set_limit("/api/v1/auth/login", 5, 60)
        rate_limiter_instance.set_limit("/api/v1/auth/register", 3, 60)

        # More lenient for read operations
        rate_limiter_instance.set_limit("/api/v1/stats", 120, 60)
        rate_limiter_instance.set_limit("/api/v1/health", 300, 60)

    return rate_limiter_instance


# Convenience alias
rate_limiter = get_rate_limiter


__all__ = ["RateLimitMiddleware", "RateLimiter", "rate_limiter", "get_rate_limiter"]
