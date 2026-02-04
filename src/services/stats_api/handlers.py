"""
AzabBot - Handlers Mixin
========================

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
from src.core.constants import QUERY_LIMIT_SMALL, QUERY_LIMIT_MEDIUM, QUERY_LIMIT_LARGE

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
            # Get permanent counter for total closed (survives ticket deletion)
            total_tickets_closed = self._bot.db.get_total_tickets_closed(guild_id) if guild_id else 0
            # Combine open + claimed as "open" for dashboard (both are active tickets)
            # Use permanent counter for closed if it's higher than current DB count
            tickets = {
                "open": tickets_raw.get("open", 0) + tickets_raw.get("claimed", 0),
                "closed": max(tickets_raw.get("closed", 0), total_tickets_closed),
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
            mods_raw = self._bot.db.get_moderator_leaderboard(limit=QUERY_LIMIT_MEDIUM, exclude_user_id=bot_user_id)

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

            # Get member activity (join/leave history)
            activity = self._bot.db.get_member_activity(user_id, guild_id) if guild_id else None
            join_count = activity["join_count"] if activity else 0
            leave_count = activity["leave_count"] if activity else 0
            first_joined_at = activity["first_joined_at"] if activity else None

            # Get spam violations (method returns dict with defaults, never None)
            spam_violations = self._bot.db.get_spam_violations(user_id, guild_id)["violation_count"] if guild_id else 0

            # Get username/nickname history
            previous_names = self._bot.db.get_previous_names(user_id, limit=5)
            nickname_history = self._bot.db.get_all_nicknames(user_id, guild_id) if guild_id else []

            # Get user info from Discord
            name, avatar, _ = await self._fetch_user_data(user_id, f"User {user_id}")

            # Get rank among offenders
            top_offenders = self._bot.db.get_top_offenders(limit=QUERY_LIMIT_LARGE, guild_id=guild_id)
            rank = next(
                (i + 1 for i, o in enumerate(top_offenders) if o["user_id"] == user_id),
                None
            )

            # Get recent punishments for this user
            recent_punishments = await self._get_user_recent_punishments(user_id, guild_id, limit=QUERY_LIMIT_SMALL)

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
                "join_count": join_count,
                "leave_count": leave_count,
                "first_joined_at": first_joined_at,
                "spam_violations": spam_violations,
                "previous_names": previous_names,
                "nickname_history": nickname_history,
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
            mod_leaderboard = self._bot.db.get_moderator_leaderboard(limit=QUERY_LIMIT_LARGE)
            rank = next(
                (i + 1 for i, m in enumerate(mod_leaderboard) if m["moderator_id"] == user_id),
                None
            )

            # Get recent actions by this moderator
            recent_actions = await self._get_moderator_recent_actions(user_id, guild_id, limit=QUERY_LIMIT_SMALL)

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
    # Appeal Web Endpoints
    # =========================================================================

    async def handle_appeal_get(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        GET /api/azab/appeal/{token}

        Validate token and return case info for the appeal form.
        """
        token = request.match_info.get("token", "")
        client_ip = get_client_ip(request)

        if not token:
            return web.json_response(
                {"error": "Missing appeal token"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Validate token
        from src.services.appeals.tokens import validate_appeal_token
        is_valid, payload, error = validate_appeal_token(token)

        if not is_valid:
            logger.warning("Appeal Token Validation Failed", [
                ("Client IP", client_ip),
                ("Error", error or "Unknown"),
            ])
            return web.json_response(
                {"error": error or "Invalid appeal link"},
                status=401,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        case_id = payload["case_id"]
        user_id = payload["user_id"]

        logger.info("Appeal Page Requested", [
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Client IP", client_ip),
        ])

        # Get case info
        case = self._bot.db.get_appealable_case(case_id)
        if not case:
            return web.json_response(
                {"error": "Case not found"},
                status=404,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Verify user matches case
        if case["user_id"] != user_id:
            logger.warning("Appeal User Mismatch", [
                ("Case ID", case_id),
                ("Token User ID", str(user_id)),
                ("Case User ID", str(case["user_id"])),
            ])
            return web.json_response(
                {"error": "Invalid appeal link"},
                status=403,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Check if already appealed (get existing appeal status)
        existing_appeal = self._bot.db.get_appeal_by_case(case_id)
        appeal_status = None
        if existing_appeal:
            appeal_status = {
                "appeal_id": existing_appeal.get("appeal_id"),
                "status": existing_appeal.get("status", "pending"),
                "submitted_at": existing_appeal.get("created_at"),
                "resolved_at": existing_appeal.get("resolved_at"),
                "resolution": existing_appeal.get("resolution"),
                "resolution_reason": existing_appeal.get("resolution_reason"),
            }

        # Check eligibility
        if self._bot.appeal_service:
            can_appeal, reason, _ = self._bot.appeal_service.can_appeal(case_id)
        else:
            can_appeal = False
            reason = "Appeal system is not available"

        # Format moderator name
        mod_id = case.get("moderator_id")
        mod_name = "Unknown Moderator"
        if mod_id:
            try:
                mod = await self._bot.fetch_user(mod_id)
                mod_name = mod.display_name if mod else f"User {mod_id}"
            except Exception:
                mod_name = f"User {mod_id}"

        # Build response
        response = {
            "case_id": case_id,
            "user_id": str(user_id),
            "action_type": case.get("action_type", "unknown"),
            "reason": case.get("reason", "No reason provided"),
            "moderator": mod_name,
            "created_at": case.get("created_at"),
            "duration_seconds": case.get("duration_seconds"),
            "can_appeal": can_appeal,
            "appeal_blocked_reason": reason if not can_appeal else None,
            "existing_appeal": appeal_status,
        }

        return web.json_response(
            response,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    async def handle_appeal_post(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        POST /api/azab/appeal/{token}

        Submit an appeal for a ban/mute case.
        """
        token = request.match_info.get("token", "")
        client_ip = get_client_ip(request)

        if not token:
            return web.json_response(
                {"error": "Missing appeal token"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Validate token
        from src.services.appeals.tokens import validate_appeal_token
        is_valid, payload, error = validate_appeal_token(token)

        if not is_valid:
            logger.warning("Appeal Submit Token Invalid", [
                ("Client IP", client_ip),
                ("Error", error or "Unknown"),
            ])
            return web.json_response(
                {"error": error or "Invalid appeal link"},
                status=401,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        case_id = payload["case_id"]
        user_id = payload["user_id"]

        # Parse request body
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid request body"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        appeal_reason = body.get("reason", "").strip()

        # Validate appeal reason
        if not appeal_reason:
            return web.json_response(
                {"error": "Appeal reason is required"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        if len(appeal_reason) < 20:
            return web.json_response(
                {"error": "Appeal reason must be at least 20 characters"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        if len(appeal_reason) > 1000:
            return web.json_response(
                {"error": "Appeal reason must be under 1000 characters"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        logger.info("Appeal Submission", [
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Client IP", client_ip),
            ("Reason Length", str(len(appeal_reason))),
        ])

        # Check appeal service
        if not self._bot.appeal_service:
            return web.json_response(
                {"error": "Appeal system is not available"},
                status=503,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Get case to verify user
        case = self._bot.db.get_appealable_case(case_id)
        if not case:
            return web.json_response(
                {"error": "Case not found"},
                status=404,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        if case["user_id"] != user_id:
            return web.json_response(
                {"error": "Invalid appeal link"},
                status=403,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Fetch user from Discord
        try:
            user = await self._bot.fetch_user(user_id)
        except Exception as e:
            logger.error("Failed to fetch user for appeal", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return web.json_response(
                {"error": "Failed to verify user"},
                status=500,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # Submit appeal
        success, message, appeal_id = await self._bot.appeal_service.create_appeal(
            case_id=case_id,
            user=user,
            reason=appeal_reason,
        )

        if success:
            logger.success("Web Appeal Submitted", [
                ("Case ID", case_id),
                ("Appeal ID", appeal_id),
                ("User ID", str(user_id)),
                ("Client IP", client_ip),
            ])
            return web.json_response(
                {
                    "success": True,
                    "message": "Your appeal has been submitted successfully.",
                    "appeal_id": appeal_id,
                },
                headers={"Access-Control-Allow-Origin": "*"}
            )
        else:
            logger.warning("Web Appeal Failed", [
                ("Case ID", case_id),
                ("User ID", str(user_id)),
                ("Reason", message),
            ])
            return web.json_response(
                {"error": message},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

    async def handle_appeal_options(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        OPTIONS /api/azab/appeal/{token}

        Handle CORS preflight requests.
        """
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            }
        )


__all__ = ["HandlersMixin"]
