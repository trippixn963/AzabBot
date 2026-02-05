"""
Moderation Dashboard Handlers
==============================

Protected API endpoints for the moderation dashboard.

Author: John Hamwi
"""

from typing import TYPE_CHECKING

from aiohttp import web

from src.core.config import get_config
from src.core.database import get_db
from src.core.logger import logger

from .mod_auth import get_auth_manager, extract_bearer_token

if TYPE_CHECKING:
    from .service import AzabAPI


# =============================================================================
# Constants
# =============================================================================

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


# =============================================================================
# Helper Functions
# =============================================================================

def _require_auth(request: web.Request) -> bool:
    """
    Check if request has valid authentication.

    Args:
        request: The incoming request.

    Returns:
        True if authenticated, False otherwise.
    """
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    if not token:
        return False
    return get_auth_manager().validate_token(token)


def _get_pagination(request: web.Request) -> tuple[int, int]:
    """
    Extract pagination parameters from request.

    Args:
        request: The incoming request.

    Returns:
        Tuple of (page, limit).
    """
    try:
        page = max(1, int(request.query.get("page", 1)))
    except ValueError:
        page = 1

    try:
        limit = min(MAX_PAGE_SIZE, max(1, int(request.query.get("limit", DEFAULT_PAGE_SIZE))))
    except ValueError:
        limit = DEFAULT_PAGE_SIZE

    return page, limit


def _cors_headers() -> dict:
    """Return CORS headers for responses."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
    }


async def _get_user_info(bot, user_id: int) -> dict:
    """
    Get user info from Discord.

    Args:
        bot: The Discord bot instance.
        user_id: Discord user ID.

    Returns:
        Dict with username and avatar_url.
    """
    try:
        user = await bot.fetch_user(user_id)
        return {
            "username": user.display_name,
            "avatar_url": str(user.display_avatar.url) if user.display_avatar else None,
        }
    except Exception:
        return {
            "username": f"User {user_id}",
            "avatar_url": None,
        }


# =============================================================================
# Mixin Class
# =============================================================================

class ModHandlersMixin:
    """Mixin for moderation dashboard HTTP endpoints."""

    async def handle_mod_auth(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Authenticate a moderator and return a session token.

        POST /api/azab/mod/auth
        Body: {"password": "..."}
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON"},
                status=400,
                headers=_cors_headers()
            )

        password = data.get("password", "")
        if not password:
            return web.json_response(
                {"success": False, "error": "Password required"},
                status=400,
                headers=_cors_headers()
            )

        auth_manager = get_auth_manager()
        if not auth_manager.verify_password(password):
            logger.warning("Mod Dashboard: Failed login attempt")
            return web.json_response(
                {"success": False, "error": "Invalid password"},
                status=401,
                headers=_cors_headers()
            )

        token = auth_manager.create_token()
        return web.json_response(
            {"success": True, "token": token},
            headers=_cors_headers()
        )

    async def handle_mod_auth_options(self: "AzabAPI", request: web.Request) -> web.Response:
        """Handle CORS preflight for auth endpoint."""
        return web.Response(status=204, headers=_cors_headers())

    async def handle_mod_logout(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Logout and revoke session token.

        POST /api/azab/mod/logout
        """
        auth_header = request.headers.get("Authorization")
        token = extract_bearer_token(auth_header)

        if token:
            get_auth_manager().revoke_token(token)

        return web.json_response(
            {"success": True},
            headers=_cors_headers()
        )

    async def handle_mod_cases(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        List all cases with pagination.

        GET /api/azab/mod/cases
        Query: ?page=1&limit=50&status=open|closed|all
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        page, limit = _get_pagination(request)
        status_filter = request.query.get("status", "all")
        offset = (page - 1) * limit

        db = get_db()
        config = get_config()
        guild_id = config.logging_guild_id

        # Build query based on status filter
        if status_filter == "open":
            where_clause = "WHERE status = 'open'"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"
        elif status_filter == "closed":
            where_clause = "WHERE status = 'resolved'"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"
        else:
            where_clause = "WHERE status != 'archived'"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"

        # Get total count
        count_row = db.fetchone(f"SELECT COUNT(*) as count FROM cases {where_clause}")
        total = count_row["count"] if count_row else 0

        # Get cases
        rows = db.fetchall(
            f"""SELECT * FROM cases
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            (limit, offset)
        )

        cases = []
        for row in rows:
            case = dict(row)

            # Get user info
            user_info = await _get_user_info(self._bot, case["user_id"])

            # Get moderator info
            mod_info = await _get_user_info(self._bot, case["moderator_id"])

            cases.append({
                "case_id": case["case_id"],
                "user_id": str(case["user_id"]),
                "username": user_info["username"],
                "action": case["action_type"],
                "reason": case.get("reason"),
                "moderator_id": str(case["moderator_id"]),
                "moderator_name": mod_info["username"],
                "status": case["status"],
                "created_at": case["created_at"],
                "thread_id": str(case["thread_id"]),
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1

        logger.tree("Mod Dashboard: Cases List", [
            ("Page", f"{page}/{pages}"),
            ("Filter", status_filter),
            ("Results", str(len(cases))),
        ], emoji="📋")

        return web.json_response({
            "cases": cases,
            "total": total,
            "page": page,
            "pages": pages,
        }, headers=_cors_headers())

    async def handle_mod_case_detail(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Get details for a single case.

        GET /api/azab/mod/cases/{case_id}
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        case_id = request.match_info.get("case_id", "").upper()
        if not case_id:
            return web.json_response(
                {"error": "Case ID required"},
                status=400,
                headers=_cors_headers()
            )

        db = get_db()
        case = db.get_case(case_id)

        if not case:
            return web.json_response(
                {"error": "Case not found"},
                status=404,
                headers=_cors_headers()
            )

        # Get user info
        user_info = await _get_user_info(self._bot, case["user_id"])

        # Get moderator info
        mod_info = await _get_user_info(self._bot, case["moderator_id"])

        # Get evidence
        evidence_urls = db.get_case_evidence(case_id)

        # Build thread URL
        config = get_config()
        guild_id = config.logging_guild_id or case.get("guild_id", 0)
        thread_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}" if case.get("thread_id") else None

        result = {
            "case_id": case["case_id"],
            "user_id": str(case["user_id"]),
            "username": user_info["username"],
            "avatar_url": user_info["avatar_url"],
            "action": case["action_type"],
            "reason": case.get("reason"),
            "evidence": evidence_urls,
            "moderator_id": str(case["moderator_id"]),
            "moderator_name": mod_info["username"],
            "status": case["status"],
            "created_at": case["created_at"],
            "resolved_at": case.get("resolved_at"),
            "resolved_by": str(case["resolved_by"]) if case.get("resolved_by") else None,
            "resolved_reason": case.get("resolved_reason"),
            "thread_id": str(case["thread_id"]),
            "thread_url": thread_url,
            "duration_seconds": case.get("duration_seconds"),
        }

        logger.tree("Mod Dashboard: Case Detail", [
            ("Case ID", case_id),
            ("Status", case["status"]),
        ], emoji="📋")

        return web.json_response(result, headers=_cors_headers())

    async def handle_mod_tickets(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        List all tickets with pagination.

        GET /api/azab/mod/tickets
        Query: ?page=1&limit=50&status=open|closed|all
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        page, limit = _get_pagination(request)
        status_filter = request.query.get("status", "all")
        offset = (page - 1) * limit

        db = get_db()
        config = get_config()
        guild_id = config.logging_guild_id

        # Build query based on status filter
        if status_filter == "open":
            where_clause = "WHERE status IN ('open', 'claimed')"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"
        elif status_filter == "closed":
            where_clause = "WHERE status = 'closed'"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"
        else:
            where_clause = "WHERE 1=1"
            if guild_id:
                where_clause += f" AND guild_id = {guild_id}"

        # Get total count
        count_row = db.fetchone(f"SELECT COUNT(*) as count FROM tickets {where_clause}")
        total = count_row["count"] if count_row else 0

        # Get tickets
        rows = db.fetchall(
            f"""SELECT * FROM tickets
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            (limit, offset)
        )

        tickets = []
        for row in rows:
            ticket = dict(row)

            # Get user info
            user_info = await _get_user_info(self._bot, ticket["user_id"])

            # Get claimer info if claimed
            claimed_by_name = None
            if ticket.get("claimed_by"):
                claimer_info = await _get_user_info(self._bot, ticket["claimed_by"])
                claimed_by_name = claimer_info["username"]

            # Get message count
            message_count = db.get_ticket_message_count(ticket["ticket_id"])

            tickets.append({
                "ticket_id": ticket["ticket_id"],
                "user_id": str(ticket["user_id"]),
                "username": user_info["username"],
                "category": ticket.get("category", "support"),
                "subject": ticket.get("subject", "No subject"),
                "status": ticket["status"],
                "claimed_by": claimed_by_name,
                "created_at": ticket["created_at"],
                "message_count": message_count,
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1

        logger.tree("Mod Dashboard: Tickets List", [
            ("Page", f"{page}/{pages}"),
            ("Filter", status_filter),
            ("Results", str(len(tickets))),
        ], emoji="🎫")

        return web.json_response({
            "tickets": tickets,
            "total": total,
            "page": page,
            "pages": pages,
        }, headers=_cors_headers())

    async def handle_mod_ticket_detail(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Get details for a single ticket.

        GET /api/azab/mod/tickets/{ticket_id}
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        ticket_id = request.match_info.get("ticket_id", "").upper()
        if not ticket_id:
            return web.json_response(
                {"error": "Ticket ID required"},
                status=400,
                headers=_cors_headers()
            )

        db = get_db()
        ticket = db.get_ticket(ticket_id)

        if not ticket:
            return web.json_response(
                {"error": "Ticket not found"},
                status=404,
                headers=_cors_headers()
            )

        # Get user info
        user_info = await _get_user_info(self._bot, ticket["user_id"])

        # Get claimer info if claimed
        claimed_by_name = None
        if ticket.get("claimed_by"):
            claimer_info = await _get_user_info(self._bot, ticket["claimed_by"])
            claimed_by_name = claimer_info["username"]

        # Get message count
        message_count = db.get_ticket_message_count(ticket_id)

        # Build transcript URL
        config = get_config()
        transcript_url = None
        if config.transcript_base_url:
            transcript_url = f"{config.transcript_base_url}/{ticket_id}"

        result = {
            "ticket_id": ticket["ticket_id"],
            "user_id": str(ticket["user_id"]),
            "username": user_info["username"],
            "avatar_url": user_info["avatar_url"],
            "category": ticket.get("category", "support"),
            "subject": ticket.get("subject", "No subject"),
            "status": ticket["status"],
            "priority": ticket.get("priority", "normal"),
            "claimed_by_id": str(ticket["claimed_by"]) if ticket.get("claimed_by") else None,
            "claimed_by_name": claimed_by_name,
            "created_at": ticket["created_at"],
            "closed_at": ticket.get("closed_at"),
            "closed_by": str(ticket["closed_by"]) if ticket.get("closed_by") else None,
            "close_reason": ticket.get("close_reason"),
            "message_count": message_count,
            "transcript_url": transcript_url,
        }

        logger.tree("Mod Dashboard: Ticket Detail", [
            ("Ticket ID", ticket_id),
            ("Status", ticket["status"]),
        ], emoji="🎫")

        return web.json_response(result, headers=_cors_headers())

    async def handle_mod_user(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Lookup a user's moderation history.

        GET /api/azab/mod/users/{user_id}
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        user_id_str = request.match_info.get("user_id", "")
        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response(
                {"error": "Invalid user ID"},
                status=400,
                headers=_cors_headers()
            )

        db = get_db()
        config = get_config()
        guild_id = config.logging_guild_id

        # Get user info from Discord
        user_info = await _get_user_info(self._bot, user_id)

        # Get punishment counts
        mutes = db.fetchone(
            "SELECT COUNT(*) as c FROM mute_history WHERE user_id = ? AND action = 'mute'" +
            (f" AND guild_id = {guild_id}" if guild_id else ""),
            (user_id,)
        )
        bans = db.fetchone(
            "SELECT COUNT(*) as c FROM ban_history WHERE user_id = ? AND action = 'ban'" +
            (f" AND guild_id = {guild_id}" if guild_id else ""),
            (user_id,)
        )
        warns = db.fetchone(
            "SELECT COUNT(*) as c FROM warnings WHERE user_id = ?" +
            (f" AND guild_id = {guild_id}" if guild_id else ""),
            (user_id,)
        )
        timeouts = db.fetchone(
            "SELECT COUNT(*) as c FROM timeout_history WHERE user_id = ? AND action = 'timeout'" +
            (f" AND guild_id = {guild_id}" if guild_id else ""),
            (user_id,)
        )
        kicks = db.fetchone(
            "SELECT COUNT(*) as c FROM kick_history WHERE user_id = ?" +
            (f" AND guild_id = {guild_id}" if guild_id else ""),
            (user_id,)
        )

        punishment_summary = {
            "mutes": mutes["c"] if mutes else 0,
            "bans": bans["c"] if bans else 0,
            "warns": warns["c"] if warns else 0,
            "timeouts": timeouts["c"] if timeouts else 0,
            "kicks": kicks["c"] if kicks else 0,
        }

        # Get recent cases
        cases_query = """SELECT * FROM cases WHERE user_id = ?"""
        if guild_id:
            cases_query += f" AND guild_id = {guild_id}"
        cases_query += " ORDER BY created_at DESC LIMIT 10"

        case_rows = db.fetchall(cases_query, (user_id,))
        recent_cases = []
        for row in case_rows:
            case = dict(row)
            mod_info = await _get_user_info(self._bot, case["moderator_id"])
            recent_cases.append({
                "case_id": case["case_id"],
                "action": case["action_type"],
                "reason": case.get("reason"),
                "moderator_name": mod_info["username"],
                "status": case["status"],
                "created_at": case["created_at"],
            })

        # Get recent tickets
        tickets_query = """SELECT * FROM tickets WHERE user_id = ?"""
        if guild_id:
            tickets_query += f" AND guild_id = {guild_id}"
        tickets_query += " ORDER BY created_at DESC LIMIT 10"

        ticket_rows = db.fetchall(tickets_query, (user_id,))
        recent_tickets = []
        for row in ticket_rows:
            ticket = dict(row)
            recent_tickets.append({
                "ticket_id": ticket["ticket_id"],
                "category": ticket.get("category", "support"),
                "subject": ticket.get("subject", "No subject"),
                "status": ticket["status"],
                "created_at": ticket["created_at"],
            })

        result = {
            "user_id": str(user_id),
            "username": user_info["username"],
            "avatar_url": user_info["avatar_url"],
            "punishment_summary": punishment_summary,
            "recent_cases": recent_cases,
            "recent_tickets": recent_tickets,
        }

        logger.tree("Mod Dashboard: User Lookup", [
            ("User ID", str(user_id)),
            ("Username", user_info["username"]),
            ("Total Punishments", str(sum(punishment_summary.values()))),
        ], emoji="👤")

        return web.json_response(result, headers=_cors_headers())

    async def handle_mod_stats(self: "AzabAPI", request: web.Request) -> web.Response:
        """
        Get overview statistics for the dashboard.

        GET /api/azab/mod/stats
        """
        if not _require_auth(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
                headers=_cors_headers()
            )

        db = get_db()
        config = get_config()
        guild_id = config.logging_guild_id

        # Get counts
        open_cases = db.get_open_cases_count(guild_id)
        total_cases = db.get_total_cases(guild_id)

        # Get open tickets count
        open_tickets_row = db.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE status IN ('open', 'claimed')" +
            (f" AND guild_id = {guild_id}" if guild_id else "")
        )
        open_tickets = open_tickets_row["c"] if open_tickets_row else 0

        # Get total tickets count
        total_tickets_row = db.fetchone(
            "SELECT COUNT(*) as c FROM tickets" +
            (f" WHERE guild_id = {guild_id}" if guild_id else "")
        )
        total_tickets = total_tickets_row["c"] if total_tickets_row else 0

        # Get active prisoners
        active_prisoners = db.get_active_prisoners_count(guild_id)

        result = {
            "open_cases": open_cases,
            "total_cases": total_cases,
            "open_tickets": open_tickets,
            "total_tickets": total_tickets,
            "active_prisoners": active_prisoners,
        }

        return web.json_response(result, headers=_cors_headers())

    async def handle_mod_options(self: "AzabAPI", request: web.Request) -> web.Response:
        """Handle CORS preflight for all mod endpoints."""
        return web.Response(status=204, headers=_cors_headers())


__all__ = ["ModHandlersMixin"]
