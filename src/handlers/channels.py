"""
AzabBot - Channel Events (Thin Wrapper)
=======================================

Re-exports from the channels package for backwards compatibility.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from src.handlers.channels import ChannelEvents, setup

__all__ = ["ChannelEvents", "setup"]
