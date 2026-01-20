"""
Case Button Views
=================

Buttons for case management (approve, edit, links).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.logger import logger
from src.utils.footer import set_footer

from .constants import CASE_EMOJI, MESSAGE_EMOJI, NOTE_EMOJI, APPROVE_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Case Button View
# =============================================================================

class CaseButtonView(discord.ui.View):
    """View with Case link button for public response."""

    def __init__(self, guild_id: int, thread_id: int, user_id: int):
        super().__init__(timeout=None)

        # Case link button (links to case thread with control panel)
        url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Case",
            url=url,
            style=discord.ButtonStyle.link,
            emoji=CASE_EMOJI,
        ))


# =============================================================================
# Message Button View
# =============================================================================

class MessageButtonView(discord.ui.View):
    """View with a single Message link button."""

    def __init__(self, jump_url: str):
        super().__init__(timeout=None)

        # Message link button
        self.add_item(discord.ui.Button(
            label="Message",
            url=jump_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))


# =============================================================================
# Edit Case Button & Modal
# =============================================================================

class EditCaseModal(discord.ui.Modal):
    """Modal for editing case reason."""

    def __init__(self, case_id: str, current_reason: Optional[str] = None):
        super().__init__(title="Edit Case Reason")
        self.case_id = case_id

        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Enter the updated reason for this case...",
            default=current_reason or "",
            required=False,
            max_length=1000,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        new_reason = self.reason_input.value.strip() or None

        try:
            # Update case in database
            db = get_db()
            success = db.update_case_reason(self.case_id, new_reason, interaction.user.id)

            if success:
                await interaction.response.send_message(
                    f"✏️ **Case Updated** by {interaction.user.mention}\n"
                    f"**New Reason:** {new_reason or 'No reason provided'}",
                    ephemeral=False,
                )

                logger.tree("Case Edited", [
                    ("Case ID", self.case_id),
                    ("Editor", f"{interaction.user} ({interaction.user.id})"),
                    ("New Reason", (new_reason or "None")[:50]),
                ], emoji="✏️")
            else:
                await interaction.response.send_message(
                    "❌ Failed to update case. Case may not exist.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error("Edit Case Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ An error occurred while updating the case.",
                ephemeral=True,
            )


class EditCaseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"edit_case:(?P<case_id>\w+)"):
    """
    Persistent edit button that allows moderators to edit case reason.

    Works after bot restart by using DynamicItem with regex pattern.
    Only moderators can use this button.
    """

    def __init__(self, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Edit",
                style=discord.ButtonStyle.secondary,
                emoji=NOTE_EMOJI,
                custom_id=f"edit_case:{case_id}",
            )
        )
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "EditCaseButton":
        """Reconstruct the button from the custom_id regex match."""
        case_id = match.group("case_id")
        return cls(case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle edit button click - only moderators can use."""
        logger.tree("Edit Case Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
        ], emoji="✏️")

        from src.core.config import get_config, is_developer

        config = get_config()

        # Check if user is moderator or developer
        is_mod = False
        if isinstance(interaction.user, discord.Member):
            if is_developer(interaction.user.id):
                is_mod = True
            elif interaction.user.guild_permissions.moderate_members:
                is_mod = True
            elif config.moderation_role_id and interaction.user.get_role(config.moderation_role_id):
                is_mod = True

        if not is_mod:
            await interaction.response.send_message(
                "❌ Only moderators can edit cases.",
                ephemeral=True,
            )
            return

        try:
            # Get current case info
            db = get_db()
            case = db.get_case(self.case_id)

            current_reason = case.get("reason") if case else None

            # Show edit modal
            modal = EditCaseModal(self.case_id, current_reason)
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error("Edit Case Button Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ Failed to open edit modal.",
                ephemeral=True,
            )


# =============================================================================
# Approve Button (Owner Only)
# =============================================================================

class ApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"approve_case:(?P<thread_id>\d+):(?P<case_id>\w+)"):
    """
    Persistent approve button that closes/archives the case thread when clicked by owner.

    Works after bot restart by using DynamicItem with regex pattern.
    Only the developer/owner can use this button.
    """

    def __init__(self, thread_id: int, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                emoji=APPROVE_EMOJI,
                custom_id=f"approve_case:{thread_id}:{case_id}",
            )
        )
        self.thread_id = thread_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "ApproveButton":
        """Reconstruct the button from the custom_id regex match."""
        thread_id = int(match.group("thread_id"))
        case_id = match.group("case_id")
        return cls(thread_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle approve button click - only owner can use."""
        from src.core.config import is_developer, get_config
        from src.services.case_log.transcript import TranscriptBuilder
        from src.services.case_log.views import CaseControlPanelView
        from src.services.case_log.embeds import build_control_panel_embed
        from src.utils.retry import safe_fetch_message, safe_edit

        config = get_config()

        # Only owner can approve
        if not is_developer(interaction.user.id):
            await interaction.response.send_message(
                "Only the owner can approve cases.",
                ephemeral=True,
            )
            return

        try:
            # Get the thread
            thread = interaction.channel
            if not isinstance(thread, discord.Thread):
                await interaction.response.send_message(
                    "This button can only be used in case threads.",
                    ephemeral=True,
                )
                return

            # Update database FIRST (before Discord action)
            db = get_db()
            db.approve_case(self.case_id, interaction.user.id)

            # Get case info for action-type-based deletion timing
            case_info = db.get_case(self.case_id)
            action_type = case_info.get("action_type", "mute") if case_info else "mute"

            # Calculate deletion time based on action type
            # Ban: 30 days, Mute: 14 days, Other: 7 days
            import time
            now = int(time.time())
            if action_type == "ban":
                retention_days = 30
            elif action_type in ("mute", "timeout"):
                retention_days = 14
            else:
                retention_days = 7
            deletion_timestamp = now + (retention_days * 24 * 60 * 60)

            # Build and save transcript immediately
            transcript_saved = False
            existing_transcript = db.get_case_transcript(self.case_id)
            if not existing_transcript:
                try:
                    # Fetch case info for target user and moderator names
                    case_info = db.get_case(self.case_id)
                    target_user_id = case_info.get("user_id") if case_info else None
                    moderator_id = case_info.get("moderator_id") if case_info else None

                    # Try to fetch user names from Discord
                    target_user_name = None
                    moderator_name = None

                    if target_user_id:
                        try:
                            target_user = await interaction.client.fetch_user(target_user_id)
                            target_user_name = target_user.display_name
                        except Exception:
                            pass

                    if moderator_id:
                        try:
                            moderator_user = await interaction.client.fetch_user(moderator_id)
                            moderator_name = moderator_user.display_name
                        except Exception:
                            pass

                    transcript_builder = TranscriptBuilder(
                        interaction.client,
                        config.transcript_assets_thread_id
                    )
                    transcript = await transcript_builder.build_from_thread(
                        thread=thread,
                        case_id=self.case_id,
                        target_user_id=target_user_id,
                        target_user_name=target_user_name,
                        moderator_id=moderator_id,
                        moderator_name=moderator_name,
                    )
                    if transcript:
                        transcript_saved = db.save_case_transcript(self.case_id, transcript.to_json())
                        if transcript_saved:
                            logger.tree("Transcript Created On Approval", [
                                ("Case ID", self.case_id),
                                ("Messages", str(transcript.message_count)),
                                ("Target", f"{target_user_name} ({target_user_id})"),
                                ("Moderator", f"{moderator_name} ({moderator_id})"),
                            ], emoji="📝")
                except Exception as e:
                    logger.warning("Transcript Creation Failed", [
                        ("Case ID", self.case_id),
                        ("Error", str(e)[:50]),
                    ])
            else:
                transcript_saved = True  # Already exists

            # Build approval embed with deletion time (NO transcript button here)
            embed = discord.Embed(
                title="✅ Case Approved",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(
                name="Approved By",
                value=interaction.user.mention,
                inline=True,
            )
            embed.add_field(
                name="Case ID",
                value=f"`{self.case_id}`",
                inline=True,
            )
            embed.add_field(
                name="🗑️ Auto-Delete",
                value=f"<t:{deletion_timestamp}:F>\n(<t:{deletion_timestamp}:R>)",
                inline=False,
            )
            set_footer(embed)

            # Send approval embed WITHOUT transcript button
            await interaction.response.send_message(embed=embed)

            # Update the control panel with transcript button
            transcript_url = None
            if config.case_transcript_base_url and transcript_saved:
                transcript_url = f"{config.case_transcript_base_url}/{self.case_id}"

            # Find and update the control panel
            case = db.get_case(self.case_id)
            if case:
                control_panel_msg_id = case.get("control_panel_message_id")

                # If not found, search pinned messages
                if not control_panel_msg_id:
                    try:
                        pinned = await thread.pins()
                        for msg in pinned:
                            if msg.embeds and msg.embeds[0].title and "Control Panel" in msg.embeds[0].title:
                                control_panel_msg_id = msg.id
                                db.set_case_control_panel_message(self.case_id, msg.id)
                                break
                    except Exception:
                        pass

                if control_panel_msg_id:
                    control_msg = await safe_fetch_message(thread, control_panel_msg_id)
                    if control_msg:
                        # Build updated control panel embed
                        # Note: Don't pass moderator here - use case data to preserve original moderator
                        control_embed = build_control_panel_embed(
                            case=case,
                            user=None,
                            moderator=None,  # Let it use case.get("moderator_id")
                            status="approved",
                        )

                        # Check if evidence exists
                        evidence_urls = db.get_case_evidence(self.case_id)
                        has_evidence = len(evidence_urls) > 0

                        # Build control panel view with transcript button
                        control_view = CaseControlPanelView(
                            user_id=case.get("user_id"),
                            guild_id=case.get("guild_id"),
                            case_id=self.case_id,
                            case_thread_id=thread.id,
                            status="approved",
                            is_mute=case.get("action_type") in ("mute", "timeout"),
                            has_evidence=has_evidence,
                            transcript_url=transcript_url,
                        )

                        await safe_edit(control_msg, embed=control_embed, view=control_view)
                        logger.tree("Control Panel Updated With Transcript", [
                            ("Case ID", self.case_id),
                            ("Has Transcript", "Yes" if transcript_url else "No"),
                        ], emoji="🎛️")

            # Add green check mark to thread name
            current_name = thread.name
            if not current_name.startswith("✅"):
                new_name = f"✅ | {current_name}"
                # Discord thread names max 100 chars
                if len(new_name) > 100:
                    new_name = new_name[:100]
                await thread.edit(name=new_name)

            # Update tags to show "Approved" status
            approved_tags = []
            if hasattr(interaction.client, 'case_log_service') and interaction.client.case_log_service:
                approved_tags = interaction.client.case_log_service.get_tags_for_case(
                    action_type, is_approved=True
                )

            # Lock the thread (but DON'T archive - keep visible during cooldown)
            # Thread will be deleted by scheduler after retention period
            if approved_tags:
                await thread.edit(
                    locked=True,
                    applied_tags=approved_tags,
                    reason=f"Case approved by {interaction.user.display_name}",
                )
            else:
                await thread.edit(
                    locked=True,
                    reason=f"Case approved by {interaction.user.display_name}",
                )

            tag_names = [t.name for t in approved_tags] if approved_tags else []
            logger.tree("Case Approved", [
                ("Case ID", self.case_id),
                ("Thread ID", str(self.thread_id)),
                ("Approved By", f"{interaction.user.display_name} ({interaction.user.id})"),
                ("Tags Updated", ", ".join(tag_names) if tag_names else "None"),
                ("Transcript", "Yes" if transcript_url else "No"),
                ("Deletes At", f"<t:{deletion_timestamp}:F>"),
            ], emoji="✅")

            # Log transcript via logging service
            if transcript_url and case and hasattr(interaction.client, 'logging_service') and interaction.client.logging_service:
                try:
                    user_id = case.get("user_id")
                    action_type = case.get("action_type", "unknown")
                    reason = case.get("reason") or "No reason provided"
                    moderator_id = case.get("moderator_id")
                    created_at = case.get("created_at")

                    # Try to get user info
                    try:
                        user = await interaction.client.fetch_user(user_id)
                    except Exception:
                        user = None

                    if user:
                        case_thread_url = f"https://discord.com/channels/{case.get('guild_id')}/{thread.id}"
                        await interaction.client.logging_service.log_case_transcript(
                            case_id=self.case_id,
                            user=user,
                            action_type=action_type,
                            moderator_id=moderator_id,
                            reason=reason,
                            created_at=created_at or 0,
                            approved_by=interaction.user,
                            transcript_url=transcript_url,
                            case_thread_url=case_thread_url,
                        )

                        logger.tree("Case Transcript Logged", [
                            ("Case ID", self.case_id),
                            ("User", user.name),
                        ], emoji="📜")
                except Exception as e:
                    logger.warning("Failed to Log Case Transcript", [
                        ("Case ID", self.case_id),
                        ("Error", str(e)[:50]),
                    ])

        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to archive this thread.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Approve Button Error", [
                ("Case ID", self.case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while approving the case.",
                        ephemeral=True,
                    )
            except discord.HTTPException as e:
                logger.debug(f"Approve error response failed: {e.code} - {e.text[:50] if e.text else 'No text'}")


__all__ = [
    "CaseButtonView",
    "MessageButtonView",
    "EditCaseModal",
    "EditCaseButton",
    "ApproveButton",
]
