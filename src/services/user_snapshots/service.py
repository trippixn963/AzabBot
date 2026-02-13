"""
AzabBot - User Snapshots Service
================================

Centralized service for managing user snapshots.
Preserves user profile data (nickname, roles, avatar) for banned/left users.
Activity data is NOT snapshotted - SyriaBot retains it for inactive users.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
from typing import Optional, List, Dict, Any

import discord

from src.core.logger import logger
from src.core.database import get_db


def save_member_snapshot(
    member: discord.Member,
    reason: str = "lookup",
) -> bool:
    """
    Save a snapshot of member profile data for future lookups.

    Called when:
    - A member leaves the server (reason="leave")
    - A member is banned (reason="ban")
    - A member is muted (reason="mute")
    - A member is kicked (reason="kick")
    - A member is looked up via dashboard (reason="lookup")

    Note: Activity data (messages, voice time) is NOT saved here.
    SyriaBot retains activity data for inactive users.

    Args:
        member: Discord member object with full data
        reason: Why snapshot was taken

    Returns:
        True if saved successfully
    """
    try:
        db = get_db()

        # Build roles data
        roles_data = _extract_roles(member)

        # Extract timestamps
        joined_at = member.joined_at.timestamp() if member.joined_at else None
        account_created_at = member.created_at.timestamp() if member.created_at else None
        avatar_url = str(member.display_avatar.url) if member.display_avatar else None

        success = db.save_user_snapshot(
            user_id=member.id,
            guild_id=member.guild.id,
            username=member.name,
            display_name=member.display_name or member.name,
            nickname=member.nick,
            avatar_url=avatar_url,
            roles=roles_data,
            joined_at=joined_at,
            account_created_at=account_created_at,
            reason=reason,
        )

        if success:
            logger.tree("User Snapshot Saved", [
                ("User ID", str(member.id)),
                ("Username", member.name),
                ("Reason", reason),
                ("Roles", str(len(roles_data))),
                ("Has Nickname", "Yes" if member.nick else "No"),
            ], emoji="📸")

        return success

    except Exception as e:
        logger.error("User Snapshot Save Failed", [
            ("User ID", str(member.id)),
            ("Reason", reason),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
        return False


def save_user_snapshot(
    user: discord.User,
    member: Optional[discord.Member],
    guild_id: int,
    reason: str = "lookup",
) -> bool:
    """
    Save a snapshot from a User object (with optional Member data).

    Use this when you have a User but might not have full Member data.

    Args:
        user: Discord user object
        member: Optional Discord member (for roles, nickname)
        guild_id: Guild ID to save snapshot for
        reason: Why snapshot was taken

    Returns:
        True if saved successfully
    """
    # If we have a member, use the more complete function
    if member:
        return save_member_snapshot(member, reason)

    # Otherwise save what we can from the User object
    try:
        db = get_db()

        account_created_at = user.created_at.timestamp() if user.created_at else None
        avatar_url = str(user.display_avatar.url) if user.display_avatar else None

        success = db.save_user_snapshot(
            user_id=user.id,
            guild_id=guild_id,
            username=user.name,
            display_name=user.display_name or user.name,
            nickname=None,
            avatar_url=avatar_url,
            roles=[],
            joined_at=None,
            account_created_at=account_created_at,
            reason=reason,
        )

        if success:
            logger.tree("User Snapshot Saved (Partial)", [
                ("User ID", str(user.id)),
                ("Username", user.name),
                ("Reason", reason),
                ("Note", "No member data available"),
            ], emoji="📸")

        return success

    except Exception as e:
        logger.error("User Snapshot Save Failed", [
            ("User ID", str(user.id)),
            ("Reason", reason),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
        return False


def update_snapshot_reason(
    user_id: int,
    guild_id: int,
    new_reason: str,
) -> bool:
    """
    Update the reason for an existing snapshot.

    Used when a 'leave' snapshot should become a 'ban' snapshot.

    Args:
        user_id: Discord user ID
        guild_id: Guild ID
        new_reason: New reason to set

    Returns:
        True if updated successfully
    """
    try:
        db = get_db()
        existing = db.get_user_snapshot(user_id, guild_id)

        if not existing:
            logger.debug("Snapshot Reason Update Skipped", [
                ("User ID", str(user_id)),
                ("Reason", "No existing snapshot"),
            ])
            return False

        old_reason = existing.get("snapshot_reason", "unknown")

        success = db.save_user_snapshot(
            user_id=user_id,
            guild_id=guild_id,
            username=existing["username"],
            display_name=existing["display_name"],
            nickname=existing.get("nickname"),
            avatar_url=existing.get("avatar_url"),
            roles=existing.get("roles", []),
            joined_at=existing.get("joined_at"),
            account_created_at=existing.get("account_created_at"),
            reason=new_reason,
        )

        if success:
            logger.tree("Snapshot Reason Updated", [
                ("User ID", str(user_id)),
                ("Username", existing["username"]),
                ("Old Reason", old_reason),
                ("New Reason", new_reason),
            ], emoji="🔄")

        return success

    except Exception as e:
        logger.error("Snapshot Reason Update Failed", [
            ("User ID", str(user_id)),
            ("New Reason", new_reason),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
        return False


def get_snapshot(user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a user's cached snapshot.

    Args:
        user_id: Discord user ID
        guild_id: Guild ID

    Returns:
        Snapshot dict or None
    """
    try:
        db = get_db()
        return db.get_user_snapshot(user_id, guild_id)
    except sqlite3.Error:
        # Database error during snapshot retrieval
        return None


def _extract_roles(member: discord.Member) -> List[Dict[str, Any]]:
    """Extract role data from a member."""
    roles_data = []
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.name == "@everyone":
            continue
        roles_data.append({
            "id": str(role.id),
            "name": role.name,
            "color": f"#{role.color.value:06x}" if role.color.value else "#99aab5",
            "position": role.position,
        })
    return roles_data


def cleanup_old_snapshots(guild_id: int, days_old: int = 365) -> int:
    """
    Delete snapshots older than specified days (for users without cases).

    Args:
        guild_id: Guild ID
        days_old: Delete snapshots older than this

    Returns:
        Number of deleted snapshots
    """
    try:
        db = get_db()

        stats_before = db.get_snapshot_stats(guild_id)
        total_before = stats_before.get("total", 0)

        deleted = db.cleanup_old_snapshots(guild_id, days_old)

        if deleted > 0:
            logger.tree("Snapshot Cleanup Complete", [
                ("Guild ID", str(guild_id)),
                ("Deleted", str(deleted)),
                ("Remaining", str(total_before - deleted)),
                ("Threshold", f"{days_old} days"),
                ("Note", "Users with cases preserved"),
            ], emoji="🧹")

        return deleted

    except Exception as e:
        logger.error("Snapshot Cleanup Failed", [
            ("Guild ID", str(guild_id)),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
        return 0


__all__ = [
    "save_member_snapshot",
    "save_user_snapshot",
    "update_snapshot_reason",
    "get_snapshot",
    "cleanup_old_snapshots",
]
