"""
AzabBot - User Snapshots Service Package
========================================

Centralized service for managing user snapshots.
Preserves user data (nickname, roles, avatar) for banned/left users.

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
