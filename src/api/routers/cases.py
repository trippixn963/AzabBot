"""
AzabBot - Cases Router
======================

Moderation case management endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.auth import TokenPayload
from src.api.utils.discord import (
    batch_fetch_users,
    fetch_user_info,
    to_iso_string,
    format_duration,
    calculate_case_status,
    calculate_expires_at,
)
from src.core.database import get_db


router = APIRouter(prefix="/cases", tags=["Cases"])


# =============================================================================
# List & Search
# =============================================================================

@router.get("")
async def list_cases(
    bot: Any = Depends(get_bot),
    pagination: PaginationParams = Depends(get_pagination),
    case_type: Optional[str] = Query(None, description="Filter by case type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by user ID or case #"),
    time_range: Optional[str] = Query(None, description="Filter: today, week, month, all"),
    sort_by: Optional[str] = Query("created_at", description="Sort by: created_at, case_id, action_type, status"),
    sort_dir: Optional[str] = Query("desc", description="Sort direction: asc, desc"),
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    List moderation cases with pagination and filtering.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()

    # Build query conditions
    conditions = []
    params = []

    if case_type:
        conditions.append("action_type = ?")
        params.append(case_type)

    if status:
        if status == "active":
            conditions.append("status = 'active'")
        elif status == "resolved":
            conditions.append("status = 'resolved'")
        elif status == "appealed":
            conditions.append("case_id IN (SELECT case_id FROM appeals)")
        elif status == "expired":
            conditions.append("duration_seconds IS NOT NULL AND (created_at + duration_seconds) <= ?")
            params.append(now)
        elif status == "reversed":
            conditions.append("status = 'reversed'")

    if time_range:
        time_offsets = {"today": 0, "week": 7 * 86400, "month": 30 * 86400}
        if time_range in time_offsets:
            conditions.append("created_at >= ?")
            params.append(today_start - time_offsets[time_range])

    if search:
        conditions.append("(CAST(case_id AS TEXT) LIKE ? OR CAST(user_id AS TEXT) LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    total = db.fetchone(f"SELECT COUNT(*) FROM cases WHERE {where_clause}", params)[0]

    # Validate and build ORDER BY clause
    valid_sort_columns = {"created_at", "case_id", "action_type", "status", "user_id", "moderator_id"}
    sort_column = sort_by if sort_by in valid_sort_columns else "created_at"
    sort_direction = "ASC" if sort_dir and sort_dir.lower() == "asc" else "DESC"

    # Get page of results
    # Sort by status (active first, then expired/resolved), then by requested column
    query = f"""
        SELECT id, case_id, user_id, moderator_id, action_type, status, reason,
               duration_seconds, created_at, resolved_at
        FROM cases
        WHERE {where_clause}
        ORDER BY
            CASE status
                WHEN 'active' THEN 0
                WHEN 'expired' THEN 1
                ELSE 2
            END,
            {sort_column} {sort_direction}
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    # Batch fetch all user info
    all_user_ids = set()
    for row in rows:
        all_user_ids.add(row["user_id"])
        all_user_ids.add(row["moderator_id"])
    user_info = await batch_fetch_users(bot, list(all_user_ids))

    # Build response
    cases = []
    for row in rows:
        user_id = row["user_id"]
        mod_id = row["moderator_id"]
        user_name, user_avatar = user_info.get(user_id, (None, None))
        mod_name, mod_avatar = user_info.get(mod_id, (None, None))

        cases.append({
            "id": row["id"],
            "case_id": row["case_id"],
            "case_type": row["action_type"],
            "status": calculate_case_status(row["status"], row["duration_seconds"], row["created_at"], now),
            "user_id": str(user_id),
            "user_name": user_name or f"User {user_id}",
            "user_avatar": user_avatar,
            "moderator_id": str(mod_id),
            "moderator_name": mod_name or f"Mod {mod_id}",
            "moderator_avatar": mod_avatar,
            "reason": row["reason"] or "No reason provided",
            "created_at": to_iso_string(row["created_at"]),
            "expires_at": calculate_expires_at(row["duration_seconds"], row["created_at"]),
        })

    total_pages = (total + pagination.per_page - 1) // pagination.per_page

    logger.debug("Cases Listed", [
        ("User", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(cases))),
        ("Total", str(total)),
    ])

    return JSONResponse(content={
        "success": True,
        "data": {
            "cases": cases,
            "total": total,
            "total_pages": total_pages,
        }
    })


# =============================================================================
# Case Statistics
# =============================================================================

@router.get("/stats")
async def get_case_stats(
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get case statistics for dashboard cards.
    Uses optimized single-query approach.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()
    week_start = today_start - (7 * 86400)

    # Single optimized query for all case stats
    stats_row = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN action_type = 'mute' AND status = 'active'
                AND (duration_seconds IS NULL OR created_at + duration_seconds > ?)
                THEN 1 ELSE 0 END) as active_mutes,
            SUM(CASE WHEN action_type = 'ban' AND status = 'active'
                THEN 1 ELSE 0 END) as active_bans,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_today,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_this_week
        FROM cases
        """,
        (now, today_start, week_start)
    )

    # Separate query for appeals (different table)
    pending_appeals = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE status = 'pending'"
    )[0]

    response = {
        "success": True,
        "data": {
            "total_cases": stats_row[0] or 0,
            "active_mutes": stats_row[1] or 0,
            "active_bans": stats_row[2] or 0,
            "cases_today": stats_row[3] or 0,
            "cases_this_week": stats_row[4] or 0,
            "pending_appeals": pending_appeals,
        }
    }

    logger.debug("Case Stats Fetched", [
        ("User", str(payload.sub)),
        ("Total Cases", str(stats_row[0])),
        ("Active Mutes", str(stats_row[1])),
        ("Pending Appeals", str(pending_appeals)),
    ])

    return JSONResponse(content=response)


# =============================================================================
# Individual Case
# =============================================================================

@router.get("/{case_id}")
async def get_case(
    case_id: str,
    include_transcript: bool = Query(True, description="Include thread transcript"),
    transcript_limit: int = Query(100, ge=1, le=500, description="Max messages to return"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get detailed information about a specific case.
    """
    db = get_db()
    now = time.time()

    row = db.fetchone(
        """SELECT id, case_id, user_id, guild_id, thread_id, action_type, status,
                  moderator_id, reason, duration_seconds, evidence, created_at,
                  resolved_at, resolved_by, resolved_reason, evidence_urls, transcript
           FROM cases WHERE case_id = ?""",
        (case_id,)
    )

    if not row:
        logger.debug("Case Not Found", [
            ("Case ID", str(case_id)),
            ("User", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Case #{case_id} not found",
        )

    # Collect user IDs to fetch
    user_ids = [row["user_id"], row["moderator_id"]]
    if row["resolved_by"]:
        user_ids.append(row["resolved_by"])

    # Batch fetch user info
    user_info = await batch_fetch_users(bot, user_ids)

    user_name, user_avatar = user_info.get(row["user_id"], (None, None))
    mod_name, mod_avatar = user_info.get(row["moderator_id"], (None, None))

    # Parse evidence URLs
    evidence = []
    if row["evidence_urls"]:
        urls = row["evidence_urls"].split(",") if isinstance(row["evidence_urls"], str) else []
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        for i, url in enumerate(urls):
            url = url.strip()
            if url:
                evidence.append({
                    "id": i + 1,
                    "type": "image" if url.lower().endswith(image_extensions) else "link",
                    "content": url,
                    "added_by": mod_name or f"Mod {row['moderator_id']}",
                    "added_at": to_iso_string(row["created_at"]),
                })

    # Add text evidence if present
    if row["evidence"]:
        evidence.append({
            "id": len(evidence) + 1,
            "type": "text",
            "content": row["evidence"],
            "added_by": mod_name or f"Mod {row['moderator_id']}",
            "added_at": to_iso_string(row["created_at"]),
        })

    # Get appeal info if exists
    appeal = None
    appeal_row = db.fetchone(
        """SELECT id, status, reason, created_at, resolved_by, resolved_at, resolution_reason
           FROM appeals WHERE case_id = ? ORDER BY created_at DESC LIMIT 1""",
        (case_id,)
    )
    if appeal_row:
        reviewed_by_name = None
        if appeal_row["resolved_by"]:
            rb_info = user_info.get(appeal_row["resolved_by"])
            if rb_info:
                reviewed_by_name = rb_info[0]
            else:
                _, reviewed_by_name, _ = await fetch_user_info(bot, appeal_row["resolved_by"])

        appeal = {
            "id": appeal_row["id"],
            "status": appeal_row["status"],
            "reason": appeal_row["reason"],
            "submitted_at": to_iso_string(appeal_row["created_at"]),
            "reviewed_by": reviewed_by_name,
            "reviewed_at": to_iso_string(appeal_row["resolved_at"]),
            "response": appeal_row["resolution_reason"],
        }

    # Get related cases (same user)
    related_rows = db.fetchall(
        """SELECT case_id FROM cases
           WHERE user_id = ? AND case_id != ?
           ORDER BY created_at DESC LIMIT 5""",
        (row["user_id"], case_id)
    )
    related_cases = [r["case_id"] for r in related_rows]

    # Parse transcript if available and requested
    transcript = None
    if include_transcript and row["transcript"]:
        try:
            transcript_data = json.loads(row["transcript"])
            raw_messages = transcript_data.get("messages", [])

            # Format messages for frontend
            messages = []
            for msg in raw_messages:
                content = msg.get("content", "")
                attachments = msg.get("attachments", [])
                embeds = msg.get("embeds", [])

                # Build embed summary if present (for bot messages with embeds)
                embed_text = ""
                if embeds and not content:
                    for embed in embeds[:1]:  # Just first embed
                        if embed.get("title"):
                            embed_text = f"[{embed.get('title')}]"
                            break

                # Skip completely empty messages
                if not content and not attachments and not embed_text:
                    continue

                messages.append({
                    "id": msg.get("message_id"),
                    "author_id": str(msg.get("author_id")),
                    "author_name": msg.get("author_display_name") or msg.get("author_name"),
                    "author_avatar": msg.get("author_avatar_url"),
                    "content": content or embed_text,
                    "timestamp": to_iso_string(msg.get("timestamp")),
                    "attachments": attachments,
                    "is_bot": msg.get("author_name") == "Azab",
                })

            # Apply limit
            total_messages = len(messages)
            messages = messages[:transcript_limit]

            transcript = {
                "thread_id": str(transcript_data.get("thread_id")),
                "thread_name": transcript_data.get("thread_name"),
                "message_count": len(messages),
                "total_messages": total_messages,
                "has_more": total_messages > transcript_limit,
                "messages": messages,
            }
        except (json.JSONDecodeError, TypeError):
            pass

    updated_at = row["resolved_at"] or row["created_at"]

    response = {
        "success": True,
        "data": {
            "id": row["id"],
            "case_id": row["case_id"],
            "case_type": row["action_type"],
            "status": calculate_case_status(row["status"], row["duration_seconds"], row["created_at"], now),
            "user_id": str(row["user_id"]),
            "user_name": user_name or f"User {row['user_id']}",
            "user_avatar": user_avatar,
            "moderator_id": str(row["moderator_id"]),
            "moderator_name": mod_name or f"Mod {row['moderator_id']}",
            "moderator_avatar": mod_avatar,
            "reason": row["reason"] or "No reason provided",
            "duration": format_duration(row["duration_seconds"]),
            "created_at": to_iso_string(row["created_at"]),
            "updated_at": to_iso_string(updated_at),
            "expires_at": calculate_expires_at(row["duration_seconds"], row["created_at"]),
            "notes": row["resolved_reason"],
            "evidence": evidence,
            "appeal": appeal,
            "related_cases": related_cases,
            "transcript": transcript,
        }
    }

    logger.debug("Case Fetched", [
        ("Case ID", str(case_id)),
        ("User", str(payload.sub)),
        ("Type", row["action_type"]),
    ])

    return JSONResponse(content=response)


__all__ = ["router"]
