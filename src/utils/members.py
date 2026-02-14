"""
AzabBot - Member Utilities
==========================

Helper functions for member-related checks.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Optional
import discord


def is_booster(member: Optional[discord.Member]) -> bool:
    """
    Check if a member is a server booster.

    Args:
        member: Discord member to check (can be None).

    Returns:
        True if member is a booster, False otherwise.
    """
    return member is not None and member.premium_since is not None


__all__ = ["is_booster"]
