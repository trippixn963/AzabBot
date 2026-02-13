"""
AzabBot - User Snapshots Service Package
========================================

Centralized service for managing user snapshots.
Preserves user profile data (nickname, roles, avatar) for banned/left users.
Activity data comes from SyriaBot which retains data for inactive users.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import (
    save_member_snapshot,
    save_user_snapshot,
    update_snapshot_reason,
    get_snapshot,
    cleanup_old_snapshots,
)

__all__ = [
    "save_member_snapshot",
    "save_user_snapshot",
    "update_snapshot_reason",
    "get_snapshot",
    "cleanup_old_snapshots",
]
