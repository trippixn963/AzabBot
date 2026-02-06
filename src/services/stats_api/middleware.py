"""
AzabBot - Middleware
====================

Rate limiting, caching, and middleware functions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from typing import Dict, List, Optional

from aiohttp import web

from src.core.constants import RATE_LIMIT_REQUESTS, RATE_LIMIT_BURST, STATS_CACHE_TTL


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Sliding window rate limiter per IP address."""

    def __init__(self, requests_per_minute: int = RATE_LIMIT_REQUESTS, burst_limit: int = RATE_LIMIT_BURST):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self._requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_ip: str) -> tuple[bool, Optional[int]]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        async with self._lock:
            now = time.time()
            window_start = now - 60

            # Get or initialize request history
            if client_ip not in self._requests:
                self._requests[client_ip] = []

            # Remove old requests outside window
            self._requests[client_ip] = [
                ts for ts in self._requests[client_ip] if ts > window_start
            ]

            requests = self._requests[client_ip]

            # Check burst limit (last second)
            recent_requests = sum(1 for ts in requests if ts > now - 1)
            if recent_requests >= self.burst_limit:
                return False, 1

            # Check rate limit
            if len(requests) >= self.requests_per_minute:
                oldest = min(requests)
                retry_after = int(oldest + 60 - now) + 1
                return False, max(1, retry_after)

            # Allow and record
            requests.append(now)
            return True, None

    async def cleanup(self) -> None:
        """Remove stale entries."""
        async with self._lock:
            now = time.time()
            window_start = now - 60
            self._requests = {
                ip: [ts for ts in times if ts > window_start]
                for ip, times in self._requests.items()
                if any(ts > window_start for ts in times)
            }


# Global rate limiter
rate_limiter = RateLimiter(requests_per_minute=RATE_LIMIT_REQUESTS, burst_limit=RATE_LIMIT_BURST)


# =============================================================================
# Response Cache
# =============================================================================

class ResponseCache:
    """Simple TTL cache for API responses."""

    def __init__(self, ttl: int = STATS_CACHE_TTL):
        self.ttl = ttl
        self._cache: Dict[str, tuple[Dict, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Dict]:
        """Get cached response if not expired."""
        async with self._lock:
            if key in self._cache:
                data, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return data
                try:
                    del self._cache[key]
                except KeyError:
                    pass  # Already removed
        return None

    async def set(self, key: str, data: Dict) -> None:
        """Cache response."""
        async with self._lock:
            self._cache[key] = (data, time.time())

    async def invalidate(self, key: str) -> None:
        """Invalidate cache entry."""
        async with self._lock:
            self._cache.pop(key, None)


# =============================================================================
# Helper Functions
# =============================================================================

def get_client_ip(request: web.Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check X-Forwarded-For header (from reverse proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct connection
    peername = request.transport.get_extra_info("peername")
    if peername:
        return peername[0]

    return "unknown"


# =============================================================================
# Middleware Functions
# =============================================================================

@web.middleware
async def rate_limit_middleware(request: web.Request, handler) -> web.Response:
    """Enforce rate limiting on all endpoints except /health."""
    if request.path == "/health":
        return await handler(request)

    client_ip = get_client_ip(request)
    allowed, retry_after = await rate_limiter.is_allowed(client_ip)

    if not allowed:
        return web.json_response(
            {"error": "Rate limit exceeded", "retry_after": retry_after},
            status=429,
            headers={
                "Retry-After": str(retry_after),
                "Access-Control-Allow-Origin": "*",
            }
        )

    return await handler(request)


@web.middleware
async def security_headers_middleware(request: web.Request, handler) -> web.Response:
    """Add security headers to all responses."""
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


__all__ = [
    "RateLimiter",
    "ResponseCache",
    "rate_limiter",
    "get_client_ip",
    "rate_limit_middleware",
    "security_headers_middleware",
]
