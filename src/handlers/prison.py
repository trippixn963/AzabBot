"""
AzabBot - Prison Handler (Thin Wrapper)
=======================================

Re-exports from the prison package for backwards compatibility.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.handlers.prison import PrisonHandler
from src.utils.duration import format_duration_from_minutes as format_duration

__all__ = ["PrisonHandler", "format_duration"]
