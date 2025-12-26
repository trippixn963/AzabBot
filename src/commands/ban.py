"""
Azab Discord Bot - Ban Command Cog
===================================

Server moderation ban/unban commands.

Features:
    - /ban <user> [reason] [evidence]: Ban a user
    - /unban <user> [reason] [evidence]: Unban a user (with autocomplete)
    - Right-click context menu ban
    - Management role protection
    - DM notification before ban
    - Case logging with forum threads
    - Ban count tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time

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
    """Provide autocomplete for banned users (supports cross-server)."""
    try:
        config = get_config()

        # Determine target guild (cross-server support)
        target_guild = interaction.guild
        if (config.mod_server_id and
            config.logging_guild_id and
            interaction.guild.id == config.mod_server_id):
            main_guild = interaction.client.get_guild(config.logging_guild_id)
            if main_guild:
                target_guild = main_guild

        bans = [entry async for entry in target_guild.bans(limit=25)]
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

    def __init__(self, target: discord.Member, cog: "BanCog", evidence: Optional[str] = None):
        super().__init__()
        self.target = target
        self.cog = cog
        self.evidence = evidence

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Process the ban when modal is submitted."""
        reason = self.reason_input.value or None

        await self.cog.execute_ban(
            interaction=interaction,
            user=self.target,
            reason=reason,
            evidence=self.evidence,
        )


# =============================================================================
# Ban Cog
# =============================================================================

class BanCog(commands.Cog):
    """Ban/unban command implementations."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        # Register context menus
        self.ban_user_ctx = app_commands.ContextMenu(
            name="Ban User",
            callback=self._ban_from_user,
        )
        self.ban_message_ctx = app_commands.ContextMenu(
            name="Ban Author",
            callback=self._ban_from_message,
        )
        self.bot.tree.add_command(self.ban_user_ctx)
        self.bot.tree.add_command(self.ban_message_ctx)

    async def cog_unload(self) -> None:
        """Remove context menus when cog unloads."""
        self.bot.tree.remove_command(self.ban_user_ctx.name, type=self.ban_user_ctx.type)
        self.bot.tree.remove_command(self.ban_message_ctx.name, type=self.ban_message_ctx.type)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_target_guild(self, interaction: discord.Interaction) -> discord.Guild:
        """
        Get the target guild for moderation actions.

        If command is run from mod server, targets the main server.
        Otherwise, targets the current server.
        """
        # If in mod server and main guild is configured, target main guild
        if (self.config.mod_server_id and
            self.config.logging_guild_id and
            interaction.guild.id == self.config.mod_server_id):
            main_guild = self.bot.get_guild(self.config.logging_guild_id)
            if main_guild:
                return main_guild
        return interaction.guild

    def _is_cross_server(self, interaction: discord.Interaction) -> bool:
        """Check if this is a cross-server moderation action."""
        return (self.config.mod_server_id and
                self.config.logging_guild_id and
                interaction.guild.id == self.config.mod_server_id)

    def _format_ban_duration(self, seconds: int) -> str:
        """Format seconds into a human-readable ban duration."""
        if seconds < 60:
            return f"{seconds}s"

        parts = []
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 and days == 0:  # Only show minutes if less than a day
            parts.append(f"{minutes}m")

        return " ".join(parts) if parts else "< 1m"

    # =========================================================================
    # Shared Ban Execution
    # =========================================================================

    async def execute_ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        is_softban: bool = False,
    ) -> bool:
        """
        Execute a ban with all validation and logging.

        Supports cross-server moderation: when run from mod server,
        the ban is executed on the main server.

        Returns True if successful, False otherwise.
        """
        # Defer if not already responded
        if not interaction.response.is_done():
            await interaction.response.defer()

        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = self._get_target_guild(interaction)
        is_cross_server = self._is_cross_server(interaction)

        # Try to get member from target guild for role checks
        target_member = target_guild.get_member(user.id)

        # -----------------------------------------------------------------
        # Validation
        # -----------------------------------------------------------------

        if user.id == interaction.user.id:
            logger.tree("BAN BLOCKED", [
                ("Reason", "Self-ban attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("You cannot ban yourself.", ephemeral=True)
            return False

        if user.id == self.bot.user.id:
            logger.tree("BAN BLOCKED", [
                ("Reason", "Bot self-ban attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("I cannot ban myself.", ephemeral=True)
            return False

        if user.bot and not is_developer(interaction.user.id):
            logger.tree("BAN BLOCKED", [
                ("Reason", "Target is a bot"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("You cannot ban bots.", ephemeral=True)
            return False

        # Role hierarchy check (only if target is a member of target guild)
        if target_member and isinstance(interaction.user, discord.Member):
            # For cross-server, get mod's roles from main server if they're a member there
            mod_member = target_guild.get_member(interaction.user.id) if is_cross_server else interaction.user
            if mod_member and target_member.top_role >= mod_member.top_role and not is_developer(interaction.user.id):
                logger.tree("BAN BLOCKED", [
                    ("Reason", "Role hierarchy"),
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Mod Role", mod_member.top_role.name),
                    ("Target", f"{user} ({user.id})"),
                    ("Target Role", target_member.top_role.name),
                ], emoji="🚫")
                await interaction.followup.send(
                    "You cannot ban someone with an equal or higher role.",
                    ephemeral=True,
                )
                return False

        # Management protection (only if target is a member)
        if self.config.moderation_role_id and target_member:
            management_role = target_guild.get_role(self.config.moderation_role_id)
            mod_member = target_guild.get_member(interaction.user.id) if is_cross_server else interaction.user
            if management_role and mod_member and isinstance(mod_member, discord.Member):
                user_has_management = management_role in target_member.roles
                mod_has_management = management_role in mod_member.roles
                if user_has_management and mod_has_management and not is_developer(interaction.user.id):
                    logger.tree("BAN BLOCKED", [
                        ("Reason", "Management protection"),
                        ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                        ("Target", f"{user} ({user.id})"),
                    ], emoji="🚫")
                    if self.bot.mod_tracker:
                        await self.bot.mod_tracker.log_management_mute_attempt(
                            mod=interaction.user,
                            target=target_member,
                        )
                    embed = discord.Embed(
                        title="Action Blocked",
                        description="Management members cannot ban each other.",
                        color=EmbedColors.WARNING,
                    )
                    set_footer(embed)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return False

        # Bot role check (only if target is a member)
        if target_member and target_member.top_role >= target_guild.me.top_role:
            logger.tree("BAN BLOCKED", [
                ("Reason", "Bot role too low"),
                ("Target Role", target_member.top_role.name),
                ("Bot Top Role", target_guild.me.top_role.name),
            ], emoji="🚫")
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
                dm_embed.add_field(name="Server", value=f"`{target_guild.name}`", inline=False)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                dm_embed.set_thumbnail(url=user.display_avatar.url)
                set_footer(dm_embed)

                await user.send(embed=dm_embed)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        # -----------------------------------------------------------------
        # Execute Ban (on target guild)
        # -----------------------------------------------------------------

        action = "Softbanned" if is_softban else "Banned"
        ban_reason = f"{action} by {interaction.user}: {reason or 'No reason'}"

        try:
            await target_guild.ban(
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
                await target_guild.unban(user, reason=f"Softban by {interaction.user}")
            except Exception as e:
                logger.error("Softban Unban Failed", [("Error", str(e)[:50])])

        # -----------------------------------------------------------------
        # Increment Ban Count (store moderator and reason for unban context)
        # -----------------------------------------------------------------

        db = get_db()
        ban_count = db.increment_ban_count(user.id, interaction.user.id, reason)

        # Record to ban history for History button
        db.add_ban(
            user_id=user.id,
            guild_id=target_guild.id,
            moderator_id=interaction.user.id,
            reason=reason,
        )

        # -----------------------------------------------------------------
        # Logging
        # -----------------------------------------------------------------

        log_type = "USER SOFTBANNED" if is_softban else "USER BANNED"
        log_items = [
            ("User", f"{user} ({user.id})"),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence or "None")[:50]),
            ("Ban Count", str(ban_count)),
            ("DM Sent", "Yes" if dm_sent else "No"),
        ]
        if is_cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree(log_type, log_items, emoji="🔨")

        # Server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_ban(
                user=user,
                reason=reason,
                moderator=interaction.user,
            )

        # -----------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # -----------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.log_ban(
                user=user,
                moderator=interaction.user,
                reason=f"[SOFTBAN] {reason}" if is_softban else reason,
                evidence=evidence,
            )

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        title = "🧹 User Softbanned" if is_softban else "🔨 User Banned"
        action_word = "softbanned" if is_softban else "banned"
        embed = discord.Embed(
            title=title,
            description=f"**{user.display_name}** has been {action_word} from the server.",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="User", value=f"`{user.name}`\n{user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`\n{interaction.user.mention}", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)
        if ban_count > 1:
            embed.add_field(name="Ban Count", value=f"`{ban_count}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Note: Evidence is intentionally not shown in public embed
        # It's only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Ban followup failed: {e}")

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
    # Context Menu Handlers
    # =========================================================================

    @app_commands.default_permissions(ban_members=True)
    async def _ban_from_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        """Ban a user directly (context menu handler)."""
        if user.bot and not is_developer(interaction.user.id):
            await interaction.response.send_message(
                "You cannot ban bots.",
                ephemeral=True,
            )
            return

        modal = BanModal(target=user, cog=self, evidence=None)
        await interaction.response.send_modal(modal)

    @app_commands.default_permissions(ban_members=True)
    async def _ban_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """Ban the author of a message (context menu handler)."""
        if message.author.bot and not is_developer(interaction.user.id):
            await interaction.response.send_message(
                "You cannot ban bots.",
                ephemeral=True,
            )
            return

        # Get evidence from message attachment if it's an image/video
        evidence = None
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
                evidence = attachment.url
                break

        user = interaction.guild.get_member(message.author.id)
        if not user:
            await interaction.response.send_message(
                "User is no longer in this server.",
                ephemeral=True,
            )
            return

        modal = BanModal(target=user, cog=self, evidence=evidence)
        await interaction.response.send_modal(modal)

    # =========================================================================
    # /ban Command
    # =========================================================================

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban (required)",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Ban a user from the server (supports cross-server from mod server)."""
        # Validate attachment is image/video if provided
        evidence_url = None
        if evidence:
            valid_types = ('image/', 'video/')
            if not evidence.content_type or not evidence.content_type.startswith(valid_types):
                await interaction.response.send_message(
                    "Evidence must be an image or video file.",
                    ephemeral=True,
                )
                return
            evidence_url = evidence.url

        await self.execute_ban(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=evidence_url,
        )

    # =========================================================================
    # /unban Command
    # =========================================================================

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The banned user to unban",
        reason="Reason for the unban",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(user=banned_user_autocomplete)
    async def unban(
        self,
        interaction: discord.Interaction,
        user: str,
        reason: Optional[str] = None,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Unban a user from the server (supports cross-server from mod server)."""
        # Validate attachment is image/video if provided
        evidence_url = None
        if evidence:
            valid_types = ('image/', 'video/')
            if not evidence.content_type or not evidence.content_type.startswith(valid_types):
                await interaction.response.send_message(
                    "Evidence must be an image or video file.",
                    ephemeral=True,
                )
                return
            evidence_url = evidence.url

        await interaction.response.defer()

        # Get target guild for cross-server moderation
        target_guild = self._get_target_guild(interaction)
        is_cross_server = self._is_cross_server(interaction)

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
            guild_name = target_guild.name if is_cross_server else "this server"
            await interaction.followup.send(f"{target_user} is not banned in {guild_name}.", ephemeral=True)
            return

        # Execute unban on target guild
        unban_reason = f"Unbanned by {interaction.user}: {reason or 'No reason'}"

        try:
            await target_guild.unban(target_user, reason=unban_reason)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to unban users.", ephemeral=True)
            return
        except discord.HTTPException as e:
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
        # Logging
        # -----------------------------------------------------------------

        log_items = [
            ("User", f"{target_user} ({target_user.id})"),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence_url or "None")[:50]),
        ]
        if is_cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree("USER UNBANNED", log_items, emoji="🔓")

        # Server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_unban(
                user=target_user,
                moderator=interaction.user,
            )

        # -----------------------------------------------------------------
        # Log to Case Forum (finds active ban case and resolves it)
        # -----------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.log_unban(
                user_id=target_user.id,
                username=str(target_user),
                moderator=interaction.user,
                reason=reason,
            )

        # Get ban duration from history
        ban_duration = None
        ban_history = db.get_ban_history(target_user.id, target_guild.id, limit=5)
        for record in ban_history:
            if record.get("action") == "ban":
                banned_seconds = int(time.time() - record["timestamp"])
                ban_duration = self._format_ban_duration(banned_seconds)
                break

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        embed = discord.Embed(
            title="🔓 User Unbanned",
            description=f"**{target_user.name}** has been unbanned from the server.",
            color=EmbedColors.SUCCESS,
        )
        embed.add_field(name="User", value=f"`{target_user.name}`\n{target_user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`\n{interaction.user.mention}", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)
        if ban_duration:
            embed.add_field(name="Was Banned For", value=f"`{ban_duration}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Note: Evidence is intentionally not shown in public embed
        # It's only visible in case logs and mod logs

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
            logger.error(f"Unban followup failed: {e}")


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the ban cog."""
    await bot.add_cog(BanCog(bot))
