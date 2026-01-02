"""
Azab Discord Bot - Anti-Nuke Protection
========================================

Detects and prevents server nuking (mass bans/kicks/deletions).

DESIGN:
    Tracks destructive actions per user within a time window.
    If thresholds exceeded, strips permissions and alerts owner.

Actions Tracked:
    - Member bans
    - Member kicks
    - Channel deletions
    - Role deletions

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Thresholds for nuke detection (actions in time window)
BAN_THRESHOLD = 5
KICK_THRESHOLD = 5
CHANNEL_DELETE_THRESHOLD = 3
ROLE_DELETE_THRESHOLD = 3
TIME_WINDOW = 60  # seconds

# Exempt users (owner is always exempt)
EXEMPT_ROLE_NAMES = ["Owner", "Admin", "Administrator"]


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ActionTracker:
    """Tracks destructive actions for a user."""
    bans: List[datetime] = field(default_factory=list)
    kicks: List[datetime] = field(default_factory=list)
    channel_deletes: List[datetime] = field(default_factory=list)
    role_deletes: List[datetime] = field(default_factory=list)


# =============================================================================
# Anti-Nuke Service
# =============================================================================

class AntiNukeService:
    """
    Detects and prevents server nuking.

    Monitors audit log for mass destructive actions and
    automatically strips permissions from offenders.
    """

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        # Track actions per user (guild_id -> user_id -> tracker)
        self._trackers: Dict[int, Dict[int, ActionTracker]] = defaultdict(
            lambda: defaultdict(ActionTracker)
        )

        # Cooldown for alerts (don't spam)
        self._alert_cooldowns: Dict[int, datetime] = {}

        logger.tree("Anti-Nuke Service Loaded", [
            ("Ban Threshold", f"{BAN_THRESHOLD} / {TIME_WINDOW}s"),
            ("Kick Threshold", f"{KICK_THRESHOLD} / {TIME_WINDOW}s"),
            ("Channel Delete", f"{CHANNEL_DELETE_THRESHOLD} / {TIME_WINDOW}s"),
            ("Role Delete", f"{ROLE_DELETE_THRESHOLD} / {TIME_WINDOW}s"),
        ], emoji="🛡️")

    def _is_exempt(self, member: discord.Member) -> bool:
        """Check if member is exempt from anti-nuke."""
        # Owner is always exempt
        if member.id == member.guild.owner_id:
            return True

        # Developer is exempt
        if member.id == self.config.developer_id:
            return True

        # Trusted bots are exempt (from config)
        if self.config.ignored_bot_ids and member.id in self.config.ignored_bot_ids:
            return True

        # Check exempt roles
        for role in member.roles:
            if role.name in EXEMPT_ROLE_NAMES:
                return True

        return False

    def _clean_old_actions(self, tracker: ActionTracker) -> None:
        """Remove actions older than the time window."""
        now = datetime.now(NY_TZ)
        cutoff = now - timedelta(seconds=TIME_WINDOW)

        tracker.bans = [t for t in tracker.bans if t > cutoff]
        tracker.kicks = [t for t in tracker.kicks if t > cutoff]
        tracker.channel_deletes = [t for t in tracker.channel_deletes if t > cutoff]
        tracker.role_deletes = [t for t in tracker.role_deletes if t > cutoff]

    async def track_ban(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a ban action.

        Returns True if nuke detected.
        """
        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.bans.append(now)

        if len(tracker.bans) >= BAN_THRESHOLD:
            await self._handle_nuke(guild, user_id, "mass_ban", len(tracker.bans))
            return True

        return False

    async def track_kick(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a kick action.

        Returns True if nuke detected.
        """
        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.kicks.append(now)

        if len(tracker.kicks) >= KICK_THRESHOLD:
            await self._handle_nuke(guild, user_id, "mass_kick", len(tracker.kicks))
            return True

        return False

    async def track_channel_delete(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a channel deletion.

        Returns True if nuke detected.
        """
        # Skip tracking for exempt bots (from config)
        if self.config.ignored_bot_ids and user_id in self.config.ignored_bot_ids:
            return False

        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.channel_deletes.append(now)

        if len(tracker.channel_deletes) >= CHANNEL_DELETE_THRESHOLD:
            await self._handle_nuke(guild, user_id, "mass_channel_delete", len(tracker.channel_deletes))
            return True

        return False

    async def track_role_delete(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a role deletion.

        Returns True if nuke detected.
        """
        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.role_deletes.append(now)

        if len(tracker.role_deletes) >= ROLE_DELETE_THRESHOLD:
            await self._handle_nuke(guild, user_id, "mass_role_delete", len(tracker.role_deletes))
            return True

        return False

    async def _handle_nuke(
        self,
        guild: discord.Guild,
        user_id: int,
        nuke_type: str,
        count: int,
    ) -> None:
        """Handle detected nuke attempt."""
        member = guild.get_member(user_id)
        if not member:
            return

        # Check if exempt
        if self._is_exempt(member):
            logger.tree("NUKE DETECTED (EXEMPT USER)", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("ID", str(member.id)),
                ("Type", nuke_type),
                ("Count", str(count)),
                ("Action", "None (exempt)"),
            ], emoji="⚠️")
            return

        # Format nuke type
        nuke_display = {
            "mass_ban": "Mass Banning",
            "mass_kick": "Mass Kicking",
            "mass_channel_delete": "Mass Channel Deletion",
            "mass_role_delete": "Mass Role Deletion",
        }.get(nuke_type, nuke_type)

        logger.tree("🚨 NUKE DETECTED", [
            ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
            ("ID", str(member.id)),
            ("Type", nuke_display),
            ("Count", f"{count} in {TIME_WINDOW}s"),
            ("Action", "Stripping permissions"),
        ], emoji="🚨")

        # Strip all roles with permissions
        await self._strip_permissions(member)

        # Alert owner and logs
        await self._send_alert(guild, member, nuke_type, count)

        # Clear tracker
        self._trackers[guild.id][user_id] = ActionTracker()

    async def _strip_permissions(self, member: discord.Member) -> None:
        """Strip all dangerous roles from member."""
        try:
            # Get roles that have dangerous permissions
            dangerous_roles = []
            for role in member.roles:
                if role.is_default():
                    continue
                perms = role.permissions
                if any([
                    perms.administrator,
                    perms.ban_members,
                    perms.kick_members,
                    perms.manage_channels,
                    perms.manage_roles,
                    perms.manage_guild,
                ]):
                    dangerous_roles.append(role)

            if dangerous_roles:
                await member.remove_roles(
                    *dangerous_roles,
                    reason="Anti-nuke: Suspicious mass actions detected"
                )
                logger.tree("Permissions Stripped", [
                    ("User", str(member)),
                    ("Roles Removed", str(len(dangerous_roles))),
                ], emoji="🔒")

        except discord.Forbidden:
            logger.warning(f"Cannot strip roles from {member} - missing permissions")
        except discord.HTTPException as e:
            logger.warning(f"Failed to strip roles: {e}")

    async def _send_alert(
        self,
        guild: discord.Guild,
        offender: discord.Member,
        nuke_type: str,
        count: int,
    ) -> None:
        """Send alert to owner and server logs."""
        # Format nuke type
        nuke_display = {
            "mass_ban": "Mass Banning",
            "mass_kick": "Mass Kicking",
            "mass_channel_delete": "Mass Channel Deletion",
            "mass_role_delete": "Mass Role Deletion",
        }.get(nuke_type, nuke_type)

        embed = discord.Embed(
            title="🚨 NUKE ATTEMPT DETECTED",
            description=f"Suspicious activity detected and stopped.",
            color=0xFF0000,  # Red
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="Offender", value=f"{offender.mention}", inline=True)
        embed.add_field(name="Type", value=nuke_display, inline=True)
        embed.add_field(name="Actions", value=f"{count} in {TIME_WINDOW}s", inline=True)
        embed.add_field(name="Response", value="Permissions stripped", inline=True)
        embed.set_thumbnail(url=offender.display_avatar.url)
        set_footer(embed)

        # Send to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await self.bot.logging_service._send_log(
                    self.bot.logging_service.LogCategory.ALERTS,
                    embed,
                )

                # Ping developer in alerts thread
                if self.config.developer_id:
                    thread = await self.bot.logging_service._get_or_create_thread(
                        self.bot.logging_service.LogCategory.ALERTS
                    )
                    if thread:
                        await thread.send(
                            f"<@{self.config.developer_id}> 🚨 **NUKE ATTEMPT STOPPED!** "
                            f"{offender.mention} was caught performing {nuke_display.lower()}."
                        )
            except Exception as e:
                logger.warning(f"Failed to log nuke alert: {e}")

        # Send to mod server general channel for all mods to see
        if self.config.alert_channel_id:
            try:
                alert_channel = self.bot.get_channel(self.config.alert_channel_id)
                if alert_channel:
                    instructions = (
                        f"@everyone 🚨 **NUKE ATTEMPT DETECTED AND STOPPED!**\n\n"
                        f"**What happened:**\n"
                        f"• {offender.mention} ({offender.name}) was performing **{nuke_display.lower()}**\n"
                        f"• They did `{count}` actions in `{TIME_WINDOW}` seconds\n"
                        f"• Bot automatically **stripped their dangerous permissions**\n\n"
                        f"**What mods should do:**\n"
                        f"1. Review what {offender.mention} deleted/banned/kicked\n"
                        f"2. Decide if they should be banned from the server\n"
                        f"3. Restore any deleted channels/roles if needed\n"
                        f"4. Unban any wrongly banned members if needed"
                    )
                    await alert_channel.send(content=instructions, embed=embed)
            except Exception as e:
                logger.warning(f"Failed to send nuke alert to alert channel: {e}")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AntiNukeService"]
