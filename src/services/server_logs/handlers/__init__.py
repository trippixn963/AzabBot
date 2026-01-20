"""
Server Logs Handlers Package
============================

Handler mixins for the LoggingService, organized by category.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .moderation import ModerationLogsMixin
from .mutes import MutesLogsMixin
from .messages import MessageLogsMixin
from .members import MemberLogsMixin
from .voice import VoiceLogsMixin
from .channels import ChannelLogsMixin
from .server import ServerLogsMixin
from .integrations import IntegrationsLogsMixin
from .threads import ThreadsLogsMixin
from .automod import AutoModLogsMixin
from .events import EventsLogsMixin
from .forum import ForumLogsMixin
from .reactions import ReactionsLogsMixin
from .stage import StageLogsMixin
from .boosts import BoostsLogsMixin
from .invites import InvitesLogsMixin
from .misc import MiscLogsMixin
from .alerts import AlertsLogsMixin
from .tickets import TicketsLogsMixin
from .appeals import AppealsLogsMixin
from .modmail import ModmailLogsMixin
from .warnings import WarningsLogsMixin
from .audit import AuditLogsMixin

__all__ = [
    "ModerationLogsMixin",
    "MutesLogsMixin",
    "MessageLogsMixin",
    "MemberLogsMixin",
    "VoiceLogsMixin",
    "ChannelLogsMixin",
    "ServerLogsMixin",
    "IntegrationsLogsMixin",
    "ThreadsLogsMixin",
    "AutoModLogsMixin",
    "EventsLogsMixin",
    "ForumLogsMixin",
    "ReactionsLogsMixin",
    "StageLogsMixin",
    "BoostsLogsMixin",
    "InvitesLogsMixin",
    "MiscLogsMixin",
    "AlertsLogsMixin",
    "TicketsLogsMixin",
    "AppealsLogsMixin",
    "ModmailLogsMixin",
    "WarningsLogsMixin",
    "AuditLogsMixin",
]
