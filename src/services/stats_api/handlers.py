"""
Stats API - Handlers Mixin
==========================

HTTP endpoint handlers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import TYPE_CHECKING

from aiohttp import web

from src.core.config import NY_TZ
from src.core.logger import logger

from .middleware import get_client_ip

if TYPE_CHECKING:
    from .service import AzabAPI


class HandlersMixin:
    """Mixin for HTTP endpoint handlers."""

    async def handle_health(self: "AzabAPI", request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "bot": "Azab",
            "connected": self._bot.is_ready(),
            "timestamp": datetime.now(NY_TZ).isoformat()
        })

    async def handle_transcript(self: "AzabAPI", request: web.Request) -> web.Response:
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

    async def handle_stats(self: "AzabAPI", request: web.Request) -> web.Response:
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
            tickets_raw = self._bot.db.get_ticket_stats(guild_id) if guild_id else {"open": 0, "claimed": 0, "closed": 0}
            # Combine open + claimed as "open" for dashboard (both are active tickets)
            tickets = {
                "open": tickets_raw.get("open", 0) + tickets_raw.get("claimed", 0),
                "closed": tickets_raw.get("closed", 0),
            }
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

    async def handle_leaderboard(self: "AzabAPI", request: web.Request) -> web.Response:
        """GET /api/azab/leaderboard - Return moderator leaderboard."""
        start_time = time.time()
        client_ip = request.headers.get("X-Forwarded-For", "unknown").split(",")[0].strip()

        logger.info("Leaderboard API Request", [
            ("Client IP", client_ip),
            ("Path", "/api/azab/leaderboard"),
        ])

        # Check cache
        cached = await self._cache.get("leaderboard")
        if cached:
            cached["response_time_ms"] = round((time.time() - start_time) * 1000, 1)
            cached["cached"] = True
            return web.json_response(cached, headers={"Access-Control-Allow-Origin": "*"})

        try:
            # Get moderator leaderboard from database (exclude bot)
            bot_user_id = self._bot.user.id if self._bot.user else None
            mods_raw = self._bot.db.get_moderator_leaderboard(limit=50, exclude_user_id=bot_user_id)

            # Build enriched leaderboard
            leaderboard = []
            for i, mod in enumerate(mods_raw, 1):
                mod_id = mod["moderator_id"]
                name, avatar, is_booster = await self._fetch_user_data(mod_id, f"Mod {mod_id}")
                leaderboard.append({
                    "rank": i,
                    "user_id": str(mod_id),
                    "name": name,
                    "avatar": avatar,
                    "actions": mod.get("total_actions", 0),
                    "mutes": mod.get("mutes", 0),
                    "bans": mod.get("bans", 0),
                    "warns": mod.get("warns", 0),
                    "is_booster": is_booster,
                })

            # Get totals
            total_mutes = self._bot.db.get_total_mutes()
            total_bans = self._bot.db.get_total_bans()
            total_warns = self._bot.db.get_total_warns()

            response = {
                "leaderboard": leaderboard,
                "total_moderators": len(leaderboard),
                "total_actions": total_mutes + total_bans + total_warns,
                "generated_at": datetime.now(NY_TZ).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 1),
                "cached": False,
            }

            # Cache for 30 seconds
            await self._cache.set("leaderboard", response)

            logger.info("Leaderboard API Response", [
                ("Moderators", str(len(leaderboard))),
                ("Response Time", f"{response['response_time_ms']}ms"),
            ])

            return web.json_response(
                response,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        except Exception as e:
            logger.error("Leaderboard API Error", [("Error", str(e)[:100])])
            return web.json_response(
                {"error": "Internal server error"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )

    async def handle_user(self: "AzabAPI", request: web.Request) -> web.Response:
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
            name, avatar, _ = await self._fetch_user_data(user_id, f"User {user_id}")

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

    async def handle_moderator(self: "AzabAPI", request: web.Request) -> web.Response:
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
            name, avatar, _ = await self._fetch_user_data(user_id, f"Mod {user_id}")

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


__all__ = ["HandlersMixin"]
