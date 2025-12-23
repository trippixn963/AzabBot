"""
Azab Discord Bot - Ban Command Cog
===================================

Server moderation ban/unban/softban commands.

Features:
    - /ban <user> [reason] [evidence]: Ban a user
    - /unban <user> [reason] [evidence]: Unban a user (with autocomplete)
    - /softban <user> [reason]: Ban + immediate unban (message purge)
    - Right-click context menu ban
    - Management role protection
    - DM notification before ban
    - Case logging with forum threads
    - Ban count tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CaseButtonView

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Autocomplete Functions
# =============================================================================

async def reason_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provide common ban reasons."""
    reasons = [
        "Spam / Advertising",
        "Harassment / Toxicity",
        "Raiding",
        "Scam / Phishing",
        "NSFW Content",
        "Impersonation",
        "Bot / Selfbot",
        "Evading punishment",
        "Breaking Discord ToS",
    ]
    return [
        app_commands.Choice(name=r, value=r)
        for r in reasons if current.lower() in r.lower()
    ][:25]


async def banned_user_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provide autocomplete for banned users."""
    try:
        bans = [entry async for entry in interaction.guild.bans(limit=25)]
        choices = []
        for ban_entry in bans:
            user = ban_entry.user
            display = f"{user.name} ({user.id})"
            if current.lower() in display.lower() or current in str(user.id):
                choices.append(app_commands.Choice(
                    name=display[:100],
                    value=str(user.id),
                ))
        return choices[:25]
    except Exception:
        return []


# =============================================================================
# Modal Classes
# =============================================================================

class BanModal(discord.ui.Modal, title="Ban User"):
    """Modal for banning a user from context menu."""

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Enter ban reason...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    evidence_input = discord.ui.TextInput(
        label="Evidence",
        placeholder="Link to evidence (message link, screenshot, etc.)",
        style=discord.TextStyle.short,
        required=False,
        max_length=500,
    )

    def __init__(self, target: discord.Member, cog: "BanCog"):
        super().__init__()
        self.target = target
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Process the ban when modal is submitted."""
        reason = self.reason_input.value or None
        evidence = self.evidence_input.value or None

        await self.cog.execute_ban(
            interaction=interaction,
            user=self.target,
            reason=reason,
            evidence=evidence,
        )


# =============================================================================
# Ban Cog
# =============================================================================

class BanCog(commands.Cog):
    """Ban/unban/softban command implementations."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        # Register context menu
        self.ban_context_menu = app_commands.ContextMenu(
            name="Ban User",
            callback=self.ban_context_callback,
        )
        self.bot.tree.add_command(self.ban_context_menu)

    async def cog_unload(self) -> None:
        """Remove context menu when cog unloads."""
        self.bot.tree.remove_command(self.ban_context_menu.name, type=self.ban_context_menu.type)

    # =========================================================================
    # Shared Ban Execution
    # =========================================================================

    async def execute_ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        is_softban: bool = False,
    ) -> bool:
        """
        Execute a ban with all validation and logging.

        Returns True if successful, False otherwise.
        """
        # Defer if not already responded
        if not interaction.response.is_done():
            await interaction.response.defer()

        # -----------------------------------------------------------------
        # Validation
        # -----------------------------------------------------------------

        if user.id == interaction.user.id:
            await interaction.followup.send("You cannot ban yourself.", ephemeral=True)
            return False

        if user.id == self.bot.user.id:
            await interaction.followup.send("I cannot ban myself.", ephemeral=True)
            return False

        if user.bot and not is_developer(interaction.user.id):
            await interaction.followup.send("You cannot ban bots.", ephemeral=True)
            return False

        # Role hierarchy check
        if isinstance(interaction.user, discord.Member):
            if user.top_role >= interaction.user.top_role and not is_developer(interaction.user.id):
                await interaction.followup.send(
                    "You cannot ban someone with an equal or higher role.",
                    ephemeral=True,
                )
                return False

        # Management protection
        if self.config.management_role_id and isinstance(interaction.user, discord.Member):
            management_role = interaction.guild.get_role(self.config.management_role_id)
            if management_role:
                user_has_management = management_role in user.roles
                mod_has_management = management_role in interaction.user.roles
                if user_has_management and mod_has_management and not is_developer(interaction.user.id):
                    if self.bot.mod_tracker:
                        await self.bot.mod_tracker.log_management_mute_attempt(
                            mod=interaction.user,
                            target=user,
                        )
                    embed = discord.Embed(
                        title="Action Blocked",
                        description="Management members cannot ban each other.",
                        color=EmbedColors.WARNING,
                    )
                    set_footer(embed)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return False

        # Bot role check
        if user.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                "I cannot ban this user because their role is higher than mine.",
                ephemeral=True,
            )
            return False

        # -----------------------------------------------------------------
        # DM User Before Ban
        # -----------------------------------------------------------------

        dm_sent = False
        if not is_softban:
            try:
                dm_embed = discord.Embed(
                    title="You have been banned",
                    color=EmbedColors.ERROR,
                )
                dm_embed.add_field(name="Server", value=f"`{interaction.guild.name}`", inline=False)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                dm_embed.set_thumbnail(url=user.display_avatar.url)
                set_footer(dm_embed)

                await user.send(embed=dm_embed)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        # -----------------------------------------------------------------
        # Prepare Case (before ban, while user is still in server)
        # -----------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.prepare_case(user)

        # -----------------------------------------------------------------
        # Execute Ban
        # -----------------------------------------------------------------

        action = "Softbanned" if is_softban else "Banned"
        ban_reason = f"{action} by {interaction.user}: {reason or 'No reason'}"

        try:
            await interaction.guild.ban(
                user,
                reason=ban_reason,
                delete_message_seconds=604800,  # 7 days
            )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to ban this user.", ephemeral=True)
            return False
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to ban: {e}", ephemeral=True)
            return False

        # -----------------------------------------------------------------
        # Softban: Immediate Unban
        # -----------------------------------------------------------------

        if is_softban:
            try:
                await interaction.guild.unban(user, reason=f"Softban by {interaction.user}")
            except Exception as e:
                logger.error("Softban Unban Failed", [("Error", str(e)[:50])])

        # -----------------------------------------------------------------
        # Increment Ban Count
        # -----------------------------------------------------------------

        db = get_db()
        ban_count = db.increment_ban_count(user.id)

        # -----------------------------------------------------------------
        # Logging
        # -----------------------------------------------------------------

        log_type = "USER SOFTBANNED" if is_softban else "USER BANNED"
        logger.tree(log_type, [
            ("User", f"{user} ({user.id})"),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence or "None")[:50]),
            ("Ban Count", str(ban_count)),
            ("DM Sent", "Yes" if dm_sent else "No"),
        ], emoji="🔨")

        # Server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_ban(
                user=user,
                reason=reason,
                moderator=interaction.user,
            )

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        title = "🧹 User Softbanned" if is_softban else "🔨 User Banned"
        embed = discord.Embed(
            title=title,
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="User", value=f"`{user.name}` ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        if case_info:
            embed.add_field(name="Case ID", value=f"`{case_info['case_id']}`", inline=True)
        if ban_count > 1:
            embed.add_field(name="Ban Count", value=f"`{ban_count}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        if evidence:
            embed.add_field(name="Evidence", value=evidence, inline=False)

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(interaction.guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Ban followup failed: {e}")

        # -----------------------------------------------------------------
        # Log to Case Forum
        # -----------------------------------------------------------------

        if self.bot.case_log_service and case_info and sent_message:
            await self.bot.case_log_service.log_ban(
                user=user,
                moderator=interaction.user,
                reason=f"[SOFTBAN] {reason}" if is_softban else reason,
                evidence=evidence,
                source_message_url=sent_message.jump_url,
            )

        # -----------------------------------------------------------------
        # Alt Detection (background task, regular bans only)
        # -----------------------------------------------------------------

        if not is_softban and self.bot.alt_detection and self.bot.alt_detection.enabled and case_info:
            asyncio.create_task(
                self.bot.alt_detection.detect_alts_for_ban(
                    banned_user=user,
                    guild=interaction.guild,
                    case_thread_id=case_info["thread_id"],
                )
            )

        return True

    # =========================================================================
    # Context Menu Ban
    # =========================================================================

    @app_commands.default_permissions(ban_members=True)
    async def ban_context_callback(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        """Handle right-click ban context menu."""
        modal = BanModal(target=user, cog=self)
        await interaction.response.send_modal(modal)

    # =========================================================================
    # /ban Command
    # =========================================================================

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        evidence="Message link or description of evidence",
        attachment="Screenshot or video evidence",
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        attachment: Optional[discord.Attachment] = None,
    ) -> None:
        """Ban a user from the server."""
        # Combine evidence sources
        if attachment:
            attachment_info = f"[{attachment.filename}]({attachment.url})"
            if evidence:
                evidence = f"{evidence}\n{attachment_info}"
            else:
                evidence = attachment_info

        await self.execute_ban(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=evidence,
        )

    # =========================================================================
    # /softban Command
    # =========================================================================

    @app_commands.command(name="softban", description="Ban and immediately unban a user (purges their messages)")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The user to softban",
        reason="Reason for the softban",
        attachment="Screenshot or video evidence",
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def softban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
        attachment: Optional[discord.Attachment] = None,
    ) -> None:
        """Softban a user (ban + immediate unban to purge messages)."""
        # Build evidence from attachment
        evidence = None
        if attachment:
            evidence = f"[{attachment.filename}]({attachment.url})"

        await self.execute_ban(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=evidence,
            is_softban=True,
        )

    # =========================================================================
    # /unban Command
    # =========================================================================

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The banned user to unban",
        reason="Reason for the unban",
        evidence="Link to evidence supporting the unban",
    )
    @app_commands.autocomplete(user=banned_user_autocomplete)
    async def unban(
        self,
        interaction: discord.Interaction,
        user: str,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> None:
        """Unban a user from the server."""
        await interaction.response.defer()

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

        # Check if actually banned
        try:
            await interaction.guild.fetch_ban(target_user)
        except discord.NotFound:
            await interaction.followup.send(f"{target_user} is not banned.", ephemeral=True)
            return

        # Execute unban
        unban_reason = f"Unbanned by {interaction.user}: {reason or 'No reason'}"

        try:
            await interaction.guild.unban(target_user, reason=unban_reason)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to unban users.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to unban: {e}", ephemeral=True)
            return

        # -----------------------------------------------------------------
        # Logging
        # -----------------------------------------------------------------

        logger.tree("USER UNBANNED", [
            ("User", f"{target_user} ({target_user.id})"),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence or "None")[:50]),
        ], emoji="🔓")

        # Server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_unban(
                user=target_user,
                moderator=interaction.user,
            )

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        # Check for existing case
        db = get_db()
        case = db.get_case_log(target_user.id)

        embed = discord.Embed(
            title="🔓 User Unbanned",
            color=EmbedColors.SUCCESS,
        )
        embed.add_field(name="User", value=f"`{target_user.name}` ({target_user.mention})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        if case:
            embed.add_field(name="Case ID", value=f"`{case['case_id']}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        if evidence:
            embed.add_field(name="Evidence", value=evidence, inline=False)

        embed.set_thumbnail(url=target_user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case:
                view = CaseButtonView(interaction.guild.id, case["thread_id"], target_user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Unban followup failed: {e}")

        # -----------------------------------------------------------------
        # Log to Case Forum
        # -----------------------------------------------------------------

        if self.bot.case_log_service and case and sent_message:
            await self.bot.case_log_service.log_unban(
                user_id=target_user.id,
                username=str(target_user),
                moderator=interaction.user,
                reason=reason,
                source_message_url=sent_message.jump_url,
            )


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the ban cog."""
    await bot.add_cog(BanCog(bot))
