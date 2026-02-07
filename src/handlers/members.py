"""
AzabBot - Member Events (Thin Wrapper)
======================================

Re-exports from the members package for backwards compatibility.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.handlers.members import MemberEvents, setup

__all__ = ["MemberEvents", "setup"]
