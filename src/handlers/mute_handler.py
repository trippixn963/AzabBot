"""
Azab Discord Bot - Mute Handler
===============================

Handles mute detection and embed processing from logs channel.
Extracts mute reasons and user information from moderation embeds.

Features:
- Process mute embeds from logs channel
- Extract user IDs and mute reasons
- Store mute information for later use
- Support various embed formats

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import re
from typing import Optional

from src.core.logger import logger


class MuteHandler:
    """
    Processes mute-related embeds and extracts information.
    
    Monitors the logs channel for mute embeds and extracts:
    - User ID and username from embed fields
    - Mute reason for contextual AI responses
    - Stores information for later retrieval
    """
    
    def __init__(self, prison_handler):
        """
        Initialize the mute handler.
        
        Args:
            prison_handler: Reference to prison handler for storing mute reasons
        """
        self.prison_handler = prison_handler
    
    async def process_mute_embed(self, message: discord.Message):
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
            # Debug log the embed structure
            logger.info(f"Processing embed - Title: {embed.title}, Author: {embed.author}")
            
            # Look for mute embeds (check title, author name, or description)
            # Combine all text fields to search for mute-related keywords
            embed_text = (str(embed.title or '') + str(embed.author.name if embed.author else '') + 
                         str(embed.description or '')).lower()
            
            # Skip if this embed is not related to muting/timeout
            if 'mute' not in embed_text and 'timeout' not in embed_text:
                continue
            
            logger.info(f"Found mute embed with {len(embed.fields)} fields")
            
            user_id = None
            user_name = None
            reason = None
            
            # First try to extract from description if it exists
            # Some moderation bots put user mentions in the description
            if embed.description:
                # Try to extract user mention from description using regex
                match = re.search(r'<@!?(\d+)>', embed.description)
                if match:
                    user_id = int(match.group(1))
                    logger.info(f"Found user ID in description: {user_id}")
            
            # Extract info from embed fields
            # Most moderation bots use structured fields for user and reason
            for field in embed.fields:
                field_name_lower = field.name.lower()
                logger.info(f"Field: {field.name} = {field.value[:100]}")
                
                # Check for user field (might be called User, Member, Target, etc.)
                # Different moderation bots use different field names
                if any(x in field_name_lower for x in ['user', 'member', 'target', 'offender']):
                    # Extract username and/or mention from user field
                    if '<@' in field.value:
                        # Try to extract user mention using regex
                        match = re.search(r'<@!?(\d+)>', field.value)
                        if match:
                            user_id = int(match.group(1))
                            logger.info(f"Extracted user ID: {user_id}")
                    
                    # Also extract username (remove mention part if exists)
                    # This handles cases where both username and mention are present
                    user_name_match = re.search(r'([^<>@]+?)(?:\s*<@|$)', field.value)
                    if user_name_match:
                        user_name = user_name_match.group(1).strip()
                        logger.info(f"Extracted username: {user_name}")
                    
                # Check for reason field
                # Look for fields containing the mute reason
                elif 'reason' in field_name_lower:
                    reason = field.value.strip()
                    logger.info(f"Extracted reason: {reason}")
            
            # Store the reason if we found it
            # Store both user_id and username mappings for maximum reliability
            if reason:
                if user_id:
                    # Primary storage by user ID (most reliable)
                    self.prison_handler.mute_reasons[user_id] = reason
                    logger.success(f"Stored mute reason for user ID {user_id}: {reason}")
                if user_name:
                    # Also store by username for fallback (case-insensitive)
                    self.prison_handler.mute_reasons[user_name.lower()] = reason
                    logger.success(f"Stored mute reason for username {user_name}: {reason}")
            else:
                logger.warning("Could not extract mute reason from embed")
    
    def is_user_muted(self, member: discord.Member, muted_role_id: int) -> bool:
        """
        Check if a user has the muted role.
        
        Args:
            member: Discord member to check
            muted_role_id: ID of the muted role
            
        Returns:
            bool: True if user has muted role, False otherwise
        """
        # Only check for muted role, ignore Discord timeouts
        if hasattr(member, 'roles'):
            for role in member.roles:
                if role.id == muted_role_id:
                    return True
        
        return False