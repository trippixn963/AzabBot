"""
Azab Discord Bot - Mute Handler
===============================

Handles mute detection and embed processing from logs channel.
Extracts mute reasons and user information from moderation embeds.

Features:
- Process mute embeds from logs channel
- Extract user IDs and mute reasons from multiple formats
- Store mute information by both ID and username
- Support various moderation bot embed formats
- Detect both role-based mutes and Discord timeouts

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import re
from typing import Optional, Any

from src.core.logger import logger


class MuteHandler:
    """
    Processes mute-related embeds and extracts information.

    Monitors the logs channel for mute embeds and extracts:
    - User ID and username from embed fields
    - Mute reason for contextual AI responses
    - Stores information for later retrieval
    """

    def __init__(self, prison_handler: Any) -> None:
        """
        Initialize the mute handler.

        Args:
            prison_handler: Reference to prison handler for storing mute reasons
        """
        self.prison_handler: Any = prison_handler

    async def process_mute_embed(self, message: discord.Message) -> None:
        """
        Process mute embeds from logs channel to extract reasons.

        Monitors the logs channel for mute embeds and extracts:
        - User ID and username from embed fields
        - Mute reason for contextual AI responses
        - Stores information in mute_reasons dict for later use

        Process Flow:
        1. Check if embed contains mute/timeout keywords
        2. Extract user ID from description or fields
        3. Extract username from user fields
        4. Extract reason from reason fields
        5. Store both user_id and username mappings for reliability

        Args:
            message (discord.Message): Message containing mute embed
        """
        for embed in message.embeds:
            logger.info(f"Processing embed - Title: {embed.title}, Author: {embed.author}")

            # DESIGN: Check multiple embed locations for mute detection
            # Different mod bots put "mute" in different places (title, author, description)
            # Combining all text ensures we catch all mod bot formats
            embed_text: str = (str(embed.title or '') + str(embed.author.name if embed.author else '') +
                         str(embed.description or '')).lower()

            # DESIGN: Early exit for non-mute embeds
            # Saves processing time on unrelated log messages (joins, messages, etc.)
            if 'mute' not in embed_text and 'timeout' not in embed_text:
                continue

            logger.info(f"Found mute embed with {len(embed.fields)} fields")

            user_id: Optional[int] = None
            user_name: Optional[str] = None
            reason: Optional[str] = None

            # DESIGN: Try extracting user ID from description first
            # Some mod bots put user mention in description instead of fields
            # Regex pattern <@!?(\d+)> matches both <@123> and <@!123> formats
            if embed.description:
                match: Optional[re.Match[str]] = re.search(r'<@!?(\d+)>', embed.description)
                if match:
                    user_id = int(match.group(1))
                    logger.info(f"Found user ID in description: {user_id}")

            # DESIGN: Parse embed fields to extract user info and mute reason
            # Field names vary by mod bot: "User", "Member", "Target", "Offender", "Reason"
            # Lowercase comparison ensures we catch all variations
            for field in embed.fields:
                field_name_lower: str = field.name.lower()
                logger.info(f"Field: {field.name} = {field.value[:100]}")

                # DESIGN: Check multiple field name keywords for user identification
                # Different mod bots use different field names for the same information
                # any() checks all variations in one pass for efficiency
                if any(x in field_name_lower for x in ['user', 'member', 'target', 'offender']):
                    if '<@' in field.value:
                        match: Optional[re.Match[str]] = re.search(r'<@!?(\d+)>', field.value)
                        if match:
                            user_id = int(match.group(1))
                            logger.info(f"Extracted user ID: {user_id}")

                    # DESIGN: Extract plain username without mention tags
                    # Regex captures everything before <@ or end of string
                    # "username123 <@123>" → "username123"
                    user_name_match: Optional[re.Match[str]] = re.search(r'([^<>@]+?)(?:\s*<@|$)', field.value)
                    if user_name_match:
                        user_name = user_name_match.group(1).strip()
                        logger.info(f"Extracted username: {user_name}")

                elif 'reason' in field_name_lower:
                    reason = field.value.strip()
                    logger.info(f"Extracted reason: {reason}")

            # DESIGN: Store mute reason by both user_id AND username for reliability
            # Moderation logs are inconsistent - sometimes only ID available, sometimes only username
            # Dual storage ensures AI can always find context regardless of embed format
            # Lowercase username for case-insensitive lookups (kamarian = Kamarian = KAMARIAN)
            if reason:
                if user_id:
                    self.prison_handler.mute_reasons[user_id] = reason
                    logger.success(f"Stored mute reason for user ID {user_id}: {reason}")

                if user_name:
                    self.prison_handler.mute_reasons[user_name.lower()] = reason
                    logger.success(f"Stored mute reason for username {user_name}: {reason}")
            else:
                logger.warning("Could not extract mute reason from embed")

    def is_user_muted(self, member: discord.Member, muted_role_id: int) -> bool:
        """
        Check if a user has the muted role.

        Checks if the given member has the configured muted role by iterating
        through their roles. This is used to determine if a user is currently
        imprisoned/muted. Does NOT check Discord's native timeout feature.

        Args:
            member: Discord member to check
            muted_role_id: ID of the muted role from .env configuration

        Returns:
            bool: True if user has muted role, False otherwise
        """
        # DESIGN: Iterate through roles manually instead of using member.get_role()
        # get_role() requires guild.roles lookup which adds extra API calls
        # Direct iteration through member.roles is O(n) but roles list is small (~5-15)
        # hasattr check prevents AttributeError if member object is malformed
        if hasattr(member, 'roles'):
            for role in member.roles:
                if role.id == muted_role_id:
                    return True

        return False
