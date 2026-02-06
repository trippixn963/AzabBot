"""
AzabBot - Transcripts Router
============================

Ticket transcript endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.core.database import get_db


router = APIRouter(prefix="/transcripts", tags=["Transcripts"])


@router.get("/{ticket_id}", response_class=HTMLResponse)
async def get_transcript(ticket_id: str):
    """
    Get HTML transcript for a ticket.

    This is a public endpoint (no auth required) for viewing transcripts.
    The ticket ID acts as authentication since it's not guessable.
    """
    from src.core.config import NY_TZ

    ticket_id = ticket_id.upper()
    db = get_db()

    # Get ticket
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        logger.debug("Transcript Not Found", [
            ("Ticket ID", ticket_id),
        ])
        return HTMLResponse(
            f"<h1>404 - Ticket Not Found</h1><p>No ticket found with ID {ticket_id}</p>",
            status_code=404,
        )

    # Get stored messages
    stored_messages = db.get_ticket_messages(ticket_id)

    # Try legacy transcript if no stored messages
    if not stored_messages:
        html_content = db.get_ticket_transcript(ticket_id)
        if html_content:
            logger.debug("Transcript Served (Legacy)", [
                ("Ticket ID", ticket_id),
            ])
            return HTMLResponse(
                html_content,
                headers={"Cache-Control": "public, max-age=60"},
            )
        logger.debug("Transcript Empty", [
            ("Ticket ID", ticket_id),
        ])
        return HTMLResponse(
            f"<h1>404 - Transcript Not Found</h1><p>No messages found for ticket {ticket_id}</p>",
            status_code=404,
        )

    # Generate transcript
    from src.services.tickets.transcript import generate_html_transcript

    messages = []
    mention_map = {}

    for msg in stored_messages:
        mention_map[msg["author_id"]] = msg["author_display_name"]

        try:
            ts = datetime.fromtimestamp(msg["timestamp"], tz=NY_TZ)
            timestamp_str = ts.strftime("%b %d, %Y %I:%M %p")
        except Exception:
            timestamp_str = "Unknown"

        messages.append({
            "author_id": msg["author_id"],
            "author_name": msg["author_display_name"],
            "author_avatar": msg.get("author_avatar"),
            "content": msg["content"],
            "timestamp": timestamp_str,
            "attachments": msg.get("attachments", []),
            "embeds": msg.get("embeds", []),
            "is_bot": msg.get("is_bot", False),
        })

    ticket_info = {
        "ticket_id": ticket_id,
        "created_at": ticket.get("created_at"),
        "closed_at": ticket.get("closed_at"),
        "user_id": ticket.get("user_id"),
    }

    html_content = generate_html_transcript(
        messages=messages,
        ticket_info=ticket_info,
        mention_map=mention_map,
    )

    logger.debug("Transcript Served", [
        ("Ticket ID", ticket_id),
        ("Messages", str(len(messages))),
    ])

    return HTMLResponse(
        html_content,
        headers={"Cache-Control": "public, max-age=60"},
    )


__all__ = ["router"]
