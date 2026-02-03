"""
AzabBot - Unban Operations Mixin
================================

Execute unban command logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_evidence,
    get_target_guild,
    is_cross_server,
)
from src.utils.footer import set_footer
from src.views import CaseButtonView
from src.utils.duration import format_duration
from src.utils.dm_helpers import safe_send_dm
from src.core.constants import CASE_LOG_TIMEOUT, GUILD_FETCH_TIMEOUT, QUERY_LIMIT_TINY

from .autocomplete import banned_user_autocomplete, removal_reason_autocomplete

if TYPE_CHECKING:
    from .cog import BanCog


class UnbanOpsMixin:
    """Mixin for unban command operations."""

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.describe(
        user="The banned user to unban",
        reason="Reason for the unban",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(user=banned_user_autocomplete, reason=removal_reason_autocomplete)
    async def unban(
        self: "BanCog",
        interaction: discord.Interaction,
        user: str,
        reason: Optional[str] = None,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Unban a user from the server (supports cross-server from mod server)."""
        # Validate evidence attachment (content type, file size, CDN expiry warning)
        evidence_result = validate_evidence(evidence, "unban")
        if not evidence_result.is_valid:
            await interaction.response.send_message(
                evidence_result.error_message,
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Get target guild for cross-server moderation
        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Parse user ID
        try:
            uid = int(user.strip())
        except ValueError:
            await interaction.followup.send("Invalid user ID. Please provide a numeric ID.", ephemeral=True)
            return

        # Fetch user
        try:
            target_user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.followup.send(f"User with ID `{uid}` not found.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to fetch user: {e}", ephemeral=True)
            return

        # Check if actually banned on target guild
        try:
            await target_guild.fetch_ban(target_user)
        except discord.NotFound:
            guild_name = target_guild.name if cross_server else "this server"
            await interaction.followup.send(f"{target_user} is not banned in {guild_name}.", ephemeral=True)
            return

        # Execute unban on target guild
        unban_reason = f"Unbanned by {interaction.user}: {reason or 'No reason'}"

        try:
            await target_guild.unban(target_user, reason=unban_reason)
        except discord.Forbidden:
            logger.warning("Unban Failed (Forbidden)", [
                ("User", f"{target_user.name} ({target_user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to unban users.", ephemeral=True)
            return
        except discord.HTTPException as e:
            logger.error("Unban Failed (HTTP)", [
                ("User", f"{target_user.name} ({target_user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(f"Failed to unban: {e}", ephemeral=True)
            return

        # Record to ban history for History button
        db = get_db()
        db.add_unban(
            user_id=target_user.id,
            guild_id=target_guild.id,
            moderator_id=interaction.user.id,
            reason=reason,
        )

        # -----------------------------------------------------------------
        # DM User About Unban
        # -----------------------------------------------------------------

        dm_embed = discord.Embed(
            title="You've Been Unbanned",
            description=f"Your ban from **{target_guild.name}** has been lifted.",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        dm_embed.add_field(name="Server", value=target_guild.name, inline=True)
        if reason:
            dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.add_field(
            name="What's Next?",
            value="You can now rejoin the server if you have an invite link.",
            inline=False,
        )
        dm_embed.set_footer(text=f"Server ID: {target_guild.id}")

        dm_sent = await safe_send_dm(target_user, embed=dm_embed, context="Unban DM")
        logger.tree("Unban DM Sent", [
            ("User", target_user.name),
            ("ID", str(target_user.id)),
            ("Delivered", "Yes" if dm_sent else "No (DMs disabled)"),
        ], emoji="📨")

        # -----------------------------------------------------------------
        # Logging
        # -----------------------------------------------------------------

        log_items = [
            ("User", target_user.name),
            ("ID", str(target_user.id)),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence_result.url or "None")[:50]),
        ]
        if cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree("USER UNBANNED", log_items, emoji="🔓")

        # -----------------------------------------------------------------
        # Log to Case Forum (finds active ban case and resolves it)
        # -----------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_unban(
                        user_id=target_user.id,
                        username=str(target_user),
                        moderator=interaction.user,
                        reason=reason,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Resolved", [
                        ("Action", "Unban"),
                        ("Case ID", case_info["case_id"]),
                        ("User", f"{target_user.name} ({target_user.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Unban"),
                    ("User", target_user.name),
                    ("ID", str(target_user.id)),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Unban case logging timed out for {target_user} ({target_user.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Unban"),
                    ("User", target_user.name),
                    ("ID", str(target_user.id)),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Unban case logging failed for {target_user} ({target_user.id}): {str(e)[:200]}"
                    )

        # Server logs (after case creation to include case_id)
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await asyncio.wait_for(
                    self.bot.logging_service.log_unban(
                        user=target_user,
                        moderator=interaction.user,
                        case_id=case_info["case_id"] if case_info else None,
                    ),
                    timeout=GUILD_FETCH_TIMEOUT,
                )
            except Exception as e:
                logger.debug(f"Server log failed (unban): {e}")

        # Get ban duration from history
        ban_duration = None
        ban_history = db.get_ban_history(target_user.id, target_guild.id, limit=QUERY_LIMIT_TINY)
        for record in ban_history:
            if record.get("action") == "ban":
                banned_seconds = int(time.time() - record["timestamp"])
                ban_duration = format_duration(banned_seconds, show_seconds=True)
                break

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        embed = discord.Embed(
            title="🔓 User Unbanned",
            color=EmbedColors.GREEN,
        )
        embed.add_field(name="User", value=target_user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)
        if ban_duration:
            embed.add_field(name="Was Banned For", value=f"`{ban_duration}`", inline=True)

        # Note: Reason/Evidence intentionally not shown in public embed
        # Only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=target_user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], target_user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("Unban Followup Failed", [
                ("User", f"{target_user.name} ({target_user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])


__all__ = ["UnbanOpsMixin"]
