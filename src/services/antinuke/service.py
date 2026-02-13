"""
AzabBot - Anti-Nuke Service
===========================

Detects and prevents server nuking (mass bans/kicks/deletions).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import RATE_LIMIT_DELAY
from src.utils.discord_rate_limit import log_http_error

from .constants import (
    BAN_THRESHOLD,
    KICK_THRESHOLD,
    CHANNEL_DELETE_THRESHOLD,
    ROLE_DELETE_THRESHOLD,
    BOT_ADD_THRESHOLD,
    TIME_WINDOW,
    DANGEROUS_PERMISSIONS,
    EXEMPT_ROLE_NAMES,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


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
    bot_adds: List[datetime] = field(default_factory=list)
    perm_escalations: List[datetime] = field(default_factory=list)


# =============================================================================
# Anti-Nuke Service
# =============================================================================

class AntiNukeService:
    """
    Detects and prevents server nuking.

    Monitors audit log for mass destructive actions and
    automatically strips permissions from offenders.

    Features:
        - Mass ban/kick/delete detection
        - Permission escalation detection
        - Unauthorized bot addition tracking
        - Quarantine mode for full lockdown
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

        # Quarantine state per guild
        self._quarantined_guilds: Set[int] = set()

        # Store original permissions when quarantine activates
        self._quarantine_backup: Dict[int, Dict[int, discord.Permissions]] = {}

        logger.tree("Anti-Nuke Service Loaded", [
            ("Ban Threshold", f"{BAN_THRESHOLD} / {TIME_WINDOW}s"),
            ("Kick Threshold", f"{KICK_THRESHOLD} / {TIME_WINDOW}s"),
            ("Channel Delete", f"{CHANNEL_DELETE_THRESHOLD} / {TIME_WINDOW}s"),
            ("Role Delete", f"{ROLE_DELETE_THRESHOLD} / {TIME_WINDOW}s"),
            ("Bot Add Threshold", f"{BOT_ADD_THRESHOLD} / {TIME_WINDOW}s"),
            ("Perm Escalation", "Immediate detection"),
            ("Quarantine Mode", "Available"),
        ], emoji="🛡️")

    def _is_exempt(self, member: discord.Member) -> bool:
        """Check if member is exempt from anti-nuke."""
        # Owner is always exempt
        if member.id == member.guild.owner_id:
            return True

        # Developer is exempt
        if member.id == self.config.owner_id:
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
        tracker.bot_adds = [t for t in tracker.bot_adds if t > cutoff]
        tracker.perm_escalations = [t for t in tracker.perm_escalations if t > cutoff]

    async def track_ban(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a ban action.

        Returns True if nuke detected.
        """
        try:
            now = datetime.now(NY_TZ)
            tracker = self._trackers[guild.id][user_id]
            self._clean_old_actions(tracker)

            tracker.bans.append(now)
            count = len(tracker.bans)

            logger.debug("Ban Action Tracked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User ID", str(user_id)),
                ("Count", f"{count} / {BAN_THRESHOLD}"),
            ])

            if count >= BAN_THRESHOLD:
                await self._handle_nuke(guild, user_id, "mass_ban", count)
                return True

            return False

        except Exception as e:
            logger.error("Track Ban Failed", [
                ("Guild", str(guild.id)),
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False

    async def track_kick(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a kick action.

        Returns True if nuke detected.
        """
        try:
            now = datetime.now(NY_TZ)
            tracker = self._trackers[guild.id][user_id]
            self._clean_old_actions(tracker)

            tracker.kicks.append(now)
            count = len(tracker.kicks)

            logger.debug("Kick Action Tracked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User ID", str(user_id)),
                ("Count", f"{count} / {KICK_THRESHOLD}"),
            ])

            if count >= KICK_THRESHOLD:
                await self._handle_nuke(guild, user_id, "mass_kick", count)
                return True

            return False

        except Exception as e:
            logger.error("Track Kick Failed", [
                ("Guild", str(guild.id)),
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False

    async def track_channel_delete(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a channel deletion.

        Returns True if nuke detected.
        """
        try:
            # Skip tracking for exempt bots (from config)
            if self.config.ignored_bot_ids and user_id in self.config.ignored_bot_ids:
                logger.debug("Channel Delete Skipped (Exempt)", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                    ("User ID", str(user_id)),
                ])
                return False

            now = datetime.now(NY_TZ)
            tracker = self._trackers[guild.id][user_id]
            self._clean_old_actions(tracker)

            tracker.channel_deletes.append(now)
            count = len(tracker.channel_deletes)

            logger.debug("Channel Delete Tracked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User ID", str(user_id)),
                ("Count", f"{count} / {CHANNEL_DELETE_THRESHOLD}"),
            ])

            if count >= CHANNEL_DELETE_THRESHOLD:
                await self._handle_nuke(guild, user_id, "mass_channel_delete", count)
                return True

            return False

        except Exception as e:
            logger.error("Track Channel Delete Failed", [
                ("Guild", str(guild.id)),
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False

    async def track_role_delete(self, guild: discord.Guild, user_id: int) -> bool:
        """
        Track a role deletion.

        Returns True if nuke detected.
        """
        try:
            now = datetime.now(NY_TZ)
            tracker = self._trackers[guild.id][user_id]
            self._clean_old_actions(tracker)

            tracker.role_deletes.append(now)
            count = len(tracker.role_deletes)

            logger.debug("Role Delete Tracked", [
                ("Guild", f"{guild.name} ({guild.id})"),
                ("User ID", str(user_id)),
                ("Count", f"{count} / {ROLE_DELETE_THRESHOLD}"),
            ])

            if count >= ROLE_DELETE_THRESHOLD:
                await self._handle_nuke(guild, user_id, "mass_role_delete", count)
                return True

            return False

        except Exception as e:
            logger.error("Track Role Delete Failed", [
                ("Guild", str(guild.id)),
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False

    async def track_bot_add(
        self,
        guild: discord.Guild,
        user_id: int,
        bot_member: discord.Member,
    ) -> bool:
        """
        Track when a bot is added to the server.

        Returns True if suspicious activity detected.
        """
        # Check if bot is in trusted list
        if self.config.ignored_bot_ids and bot_member.id in self.config.ignored_bot_ids:
            logger.tree("Bot Add (Trusted)", [
                ("Bot", f"{bot_member.name} ({bot_member.id})"),
                ("Added By", str(user_id)),
            ], emoji="🤖")
            return False

        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.bot_adds.append(now)

        logger.tree("Bot Add Tracked", [
            ("Bot", f"{bot_member.name} ({bot_member.id})"),
            ("Added By", str(user_id)),
            ("Count", f"{len(tracker.bot_adds)} / {BOT_ADD_THRESHOLD}"),
        ], emoji="🤖")

        # Multiple bots added quickly is suspicious
        if len(tracker.bot_adds) >= BOT_ADD_THRESHOLD:
            await self._handle_nuke(guild, user_id, "mass_bot_add", len(tracker.bot_adds))
            # Also kick the suspicious bots
            await self._kick_suspicious_bot(guild, bot_member, user_id)
            return True

        return False

    async def _kick_suspicious_bot(
        self,
        guild: discord.Guild,
        bot_member: discord.Member,
        added_by: int,
    ) -> None:
        """Kick a bot that was added during suspicious activity."""
        try:
            await bot_member.kick(reason=f"Anti-nuke: Suspicious bot add by user {added_by}")
            logger.tree("Suspicious Bot Kicked", [
                ("Bot", f"{bot_member.name} ({bot_member.id})"),
                ("Guild", guild.name),
            ], emoji="🚫")
        except discord.Forbidden:
            logger.warning("Bot Kick Failed (Forbidden)", [
                ("Bot", f"{bot_member.name} ({bot_member.id})"),
                ("Guild", guild.name),
                ("Error", "Missing permissions"),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Bot Kick", [
                ("Bot", f"{bot_member.name} ({bot_member.id})"),
                ("Guild", guild.name),
            ])

    async def track_permission_change(
        self,
        guild: discord.Guild,
        user_id: int,
        role: discord.Role,
        before_perms: discord.Permissions,
        after_perms: discord.Permissions,
    ) -> bool:
        """
        Track permission changes on roles.

        Detects when someone adds dangerous permissions to a role.
        Returns True if escalation detected.
        """
        member = guild.get_member(user_id)
        if member and self._is_exempt(member):
            return False

        # Check what permissions were added
        added_dangerous = []
        for perm_name in DANGEROUS_PERMISSIONS:
            before_val = getattr(before_perms, perm_name, False)
            after_val = getattr(after_perms, perm_name, False)
            if not before_val and after_val:
                added_dangerous.append(perm_name)

        if not added_dangerous:
            return False

        # Administrator grant is IMMEDIATE action
        if "administrator" in added_dangerous:
            logger.tree("🚨 ADMIN PERMISSION ESCALATION", [
                ("Role", f"{role.name} ({role.id})"),
                ("Changed By", str(user_id)),
                ("Perms Added", ", ".join(added_dangerous)),
            ], emoji="🚨")

            # Immediately revert and handle
            await self._revert_permission_change(guild, role, before_perms)
            await self._handle_nuke(guild, user_id, "permission_escalation", 1)
            return True

        # Track other dangerous permission additions
        now = datetime.now(NY_TZ)
        tracker = self._trackers[guild.id][user_id]
        self._clean_old_actions(tracker)

        tracker.perm_escalations.append(now)

        logger.tree("Permission Change Tracked", [
            ("Role", f"{role.name} ({role.id})"),
            ("Changed By", str(user_id)),
            ("Perms Added", ", ".join(added_dangerous)),
            ("Count", f"{len(tracker.perm_escalations)}"),
        ], emoji="⚠️")

        # Multiple permission escalations in short time
        if len(tracker.perm_escalations) >= 3:
            await self._handle_nuke(guild, user_id, "mass_permission_escalation", len(tracker.perm_escalations))
            return True

        return False

    async def _revert_permission_change(
        self,
        guild: discord.Guild,
        role: discord.Role,
        original_perms: discord.Permissions,
    ) -> None:
        """Revert a role's permissions to their original state."""
        try:
            await role.edit(
                permissions=original_perms,
                reason="Anti-nuke: Reverting suspicious permission escalation"
            )
            logger.tree("Permissions Reverted", [
                ("Role", f"{role.name} ({role.id})"),
                ("Guild", guild.name),
            ], emoji="↩️")
        except discord.Forbidden:
            logger.warning("Permission Revert Failed (Forbidden)", [
                ("Role", f"{role.name} ({role.id})"),
                ("Guild", guild.name),
                ("Error", "Missing permissions"),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Permission Revert", [
                ("Role", f"{role.name} ({role.id})"),
                ("Guild", guild.name),
            ])

    # =========================================================================
    # Quarantine Mode
    # =========================================================================

    def is_quarantined(self, guild_id: int) -> bool:
        """Check if a guild is in quarantine mode."""
        return guild_id in self._quarantined_guilds

    async def quarantine_guild(
        self,
        guild: discord.Guild,
        reason: str = "Nuke attempt detected",
    ) -> bool:
        """
        Put the guild in quarantine mode.

        This removes all dangerous permissions from all roles except
        the owner's top role. Use lift_quarantine to restore.

        Returns True if quarantine was activated.
        """
        if guild.id in self._quarantined_guilds:
            return False

        logger.tree("🔒 ACTIVATING QUARANTINE", [
            ("Guild", guild.name),
            ("Reason", reason),
        ], emoji="🔒")

        # Backup current permissions
        self._quarantine_backup[guild.id] = {}

        try:
            for role in guild.roles:
                # Skip @everyone and the owner's top role
                if role.is_default():
                    continue
                if guild.owner and role == guild.owner.top_role:
                    continue
                # Skip bot's role (we need to keep our perms)
                if role.managed and role.tags and role.tags.bot_id == self.bot.user.id:
                    continue

                # Check if role has dangerous permissions
                has_dangerous = any(
                    getattr(role.permissions, perm, False)
                    for perm in DANGEROUS_PERMISSIONS
                )

                if has_dangerous:
                    # Backup original permissions
                    self._quarantine_backup[guild.id][role.id] = role.permissions

                    # Create safe permissions (remove dangerous ones)
                    safe_perms = discord.Permissions(role.permissions.value)
                    for perm_name in DANGEROUS_PERMISSIONS:
                        setattr(safe_perms, perm_name, False)

                    try:
                        await role.edit(
                            permissions=safe_perms,
                            reason=f"Anti-nuke quarantine: {reason}"
                        )
                        logger.debug("Role Quarantined", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                        ])
                        await asyncio.sleep(RATE_LIMIT_DELAY)  # Rate limit protection
                    except discord.Forbidden:
                        logger.warning("Role Quarantine Failed (Forbidden)", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                            ("Error", "Missing permissions"),
                        ])
                    except discord.HTTPException as e:
                        log_http_error(e, "Role Quarantine", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                        ])

            self._quarantined_guilds.add(guild.id)

            # Alert about quarantine
            await self._send_quarantine_alert(guild, reason, activated=True)

            logger.tree("Quarantine Activated", [
                ("Guild", guild.name),
                ("Roles Modified", str(len(self._quarantine_backup.get(guild.id, {})))),
            ], emoji="🔒")

            return True

        except Exception as e:
            logger.error("Quarantine Activation Failed", [("Error", str(e)[:50])])
            return False

    async def lift_quarantine(self, guild: discord.Guild) -> bool:
        """
        Lift quarantine mode and restore original permissions.

        Returns True if quarantine was lifted.
        """
        if guild.id not in self._quarantined_guilds:
            return False

        logger.tree("🔓 LIFTING QUARANTINE", [
            ("Guild", guild.name),
        ], emoji="🔓")

        backup = self._quarantine_backup.get(guild.id, {})

        try:
            for role_id, original_perms in backup.items():
                role = guild.get_role(role_id)
                if role:
                    try:
                        await role.edit(
                            permissions=original_perms,
                            reason="Anti-nuke: Quarantine lifted, restoring permissions"
                        )
                        logger.debug("Role Restored", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                        ])
                        await asyncio.sleep(RATE_LIMIT_DELAY)  # Rate limit protection
                    except discord.Forbidden:
                        logger.warning("Role Restore Failed (Forbidden)", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                            ("Error", "Missing permissions"),
                        ])
                    except discord.HTTPException as e:
                        log_http_error(e, "Role Restore", [
                            ("Role", f"{role.name} ({role.id})"),
                            ("Guild", guild.name),
                        ])
                else:
                    logger.warning("Role Not Found During Restore", [
                        ("Role ID", str(role_id)),
                        ("Guild", guild.name),
                    ])

            self._quarantined_guilds.discard(guild.id)
            self._quarantine_backup.pop(guild.id, None)

            await self._send_quarantine_alert(guild, "Manual lift", activated=False)

            logger.tree("Quarantine Lifted", [
                ("Guild", guild.name),
                ("Roles Restored", str(len(backup))),
            ], emoji="🔓")

            return True

        except Exception as e:
            logger.error("Quarantine Lift Failed", [("Error", str(e)[:50])])
            return False

    async def _send_quarantine_alert(
        self,
        guild: discord.Guild,
        reason: str,
        activated: bool,
    ) -> None:
        """Send alert about quarantine status change."""
        if activated:
            embed = discord.Embed(
                title="🔒 QUARANTINE MODE ACTIVATED",
                description=(
                    f"The server has been locked down due to: **{reason}**\n\n"
                    f"**What this means:**\n"
                    f"• All dangerous permissions have been stripped from roles\n"
                    f"• Only server owner and bot retain full permissions\n"
                    f"• Use `/antinuke lift` to restore when safe\n\n"
                    f"**Roles affected:** {len(self._quarantine_backup.get(guild.id, {}))}"
                ),
                color=0xFF0000,
                timestamp=datetime.now(NY_TZ),
            )
        else:
            embed = discord.Embed(
                title="🔓 QUARANTINE MODE LIFTED",
                description=(
                    f"The server quarantine has been lifted.\n\n"
                    f"All role permissions have been restored to their "
                    f"original state before the lockdown."
                ),
                color=0x00FF00,
                timestamp=datetime.now(NY_TZ),
            )

        # Send to alert channel
        if self.config.alert_channel_id:
            try:
                alert_channel = self.bot.get_channel(self.config.alert_channel_id)
                if alert_channel:
                    await alert_channel.send(
                        content=f"<@{self.config.owner_id}>" if activated else None,
                        embed=embed,
                    )
                    logger.debug("Quarantine Alert Sent", [
                        ("Guild", guild.name),
                        ("Activated", str(activated)),
                        ("Channel", str(self.config.alert_channel_id)),
                    ])
                else:
                    logger.warning("Quarantine Alert Channel Not Found", [
                        ("Channel ID", str(self.config.alert_channel_id)),
                    ])
            except discord.HTTPException as e:
                log_http_error(e, "Quarantine Alert", [
                    ("Guild", guild.name),
                ])
            except Exception as e:
                logger.error("Quarantine Alert Failed", [
                    ("Guild", guild.name),
                    ("Error", str(e)[:100]),
                    ("Type", type(e).__name__),
                ])

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
            "mass_bot_add": "Mass Bot Addition",
            "permission_escalation": "Permission Escalation (Admin Grant)",
            "mass_permission_escalation": "Mass Permission Escalation",
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
            dangerous_roles: List[discord.Role] = []
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
                    ("User", f"{member.name} ({member.id})"),
                    ("Guild", member.guild.name),
                    ("Roles Removed", str(len(dangerous_roles))),
                    ("Role Names", ", ".join(r.name for r in dangerous_roles[:5])),
                ], emoji="🔒")
            else:
                logger.debug("No Dangerous Roles Found", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Guild", member.guild.name),
                ])

        except discord.Forbidden:
            logger.error("Strip Permissions Failed (Forbidden)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", member.guild.name),
                ("Error", "Missing permissions to remove roles"),
            ])
        except discord.HTTPException as e:
            log_http_error(e, "Strip Permissions", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", member.guild.name),
            ])

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
            "mass_bot_add": "Mass Bot Addition",
            "permission_escalation": "Permission Escalation (Admin Grant)",
            "mass_permission_escalation": "Mass Permission Escalation",
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

        # Send to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await self.bot.logging_service._send_log(
                    self.bot.logging_service.LogCategory.ALERTS,
                    embed,
                )

                # Ping developer in alerts thread
                if self.config.owner_id:
                    thread = await self.bot.logging_service._get_or_create_thread(
                        self.bot.logging_service.LogCategory.ALERTS
                    )
                    if thread:
                        await thread.send(
                            f"<@{self.config.owner_id}> 🚨 **NUKE ATTEMPT STOPPED!** "
                            f"{offender.mention} was caught performing {nuke_display.lower()}."
                        )

                logger.debug("Nuke Alert Logged", [
                    ("Offender", f"{offender.name} ({offender.id})"),
                    ("Type", nuke_display),
                ])
            except discord.HTTPException as e:
                log_http_error(e, "Nuke Alert Log", [
                    ("Offender", f"{offender.name} ({offender.id})"),
                ])
            except Exception as e:
                logger.error("Nuke Alert Log Failed", [
                    ("Offender", f"{offender.name} ({offender.id})"),
                    ("Error", str(e)[:100]),
                    ("Type", type(e).__name__),
                ])

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
                    logger.debug("Nuke Alert Sent to Mods", [
                        ("Channel", str(self.config.alert_channel_id)),
                        ("Offender", f"{offender.name} ({offender.id})"),
                    ])
                else:
                    logger.warning("Nuke Alert Channel Not Found", [
                        ("Channel ID", str(self.config.alert_channel_id)),
                    ])
            except discord.HTTPException as e:
                log_http_error(e, "Nuke Alert to Mods", [
                    ("Channel", str(self.config.alert_channel_id)),
                ])
            except Exception as e:
                logger.error("Nuke Alert to Mods Failed", [
                    ("Channel", str(self.config.alert_channel_id)),
                    ("Error", str(e)[:100]),
                    ("Type", type(e).__name__),
                ])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AntiNukeService", "ActionTracker"]
