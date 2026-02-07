"""
AzabBot - Purge Constants
=========================

Constants for the purge command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import timedelta

from discord import app_commands


MESSAGE_AGE_LIMIT = timedelta(days=14)
"""Messages older than this cannot be bulk deleted."""

URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)
"""Regex pattern for detecting URLs in messages."""


class PurgeFilter:
    """Available purge filter types."""
    ALL = "all"
    USER = "user"
    BOTS = "bots"
    HUMANS = "humans"
    CONTAINS = "contains"
    ATTACHMENTS = "attachments"
    EMBEDS = "embeds"
    LINKS = "links"
    REACTIONS = "reactions"
    MENTIONS = "mentions"


FILTER_CHOICES = [
    app_commands.Choice(name="All Messages", value=PurgeFilter.ALL),
    app_commands.Choice(name="From User", value=PurgeFilter.USER),
    app_commands.Choice(name="From Bots", value=PurgeFilter.BOTS),
    app_commands.Choice(name="From Humans", value=PurgeFilter.HUMANS),
    app_commands.Choice(name="Containing Text", value=PurgeFilter.CONTAINS),
    app_commands.Choice(name="With Attachments", value=PurgeFilter.ATTACHMENTS),
    app_commands.Choice(name="With Embeds", value=PurgeFilter.EMBEDS),
    app_commands.Choice(name="With Links", value=PurgeFilter.LINKS),
    app_commands.Choice(name="With Reactions", value=PurgeFilter.REACTIONS),
    app_commands.Choice(name="With Mentions", value=PurgeFilter.MENTIONS),
]


__all__ = ["MESSAGE_AGE_LIMIT", "URL_PATTERN", "PurgeFilter", "FILTER_CHOICES"]
