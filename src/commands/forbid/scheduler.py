"""
AzabBot - Scheduler Mixin
=========================

Background tasks: nightly scan, startup scan, expiry scheduler.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import asyncio
import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.footer import set_footer
from src.utils.dm_helpers import safe_send_dm
from src.utils.rate_limiter import rate_limit
from src.core.constants import FORBID_STARTUP_DELAY, SECONDS_PER_HOUR, FORBID_CHECK_INTERVAL

from .constants import RESTRICTIONS

if TYPE_CHECKING:
    from src.commands.forbid.cog import ForbidCog


class SchedulerMixin:
    """Mixin for forbid background tasks."""

    # =========================================================================
    # Startup Scan Task
    # =========================================================================

    async def _run_startup_scan(self: "ForbidCog") -> None:
        """Run forbid permission scan on bot startup (delayed to not slow startup)."""
        await self.bot.wait_until_ready()

        # Wait after ready to not slow down startup
        await asyncio.sleep(FORBID_STARTUP_DELAY)

        try:
            logger.tree("Forbid Startup Scan Started", [], emoji="🔍")

            total_fixed = 0
            for guild in self.bot.guilds:
                try:
                    fixed = await self._scan_guild_forbids(guild)
                    total_fixed += fixed
                except Exception as e:
                    logger.error("Forbid Startup Scan Error", [
                        ("Guild", guild.name),
                        ("Error", str(e)[:100]),
                    ])

            logger.tree("Forbid Startup Scan Complete", [
                ("Guilds Scanned", str(len(self.bot.guilds))),
                ("Overwrites Fixed", str(total_fixed)),
            ], emoji="✅")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Forbid Startup Scan Failed", [
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])

    # =========================================================================
    # Nightly Scan Task
    # =========================================================================

    async def _start_nightly_scan(self: "ForbidCog") -> None:
        """Start the nightly scan loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                # Calculate time until midnight (00:00) EST
                now = datetime.now(NY_TZ)
                target = now.replace(hour=0, minute=0, second=0, microsecond=0)

                # If it's past midnight today, schedule for tomorrow
                if now >= target:
                    target = target + timedelta(days=1)

                seconds_until = (target - now).total_seconds()

                # Wait until midnight
                await asyncio.sleep(seconds_until)

                # Run the scan
                await self._run_forbid_scan()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Forbid Nightly Scan Error", [
                    ("Error", str(e)[:100]),
                    ("Type", type(e).__name__),
                ])
                # Wait an hour before retrying on error
                await asyncio.sleep(SECONDS_PER_HOUR)

    async def _run_forbid_scan(self: "ForbidCog") -> None:
        """Scan all guilds and ensure forbid roles have correct overwrites."""
        logger.tree("Forbid Nightly Scan Started", [], emoji="🔍")

        total_fixed = 0

        for guild in self.bot.guilds:
            try:
                fixed = await self._scan_guild_forbids(guild)
                total_fixed += fixed
            except Exception as e:
                logger.error("Forbid Scan Error", [
                    ("Guild", guild.name),
                    ("Error", str(e)[:100]),
                ])

        logger.tree("Forbid Nightly Scan Complete", [
            ("Guilds Scanned", str(len(self.bot.guilds))),
            ("Overwrites Fixed", str(total_fixed)),
        ], emoji="✅")

    async def _scan_guild_forbids(self: "ForbidCog", guild: discord.Guild) -> int:
        """
        Scan a single guild for missing forbid overwrites. Returns count of fixes.

        OPTIMIZED: Iterates channels once, checking all forbid roles per channel.
        """
        fixed = 0

        # Pre-build role configs (only for roles that exist)
        role_configs = []
        text_perms = {"embed_links", "attach_files", "add_reactions",
                      "use_external_emojis", "use_external_stickers",
                      "create_public_threads", "create_private_threads"}
        voice_perms = {"connect", "stream"}

        for restriction, config in RESTRICTIONS.items():
            role_name = self._get_role_name(restriction)
            role = discord.utils.get(guild.roles, name=role_name)

            if not role:
                continue

            # Build expected overwrite
            overwrite_kwargs = {}
            if "permissions" in config:
                for perm in config["permissions"]:
                    overwrite_kwargs[perm] = False
            else:
                overwrite_kwargs[config["permission"]] = False

            perm_names = set(overwrite_kwargs.keys())
            role_configs.append({
                "role": role,
                "overwrite": discord.PermissionOverwrite(**overwrite_kwargs),
                "overwrite_kwargs": overwrite_kwargs,
                "apply_to_text": bool(perm_names & text_perms),
                "apply_to_voice": bool(perm_names & voice_perms),
            })

        if not role_configs:
            return 0

        # Single pass through all channels
        for channel in guild.channels:
            is_category = isinstance(channel, discord.CategoryChannel)
            is_text = isinstance(channel, (discord.TextChannel, discord.ForumChannel))
            is_voice = isinstance(channel, (discord.VoiceChannel, discord.StageChannel))

            for rc in role_configs:
                try:
                    # Determine if this channel type needs this role's overwrite
                    should_check = False
                    if is_category and (rc["apply_to_text"] or rc["apply_to_voice"]):
                        should_check = True
                    elif is_text and rc["apply_to_text"]:
                        should_check = True
                    elif is_voice and (rc["apply_to_voice"] or rc["apply_to_text"]):
                        should_check = True

                    if not should_check:
                        continue

                    # Check if overwrites are correct
                    current = channel.overwrites_for(rc["role"])
                    needs_fix = False
                    for perm_name in rc["overwrite_kwargs"]:
                        if getattr(current, perm_name) is not False:
                            needs_fix = True
                            break

                    if needs_fix:
                        await channel.set_permissions(
                            rc["role"],
                            overwrite=rc["overwrite"],
                            reason="Forbid system: scan fix"
                        )
                        fixed += 1
                        await rate_limit("role_modify")

                except (discord.Forbidden, discord.HTTPException):
                    continue

        return fixed

    # =========================================================================
    # Expiry Scheduler
    # =========================================================================

    async def _start_expiry_scheduler(self: "ForbidCog") -> None:
        """Start the expiry scheduler loop - checks every minute for expired forbids."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await self._process_expired_forbids()
                # Check at regular interval
                await asyncio.sleep(FORBID_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Forbid Expiry Scheduler Error", [
                    ("Error", str(e)[:100]),
                    ("Type", type(e).__name__),
                ])
                await asyncio.sleep(FORBID_CHECK_INTERVAL)

    async def _process_expired_forbids(self: "ForbidCog") -> None:
        """Process all expired forbids and remove them."""
        expired = self.db.get_expired_forbids()

        if not expired:
            return

        for forbid in expired:
            try:
                guild_id = forbid["guild_id"]
                user_id = forbid["user_id"]
                restriction_type = forbid["restriction_type"]

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    # Guild not accessible, just mark as removed in DB
                    self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)
                    logger.tree("Forbid Expired (Guild Not Found)", [
                        ("User ID", str(user_id)),
                        ("Guild ID", str(guild_id)),
                        ("Restriction", restriction_type),
                        ("Action", "Removed from DB"),
                    ], emoji="⏰")
                    continue

                member = guild.get_member(user_id)
                if not member:
                    # Member not in guild, just mark as removed in DB
                    self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)
                    logger.tree("Forbid Expired (Member Not Found)", [
                        ("User ID", str(user_id)),
                        ("Guild", guild.name),
                        ("Restriction", restriction_type),
                        ("Action", "Removed from DB"),
                    ], emoji="⏰")
                    continue

                # Get the forbid role
                role_name = self._get_role_name(restriction_type)
                role = discord.utils.get(guild.roles, name=role_name)

                if role and role in member.roles:
                    await member.remove_roles(role, reason="Forbid expired")

                # Mark as removed in DB
                self.db.remove_forbid(user_id, guild_id, restriction_type, self.bot.user.id)

                logger.tree("FORBID EXPIRED", [
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Restriction", restriction_type),
                    ("Guild", guild.name),
                ], emoji="⏰")

                # DM user about expiry
                expiry_embed = discord.Embed(
                    title="Restriction Expired",
                    description=f"Your **{RESTRICTIONS[restriction_type]['display']}** restriction has expired.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )
                expiry_embed.add_field(name="Server", value=guild.name, inline=True)
                expiry_embed.add_field(name="Restriction", value=RESTRICTIONS[restriction_type]['display'], inline=True)
                set_footer(expiry_embed)
                await safe_send_dm(member, embed=expiry_embed, context="Forbid Expiry DM")

            except Exception as e:
                logger.error("Forbid Expiry Processing Error", [
                    ("User ID", str(forbid.get("user_id", "unknown"))),
                    ("Guild ID", str(forbid.get("guild_id", "unknown"))),
                    ("Restriction", forbid.get("restriction_type", "unknown")),
                    ("Error", str(e)[:100]),
                ])


__all__ = ["SchedulerMixin"]
