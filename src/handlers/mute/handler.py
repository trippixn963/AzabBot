"""
AzabBot - Mute Handler
======================

Handles mute detection and embed processing from mod logs.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import re
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.handlers.prison.handler import PrisonHandler


# =============================================================================
# Mute Handler Class
# =============================================================================

class MuteHandler:
    """
    Processes mute-related embeds and extracts information.

    DESIGN:
        Parses embed structure to find user ID, username, and mute reason.
        Stores reasons in the prison handler for context.
        Handles multiple mod bot formats gracefully.

    Attributes:
        prison: Reference to the prison handler for storing reasons.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, prison: "PrisonHandler") -> None:
        """
        Initialize the mute handler.

        Args:
            prison: Prison handler instance for storing mute reasons.
        """
        self.prison = prison

        logger.tree("Mute Handler Loaded", [
            ("Purpose", "Parse mute embeds from logs"),
            ("Storage", "prison.mute_reasons"),
        ], emoji="🔒")

    # =========================================================================
    # Embed Processing
    # =========================================================================

    async def process_mute_embed(self, message: discord.Message) -> None:
        """
        Process mute embeds from logs channel to extract reasons.

        DESIGN:
            Iterates through all embeds in the message.
            Checks title, author, and description for mute keywords.
            Extracts user ID via mention pattern and username via regex.
            Stores reason indexed by both user ID and lowercase username.

        Args:
            message: Discord message containing potential mute embeds.
        """
        try:
            logger.tree("Processing Mute Embed", [
                ("Message ID", str(message.id)),
                ("Embed Count", str(len(message.embeds))),
                ("Channel", message.channel.name if hasattr(message.channel, 'name') else str(message.channel.id)),
            ], emoji="📝")

            for embed in message.embeds:
                # Check if this is a mute embed
                embed_text = (
                    str(embed.title or "")
                    + str(embed.author.name if embed.author else "")
                    + str(embed.description or "")
                ).lower()

                if "mute" not in embed_text and "timeout" not in embed_text:
                    continue

                user_id: Optional[int] = None
                user_name: Optional[str] = None
                reason: Optional[str] = None

                # -------------------------------------------------------------
                # Extract User ID from Description
                # -------------------------------------------------------------

                if embed.description:
                    match = re.search(r"<@!?(\d+)>", embed.description)
                    if match:
                        user_id = int(match.group(1))

                # -------------------------------------------------------------
                # Parse Embed Fields
                # -------------------------------------------------------------

                for field in embed.fields:
                    field_name_lower = field.name.lower()

                    # User/Member/Target field
                    if any(x in field_name_lower for x in ["user", "member", "target", "offender"]):
                        if "<@" in field.value:
                            match = re.search(r"<@!?(\d+)>", field.value)
                            if match:
                                user_id = int(match.group(1))

                        # Extract username
                        user_name_match = re.search(r"([^<>@]+?)(?:\s*<@|$)", field.value)
                        if user_name_match:
                            user_name = user_name_match.group(1).strip()

                    # Reason field
                    elif "reason" in field_name_lower:
                        reason = field.value.strip()

                # -------------------------------------------------------------
                # Store Mute Reason (with lock for thread safety)
                # -------------------------------------------------------------

                if reason:
                    async with self.prison._state_lock:
                        # LRU eviction if at limit
                        while len(self.prison.mute_reasons) >= self.prison._mute_reasons_limit:
                            try:
                                self.prison.mute_reasons.popitem(last=False)
                            except KeyError:
                                break

                        if user_id:
                            self.prison.mute_reasons[user_id] = reason
                            logger.tree("Mute Reason Captured", [
                                ("User ID", str(user_id)),
                                ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
                            ], emoji="🔒")

                        if user_name:
                            self.prison.mute_reasons[user_name.lower()] = reason
                            logger.tree("Mute Reason Captured", [
                                ("Username", user_name),
                                ("Reason", reason[:50] + "..." if len(reason) > 50 else reason),
                            ], emoji="🔒")

        except Exception as e:
            logger.error("Mute Embed Processing Failed", [
                ("Message ID", str(message.id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Mute Status Check
    # =========================================================================

    def is_user_muted(self, member: discord.Member, muted_role_id: int) -> bool:
        """
        Check if a user has the muted role.

        DESIGN:
            Simple role ID check for mute status.
            Handles edge cases where member.roles might not exist.

        Args:
            member: Discord member to check.
            muted_role_id: ID of the muted role.

        Returns:
            True if member has the muted role.
        """
        if hasattr(member, "roles"):
            for role in member.roles:
                if role.id == muted_role_id:
                    return True
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteHandler"]
