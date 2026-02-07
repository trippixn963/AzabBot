"""
AzabBot - Mute Scheduler Package
================================

Background service for automatic unmuting of expired mutes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .scheduler import MuteScheduler

__all__ = ["MuteScheduler"]
