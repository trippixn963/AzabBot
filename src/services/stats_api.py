"""
Azab Discord Bot - Stats API
============================

HTTP API server exposing moderation statistics for the dashboard.

Endpoints:
    GET /api/azab/stats              - Main dashboard stats
    GET /api/azab/user/{id}          - Individual user (offender) profile
    GET /api/azab/moderator/{id}     - Moderator profile
    GET /api/azab/transcripts/{id}   - Ticket transcript HTML
    GET /health                      - Health check

Author: discord.gg/syria
"""

import asyncio
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import psutil
from aiohttp import web

from src.core.config import get_config, NY_TZ
from src.core.logger import logger
from src.core.constants import (
    STATS_API_PORT,
    STATS_CACHE_TTL,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_BURST,
    GUILD_FETCH_TIMEOUT,
)
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

STATS_API_HOST = "0.0.0.0"
BOT_HOME = os.environ.get("BOT_HOME", "/root/AzabBot")


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
rate_limiter = RateLimiter(requests_per_minute=60, burst_limit=10)


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
# Middleware
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


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
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
async def security_headers_middleware(request: web.Request, handler):
    """Add security headers to all responses."""
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# =============================================================================
# Avatar Cache
# =============================================================================

_avatar_cache: Dict[int, tuple[Optional[str], str]] = {}
_avatar_cache_date: Optional[str] = None


# =============================================================================
# AzabAPI Class
# =============================================================================

class AzabAPI:
    """HTTP API server for Azab moderation stats."""

    def __init__(self, bot: "AzabBot") -> None:
        self._bot = bot
        self._config = get_config()
        self._start_time: Optional[datetime] = None
        self._cache = ResponseCache()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.runner: Optional[web.AppRunner] = None
        self.app: Optional[web.Application] = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the API server."""
        self._start_time = datetime.now(NY_TZ)

        # Create app with middleware
        self.app = web.Application(middlewares=[
            rate_limit_middleware,
            security_headers_middleware,
        ])

        # Setup routes
        self._setup_routes()

        # Start server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(self.runner, STATS_API_HOST, STATS_API_PORT)
        await site.start()

        # Start cleanup task
        self._cleanup_task = create_safe_task(self._cleanup_loop(), "Stats API Cleanup")

        logger.tree("Azab API Started", [
            ("Host", STATS_API_HOST),
            ("Port", str(STATS_API_PORT)),
            ("Endpoints", "/api/azab/stats, /api/azab/user/{id}, /health"),
            ("Rate Limit", "60 req/min, 10 burst"),
        ], emoji="🌐")

    async def stop(self) -> None:
        """Stop the API server."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self.runner:
            await self.runner.cleanup()
            self.runner = None

        logger.info("🌐 Azab API Stopped")

    def _setup_routes(self) -> None:
        """Configure API routes."""
        self.app.router.add_get("/api/azab/stats", self.handle_stats)
        self.app.router.add_get("/api/azab/user/{user_id}", self.handle_user)
        self.app.router.add_get("/api/azab/moderator/{user_id}", self.handle_moderator)
        self.app.router.add_get("/api/azab/transcripts/{ticket_id}", self.handle_transcript)
        self.app.router.add_get("/health", self.handle_health)

    async def _cleanup_loop(self) -> None:
        """Periodically clean up rate limiter entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await rate_limiter.cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    # =========================================================================
    # Endpoint Handlers
    # =========================================================================

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "bot": "Azab",
            "connected": self._bot.is_ready(),
            "timestamp": datetime.now(NY_TZ).isoformat()
        })

    async def handle_transcript(self, request: web.Request) -> web.Response:
        """Serve ticket transcript HTML."""
        ticket_id = request.match_info.get("ticket_id", "").upper()

        if not ticket_id:
            return web.Response(
                text="<h1>404 - Ticket ID Required</h1>",
                status=404,
                content_type="text/html",
            )

        # Get transcript from database
        from src.core.database import get_db
        db = get_db()
        html_content = db.get_ticket_transcript(ticket_id)

        if not html_content:
            return web.Response(
                text=f"<h1>404 - Transcript Not Found</h1><p>No transcript found for ticket {ticket_id}</p>",
                status=404,
                content_type="text/html",
            )

        logger.tree("Transcript Served", [
            ("Ticket ID", ticket_id),
            ("Client IP", get_client_ip(request)),
        ], emoji="📜")

        return web.Response(
            text=html_content,
            content_type="text/html",
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            }
        )

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Main stats endpoint."""
        start_time = time.time()
        client_ip = get_client_ip(request)

        logger.info("Stats API Request", [
            ("Path", "/api/azab/stats"),
            ("Client IP", client_ip),
        ])

        try:
            # Check cache
            cached = await self._cache.get("stats")
            if cached:
                cached["cached"] = True
                cached["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
                return web.json_response(cached, headers={
                    "Cache-Control": "public, max-age=30"
                })

            # Build fresh response
            now = datetime.now(NY_TZ)
            guild_id = self._config.logging_guild_id

            # Get time ranges
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            today_end = now.timestamp()
            week_start = (now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() - 7 * 86400)

            # Gather stats
            moderation = await self._get_moderation_stats(today_start, today_end, week_start, guild_id)
            appeals = self._bot.db.get_appeal_stats(guild_id) if guild_id else {"pending": 0, "approved": 0, "denied": 0}
            tickets = self._bot.db.get_ticket_stats(guild_id) if guild_id else {"open": 0, "claimed": 0, "closed": 0}
            top_offenders = await self._get_top_offenders(guild_id)
            mod_leaderboard = await self._get_moderator_leaderboard()
            recent_actions = await self._get_recent_actions(guild_id)
            repeat_offenders = await self._get_repeat_offenders(guild_id)
            recent_releases = await self._get_recent_releases(guild_id)
            mod_spotlight = await self._get_moderator_spotlight(guild_id)
            system = self._get_system_resources()
            changelog = await self._get_changelog()

            response = {
                "bot": {
                    "online": self._bot.is_ready(),
                    "latency_ms": round(self._bot.latency * 1000) if self._bot.latency else 0,
                    "guilds": len(self._bot.guilds),
                    "uptime": self._format_uptime(),
                },
                "moderation": moderation,
                "appeals": appeals,
                "tickets": tickets,
                "top_offenders": top_offenders,
                "moderator_leaderboard": mod_leaderboard,
                "recent_actions": recent_actions,
                "repeat_offenders": repeat_offenders,
                "recent_releases": recent_releases,
                "moderator_spotlight": mod_spotlight,
                "system": system,
                "changelog": changelog,
                "generated_at": now.isoformat(),
                "cached": False,
            }

            # Cache response
            await self._cache.set("stats", response)

            response["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

            logger.success("Stats API Response", [
                ("Client IP", client_ip),
                ("Response Time", f"{response['response_time_ms']}ms"),
            ])

            return web.json_response(response, headers={
                "Cache-Control": "public, max-age=30"
            })

        except Exception as e:
            logger.error("Stats API Error", [("Error", str(e)[:100])])
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )

    async def handle_user(self, request: web.Request) -> web.Response:
        """User profile endpoint."""
        start_time = time.time()
        user_id_str = request.match_info.get("user_id", "")

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response(
                {"error": "Invalid user ID"},
                status=400
            )

        try:
            # Check cache
            cache_key = f"user_{user_id}"
            cached = await self._cache.get(cache_key)
            if cached:
                cached["cached"] = True
                cached["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
                return web.json_response(cached)

            guild_id = self._config.logging_guild_id

            # Get user data
            mute_count = self._bot.db.get_user_mute_count(user_id, guild_id) if guild_id else 0
            ban_count = self._bot.db.get_user_ban_count(user_id, guild_id) if guild_id else 0
            warn_count = self._bot.db.get_user_warn_count(user_id, guild_id) if guild_id else 0
            active_warns = self._bot.db.get_active_warn_count(user_id, guild_id) if guild_id else 0
            is_muted = self._bot.db.is_user_muted(user_id, guild_id) if guild_id else False

            # Get user info from Discord
            name, avatar = await self._fetch_user_data(user_id, f"User {user_id}")

            # Get rank among offenders
            top_offenders = self._bot.db.get_top_offenders(limit=100, guild_id=guild_id)
            rank = next(
                (i + 1 for i, o in enumerate(top_offenders) if o["user_id"] == user_id),
                None
            )

            # Get recent punishments for this user
            recent_punishments = await self._get_user_recent_punishments(user_id, guild_id, limit=10)

            response = {
                "user_id": str(user_id),
                "name": name,
                "avatar": avatar,
                "rank": rank,
                "mutes": mute_count,
                "bans": ban_count,
                "warns": warn_count,
                "total_punishments": mute_count + ban_count + warn_count,
                "active_warns": active_warns,
                "currently_muted": is_muted,
                "recent_punishments": recent_punishments,
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "cached": False,
            }

            await self._cache.set(cache_key, response)
            response["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

            return web.json_response(response)

        except Exception as e:
            logger.error("User API Error", [("Error", str(e)[:100])])
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )

    async def handle_moderator(self, request: web.Request) -> web.Response:
        """Moderator profile endpoint."""
        start_time = time.time()
        user_id_str = request.match_info.get("user_id", "")

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response(
                {"error": "Invalid user ID"},
                status=400
            )

        try:
            # Check cache
            cache_key = f"moderator_{user_id}"
            cached = await self._cache.get(cache_key)
            if cached:
                cached["cached"] = True
                cached["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
                return web.json_response(cached)

            guild_id = self._config.logging_guild_id

            # Get moderator stats
            mod_stats = self._bot.db.get_moderator_stats(user_id, guild_id)

            if not mod_stats or mod_stats.get("total_actions", 0) == 0:
                return web.json_response(
                    {"error": "Moderator has no recorded actions"},
                    status=404
                )

            # Get user info from Discord
            name, avatar = await self._fetch_user_data(user_id, f"Mod {user_id}")

            # Get rank among moderators
            mod_leaderboard = self._bot.db.get_moderator_leaderboard(limit=100)
            rank = next(
                (i + 1 for i, m in enumerate(mod_leaderboard) if m["moderator_id"] == user_id),
                None
            )

            # Get recent actions by this moderator
            recent_actions = await self._get_moderator_recent_actions(user_id, guild_id, limit=10)

            response = {
                "user_id": str(user_id),
                "name": name,
                "avatar": avatar,
                "mutes_issued": mod_stats.get("mutes_issued", 0),
                "bans_issued": mod_stats.get("bans_issued", 0),
                "warns_issued": mod_stats.get("warns_issued", 0),
                "total_actions": mod_stats.get("total_actions", 0),
                "rank": rank,
                "recent_actions": recent_actions,
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "cached": False,
            }

            await self._cache.set(cache_key, response)
            response["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

            return web.json_response(response)

        except Exception as e:
            logger.error("Moderator API Error", [("Error", str(e)[:100])])
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )

    # =========================================================================
    # Data Helpers
    # =========================================================================

    async def _get_moderation_stats(
        self,
        today_start: float,
        today_end: float,
        week_start: float,
        guild_id: Optional[int]
    ) -> Dict[str, Any]:
        """Get moderation statistics."""
        db = self._bot.db

        return {
            "today": {
                "mutes": db.get_mutes_in_range(today_start, today_end, guild_id),
                "bans": db.get_bans_in_range(today_start, today_end, guild_id),
                "warns": db.get_warns_in_range(today_start, today_end, guild_id),
            },
            "weekly": {
                "mutes": db.get_mutes_in_range(week_start, today_end, guild_id),
                "bans": db.get_bans_in_range(week_start, today_end, guild_id),
                "warns": db.get_warns_in_range(week_start, today_end, guild_id),
            },
            "all_time": {
                "total_mutes": db.get_total_mutes(guild_id),
                "total_bans": db.get_total_bans(guild_id),
                "total_warns": db.get_total_warns(guild_id),
                "total_cases": db.get_total_cases(guild_id),
            },
            "active": {
                "prisoners": db.get_active_prisoners_count(guild_id),
                "open_cases": db.get_open_cases_count(guild_id),
            },
        }

    async def _get_top_offenders(self, guild_id: Optional[int], limit: int = 10) -> List[Dict]:
        """Get top offenders with avatar data."""
        offenders = self._bot.db.get_top_offenders(limit=limit, guild_id=guild_id)

        # Enrich with user data
        enriched = []
        for offender in offenders:
            user_id = offender["user_id"]
            name, avatar = await self._fetch_user_data(user_id, f"User {user_id}")
            enriched.append({
                "user_id": str(user_id),
                "name": name,
                "mutes": offender["mutes"],
                "bans": offender["bans"],
                "warns": offender["warns"],
                "total": offender["total"],
                "avatar": avatar,
            })

        return enriched

    async def _get_moderator_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get moderator leaderboard with avatar data."""
        mods = self._bot.db.get_moderator_leaderboard(limit=limit)

        enriched = []
        for mod in mods:
            mod_id = mod["moderator_id"]
            name, avatar = await self._fetch_user_data(mod_id, f"Mod {mod_id}")
            enriched.append({
                "user_id": str(mod_id),
                "name": name,
                "actions": mod["action_count"],
                "avatar": avatar,
            })

        return enriched

    async def _get_recent_actions(self, guild_id: Optional[int], limit: int = 10) -> List[Dict]:
        """Get recent moderation actions."""
        actions = self._bot.db.get_recent_actions(limit=limit, guild_id=guild_id)

        enriched = []
        for action in actions:
            user_name, _ = await self._fetch_user_data(action["user_id"], f"User {action['user_id']}")
            mod_name, _ = await self._fetch_user_data(action["moderator_id"], f"Mod {action['moderator_id']}")

            # Format timestamp
            ts = action["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": action["type"],
                "user": user_name,
                "user_id": str(action["user_id"]),
                "moderator": mod_name,
                "moderator_id": str(action["moderator_id"]),
                "reason": (action["reason"] or "No reason")[:100],
                "time": time_str,
                "timestamp": ts,
            })

        return enriched

    async def _get_repeat_offenders(self, guild_id: Optional[int], limit: int = 5) -> List[Dict]:
        """Get users with 3+ total punishments (repeat offenders)."""
        offenders = self._bot.db.get_repeat_offenders(min_offenses=3, limit=limit, guild_id=guild_id)

        enriched = []
        for offender in offenders:
            user_id = offender["user_id"]
            name, avatar = await self._fetch_user_data(user_id, f"User {user_id}")
            enriched.append({
                "user_id": str(user_id),
                "name": name,
                "mutes": offender["mutes"],
                "bans": offender["bans"],
                "warns": offender["warns"],
                "total": offender["total"],
                "avatar": avatar,
            })

        return enriched

    async def _get_recent_releases(self, guild_id: Optional[int], limit: int = 5) -> List[Dict]:
        """Get recently released prisoners."""
        releases = self._bot.db.get_recent_releases(limit=limit, guild_id=guild_id)

        enriched = []
        for release in releases:
            try:
                user_id = release["user_id"]
                name, avatar = await self._fetch_user_data(user_id, f"User {user_id}")

                # Format duration - cap at reasonable values
                duration_mins = release.get("duration_minutes", 0) or 0
                # Sanity check: cap at 1 year (525600 minutes)
                if duration_mins > 525600:
                    duration_mins = 0

                if duration_mins >= 1440:  # 24 hours
                    duration_str = f"{duration_mins // 1440}d {(duration_mins % 1440) // 60}h"
                elif duration_mins >= 60:
                    duration_str = f"{duration_mins // 60}h {duration_mins % 60}m"
                else:
                    duration_str = f"{duration_mins}m" if duration_mins > 0 else "N/A"

                # Format release time using muted_at (more reliable)
                muted_at = release.get("muted_at")
                if muted_at and muted_at < 2000000000:  # Sanity check: before year 2033
                    muted_time = datetime.fromtimestamp(muted_at, NY_TZ)
                    now = datetime.now(NY_TZ)
                    delta = now - muted_time
                    if delta.days > 0:
                        time_str = f"{delta.days}d ago"
                    elif delta.seconds >= 3600:
                        time_str = f"{delta.seconds // 3600}h ago"
                    elif delta.seconds >= 60:
                        time_str = f"{delta.seconds // 60}m ago"
                    else:
                        time_str = "just now"
                else:
                    time_str = "recently"

                enriched.append({
                    "user_id": str(user_id),
                    "name": name,
                    "avatar": avatar,
                    "time_served": duration_str,
                    "released": time_str,
                })
            except Exception:
                # Skip problematic entries
                continue

        return enriched

    async def _get_moderator_spotlight(self, guild_id: Optional[int]) -> Optional[Dict]:
        """Get top moderator of the week (excludes the bot itself)."""
        bot_user_id = self._bot.user.id if self._bot.user else None
        top_mod = self._bot.db.get_weekly_top_moderator(guild_id=guild_id, exclude_user_id=bot_user_id)

        if not top_mod:
            return None

        mod_id = top_mod["moderator_id"]
        name, avatar = await self._fetch_user_data(mod_id, f"Mod {mod_id}")

        return {
            "user_id": str(mod_id),
            "name": name,
            "avatar": avatar,
            "weekly_actions": top_mod["weekly_actions"],
            "mutes": top_mod["mutes"],
            "bans": top_mod["bans"],
            "warns": top_mod["warns"],
        }

    async def _get_moderator_recent_actions(
        self,
        moderator_id: int,
        guild_id: Optional[int],
        limit: int = 10
    ) -> List[Dict]:
        """Get recent actions by a specific moderator."""
        actions = self._bot.db.get_moderator_actions(moderator_id, limit=limit, guild_id=guild_id)

        enriched = []
        for action in actions:
            target_name, _ = await self._fetch_user_data(action["user_id"], f"User {action['user_id']}")

            # Format timestamp
            ts = action["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": action["type"],
                "target": target_name,
                "target_id": str(action["user_id"]),
                "reason": (action["reason"] or "No reason")[:100],
                "time": time_str,
                "timestamp": ts,
            })

        return enriched

    async def _get_user_recent_punishments(
        self,
        user_id: int,
        guild_id: Optional[int],
        limit: int = 10
    ) -> List[Dict]:
        """Get recent punishments received by a user."""
        punishments = self._bot.db.get_user_punishments(user_id, limit=limit, guild_id=guild_id)

        enriched = []
        for p in punishments:
            mod_name, _ = await self._fetch_user_data(p["moderator_id"], f"Mod {p['moderator_id']}") if p.get("moderator_id") else ("Unknown", None)

            # Format timestamp
            ts = p["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": p["type"],
                "reason": (p["reason"] or "No reason")[:100],
                "moderator": mod_name,
                "time": time_str,
            })

        return enriched

    def _get_system_resources(self) -> Dict[str, float]:
        """Get system resource usage."""
        try:
            process = psutil.Process()
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            return {
                "bot_mem_mb": round(process.memory_info().rss / 1024 / 1024, 1),
                "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
                "mem_percent": round(mem.percent, 1),
                "mem_used_gb": round(mem.used / 1024 / 1024 / 1024, 2),
                "mem_total_gb": round(mem.total / 1024 / 1024 / 1024, 2),
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            }
        except Exception:
            return {
                "bot_mem_mb": 0,
                "cpu_percent": 0,
                "mem_percent": 0,
                "mem_used_gb": 0,
                "mem_total_gb": 0,
                "disk_percent": 0,
                "disk_used_gb": 0,
                "disk_total_gb": 0,
            }

    async def _get_changelog(self, limit: int = 10) -> List[Dict[str, str]]:
        """Get recent git commits."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", f"-{limit}", "--format=%h|%s",
                cwd=BOT_HOME,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=GUILD_FETCH_TIMEOUT)

            changelog = []
            for line in stdout.decode().strip().split("\n"):
                if "|" in line:
                    commit, message = line.split("|", 1)
                    # Determine type
                    msg_lower = message.lower()
                    if any(w in msg_lower for w in ["fix", "bug", "patch"]):
                        commit_type = "fix"
                    elif any(w in msg_lower for w in ["add", "new", "feature", "implement"]):
                        commit_type = "feature"
                    else:
                        commit_type = "improvement"

                    changelog.append({
                        "commit": commit.strip(),
                        "message": message.strip()[:80],
                        "type": commit_type,
                    })

            return changelog

        except Exception:
            return []

    def _format_uptime(self) -> str:
        """Format bot uptime as human-readable string."""
        if not self._start_time:
            return "Unknown"

        delta = datetime.now(NY_TZ) - self._start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}m")

        return " ".join(parts)

    # =========================================================================
    # Avatar Fetching
    # =========================================================================

    def _check_cache_refresh(self) -> None:
        """Clear avatar cache at midnight EST."""
        global _avatar_cache, _avatar_cache_date
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        if _avatar_cache_date != today:
            _avatar_cache.clear()
            _avatar_cache_date = today

    async def _fetch_user_data(self, user_id: int, fallback_name: str) -> tuple[str, Optional[str]]:
        """Fetch user name and avatar with caching."""
        self._check_cache_refresh()

        # Check cache
        if user_id in _avatar_cache:
            return _avatar_cache[user_id]

        try:
            # Try local cache first
            user = self._bot.get_user(user_id)
            if not user:
                user = await asyncio.wait_for(
                    self._bot.fetch_user(user_id),
                    timeout=2.0
                )

            name = user.display_name
            avatar = user.display_avatar.url if user.display_avatar else None

            _avatar_cache[user_id] = (name, avatar)
            return name, avatar

        except Exception:
            _avatar_cache[user_id] = (fallback_name, None)
            return fallback_name, None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AzabAPI"]
