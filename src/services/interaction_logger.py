"""
Azab Discord Bot - Interaction Logger Service
==============================================

Logs all button interactions to a Discord webhook in the mods server.

Tracked interactions:
- Ticket actions (create, claim, close, reopen, transcript)
- Appeal actions (approve, deny, contact user)
- Modmail actions (close)
- Prison actions (mute, unmute)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import aiohttp
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import NY_TZ

# Webhook request timeout (seconds)
WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=10)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Logging webhook URL for mods server
LOG_WEBHOOK_URL = "https://discord.com/api/webhooks/1455223536150122578/ArxQNk45yfQjyLXfqN-xK1TsFaOvBaABbpJD0u_kYVRomdty3YxABjsZyjARAORvNkU3"

# Colors for different event types
COLOR_SUCCESS = 0x00FF00    # Green
COLOR_ERROR = 0xFF0000      # Red
COLOR_INFO = 0x5865F2       # Discord blurple
COLOR_WARNING = 0xFFD700    # Gold
COLOR_TICKET = 0x3498DB     # Blue
COLOR_APPEAL = 0x9B59B6     # Purple
COLOR_MODMAIL = 0x1ABC9C    # Teal
COLOR_PRISON = 0xFF4500     # Orange-red


# =============================================================================
# Interaction Logger Service
# =============================================================================

class InteractionLogger:
    """Logs bot button interactions via webhook."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None

    async def verify_webhook(self) -> bool:
        """Send a startup verification message to confirm webhook is working."""
        if not LOG_WEBHOOK_URL:
            logger.warning("Interaction Logger", [
                ("Status", "No webhook URL configured"),
            ])
            return False

        try:
            session = await self._get_session()
            embed = discord.Embed(
                title="🔔 Interaction Logger Online",
                description="Webhook verification successful. All button interactions will be logged here.",
                color=COLOR_SUCCESS,
            )
            embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
            embed.add_field(name="Bot", value=f"`{self.bot.user.name if self.bot.user else 'AzabBot'}`", inline=True)

            payload = {"embeds": [embed.to_dict()]}

            async with session.post(LOG_WEBHOOK_URL, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info("Interaction Logger", [
                        ("Status", "Webhook verified"),
                        ("Response", str(resp.status)),
                    ])
                    return True
                else:
                    logger.warning("Interaction Logger", [
                        ("Status", "Webhook verification failed"),
                        ("Response", str(resp.status)),
                    ])
                    return False
        except Exception as e:
            logger.error("Interaction Logger", [
                ("Status", "Webhook verification error"),
                ("Error", str(e)[:100]),
            ])
            return False

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with timeout."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=WEBHOOK_TIMEOUT)
        return self._session

    async def _send_log(self, embed: discord.Embed) -> None:
        """Send a log embed via webhook."""
        if not LOG_WEBHOOK_URL:
            return

        try:
            session = await self._get_session()
            embed_dict = embed.to_dict()
            payload = {"embeds": [embed_dict]}

            async with session.post(LOG_WEBHOOK_URL, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.debug(f"Interaction logged: {embed.title}")
                else:
                    logger.warning("Interaction Webhook Error", [
                        ("Status", str(resp.status)),
                        ("Title", embed.title or "Unknown"),
                    ])
        except Exception as e:
            logger.warning("Interaction Webhook Failed", [
                ("Error", str(e)[:100]),
                ("Title", embed.title if hasattr(embed, 'title') else "Unknown"),
            ])

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_time_str(self) -> str:
        """Get formatted time string in EST."""
        now_est = datetime.now(NY_TZ)
        return now_est.strftime("%I:%M %p EST")

    # =========================================================================
    # Ticket Events
    # =========================================================================

    async def log_ticket_created(
        self,
        user: discord.User,
        ticket_id: str,
        category: str,
        subject: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log when a ticket is created."""
        embed = discord.Embed(
            title="🎫 Ticket Created",
            color=COLOR_TICKET,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Category", value=f"`{category.title()}`", inline=True)
        embed.add_field(name="Subject", value=f"`{subject[:50]}{'...' if len(subject) > 50 else ''}`", inline=False)

        thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
        embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        await self._send_log(embed)

    async def log_ticket_claimed(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is claimed."""
        embed = discord.Embed(
            title="✋ Ticket Claimed",
            color=COLOR_WARNING,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)

        await self._send_log(embed)

    async def log_ticket_unclaimed(
        self,
        staff: discord.Member,
        ticket_id: str,
    ) -> None:
        """Log when a ticket is unclaimed."""
        embed = discord.Embed(
            title="👐 Ticket Unclaimed",
            color=COLOR_INFO,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)

        await self._send_log(embed)

    async def log_ticket_closed(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when a ticket is closed."""
        embed = discord.Embed(
            title="🔒 Ticket Closed",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)
        if reason:
            embed.add_field(name="Reason", value=f"`{reason[:100]}`", inline=False)

        await self._send_log(embed)

    async def log_ticket_reopened(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is reopened."""
        embed = discord.Embed(
            title="🔓 Ticket Reopened",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Reopened By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)

        await self._send_log(embed)

    async def log_ticket_priority(
        self,
        staff: discord.Member,
        ticket_id: str,
        priority: str,
    ) -> None:
        """Log when ticket priority is changed."""
        priority_colors = {
            "low": 0x95A5A6,      # Gray
            "normal": 0x3498DB,   # Blue
            "high": 0xFF9800,     # Orange
            "urgent": 0xFF0000,   # Red
        }

        embed = discord.Embed(
            title="🏷️ Priority Changed",
            color=priority_colors.get(priority, COLOR_INFO),
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Changed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Priority", value=f"`{priority.upper()}`", inline=True)

        await self._send_log(embed)

    async def log_ticket_assigned(
        self,
        staff: discord.Member,
        ticket_id: str,
        assigned_to: discord.Member,
    ) -> None:
        """Log when a ticket is assigned."""
        embed = discord.Embed(
            title="👤 Ticket Assigned",
            color=COLOR_INFO,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Assigned By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Assigned To", value=f"{assigned_to.mention}", inline=True)

        await self._send_log(embed)

    async def log_ticket_user_added(
        self,
        staff: discord.Member,
        ticket_id: str,
        added_user: discord.User,
    ) -> None:
        """Log when a user is added to a ticket."""
        embed = discord.Embed(
            title="➕ User Added to Ticket",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Added By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="User Added", value=f"{added_user.mention} `[{added_user.id}]`", inline=True)

        await self._send_log(embed)

    async def log_ticket_transcript(
        self,
        staff: discord.Member,
        ticket_id: str,
    ) -> None:
        """Log when a ticket transcript is requested."""
        embed = discord.Embed(
            title="📜 Transcript Requested",
            color=COLOR_INFO,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Requested By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Appeal Events
    # =========================================================================

    async def log_appeal_approved(
        self,
        staff: discord.Member,
        appeal_id: str,
        case_id: str,
        user_id: int,
        action_type: str,
    ) -> None:
        """Log when an appeal is approved."""
        embed = discord.Embed(
            title="✅ Appeal Approved",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Approved By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Case", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=f"`{action_type.title()}`", inline=True)
        embed.add_field(name="User", value=f"<@{user_id}> `[{user_id}]`", inline=True)

        await self._send_log(embed)

    async def log_appeal_denied(
        self,
        staff: discord.Member,
        appeal_id: str,
        case_id: str,
        user_id: int,
        action_type: str,
    ) -> None:
        """Log when an appeal is denied."""
        embed = discord.Embed(
            title="❌ Appeal Denied",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Denied By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Case", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=f"`{action_type.title()}`", inline=True)
        embed.add_field(name="User", value=f"<@{user_id}> `[{user_id}]`", inline=True)

        await self._send_log(embed)

    async def log_appeal_contact(
        self,
        staff: discord.Member,
        appeal_id: str,
        user: discord.User,
    ) -> None:
        """Log when staff contacts a banned user about their appeal."""
        embed = discord.Embed(
            title="📬 Appeal Contact Initiated",
            color=COLOR_APPEAL,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="User Contacted", value=f"{user.mention} `[{user.id}]`", inline=True)

        await self._send_log(embed)

    async def log_appeal_ticket_opened(
        self,
        staff: discord.Member,
        appeal_id: str,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is opened for appeal discussion."""
        embed = discord.Embed(
            title="🎫 Appeal Ticket Opened",
            color=COLOR_APPEAL,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Modmail Events
    # =========================================================================

    async def log_modmail_created(
        self,
        user: discord.User,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log when a modmail thread is created."""
        embed = discord.Embed(
            title="📬 Modmail Created",
            color=COLOR_MODMAIL,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Status", value="`Banned User`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)

        thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
        embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        await self._send_log(embed)

    async def log_modmail_closed(
        self,
        staff: discord.Member,
        user: discord.User,
        thread_id: int,
    ) -> None:
        """Log when a modmail thread is closed."""
        embed = discord.Embed(
            title="🔒 Modmail Closed",
            color=COLOR_ERROR,
        )
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)

        await self._send_log(embed)

    # =========================================================================
    # Generic Events
    # =========================================================================

    async def log_button_interaction(
        self,
        user: discord.User,
        button_name: str,
        success: bool = True,
        details: Optional[str] = None,
        **fields
    ) -> None:
        """Log a generic button interaction."""
        status = "✅" if success else "❌"
        color = COLOR_SUCCESS if success else COLOR_ERROR

        embed = discord.Embed(
            title=f"{status} {button_name}",
            color=color,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)

        if details:
            embed.add_field(name="Details", value=f"`{details[:100]}`", inline=False)

        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=True)

        await self._send_log(embed)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["InteractionLogger"]
