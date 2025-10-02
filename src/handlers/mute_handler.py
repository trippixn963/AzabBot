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
Version: v2.3.0
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
        # === ITERATE THROUGH ALL EMBEDS IN MESSAGE ===
        # Logs channel may have multiple embeds per message
        # Check each one to see if it's a mute/timeout embed
        for embed in message.embeds:
            # === DEBUG LOG FOR EMBED STRUCTURE ===
            # Log basic embed info for troubleshooting/development
            logger.info(f"Processing embed - Title: {embed.title}, Author: {embed.author}")
            
            # === DETECT MUTE-RELATED EMBEDS ===
            # Look for mute/timeout keywords in any text field of embed
            # Different mod bots put these keywords in different locations
            # Combine all text fields into one string for comprehensive search
            embed_text: str = (str(embed.title or '') + str(embed.author.name if embed.author else '') + 
                         str(embed.description or '')).lower()
            
            # === SKIP NON-MUTE EMBEDS ===
            # If embed doesn't contain "mute" or "timeout" keywords, ignore it
            # This filters out unrelated embeds (bans, kicks, warnings, etc.)
            if 'mute' not in embed_text and 'timeout' not in embed_text:
                continue
            
            # === LOG MUTE EMBED DETECTION ===
            # Confirm we found a mute-related embed and show field count
            logger.info(f"Found mute embed with {len(embed.fields)} fields")
            
            # === INITIALIZE EXTRACTION VARIABLES ===
            # Store extracted information from embed fields
            user_id: Optional[int] = None      # Discord user ID (unique, reliable)
            user_name: Optional[str] = None    # Username (for fallback lookups)
            reason: Optional[str] = None       # Mute reason text
            
            # === TRY EXTRACTING USER ID FROM DESCRIPTION FIRST ===
            # Some moderation bots (like Dyno) put user mentions in description
            # Check description before fields for faster extraction
            if embed.description:
                # === REGEX PATTERN: <@!?(\d+)> ===
                # Matches Discord user mentions: <@123456> or <@!123456>
                # Capturing group (\d+) extracts the numeric user ID
                match = re.search(r'<@!?(\d+)>', embed.description)
                if match:
                    user_id = int(match.group(1))  # Convert captured ID string to integer
                    logger.info(f"Found user ID in description: {user_id}")
            
            # === EXTRACT INFORMATION FROM EMBED FIELDS ===
            # Most moderation bots use structured fields (User, Reason, Duration, etc.)
            # Iterate through all fields to find relevant information
            for field in embed.fields:
                # Convert field name to lowercase for case-insensitive matching
                field_name_lower: str = field.name.lower()
                # Log field for debugging (truncate value to 100 chars)
                logger.info(f"Field: {field.name} = {field.value[:100]}")
                
                # === DETECT USER FIELD ===
                # Different mod bots use different field names for the affected user
                # Check for common variations: User, Member, Target, Offender
                if any(x in field_name_lower for x in ['user', 'member', 'target', 'offender']):
                    # === EXTRACT USER MENTION (USER ID) ===
                    # Check if field contains a Discord user mention <@123456>
                    if '<@' in field.value:
                        # === REGEX PATTERN: <@!?(\d+)> ===
                        # Matches: <@123456> or <@!123456> (both formats valid)
                        # !? means optional exclamation mark (for mobile mentions)
                        # (\d+) captures the numeric user ID
                        match: Optional[re.Match[str]] = re.search(r'<@!?(\d+)>', field.value)
                        if match:
                            user_id = int(match.group(1))  # Extract and convert ID to integer
                            logger.info(f"Extracted user ID: {user_id}")
                    
                    # === EXTRACT USERNAME (FALLBACK) ===
                    # Also extract plain username text for fallback lookups
                    # Handles cases where field contains: "JohnDoe <@123456>" or just "JohnDoe"
                    # === REGEX PATTERN: ([^<>@]+?)(?:\s*<@|$) ===
                    # [^<>@]+? = Match any characters except <, >, @ (non-greedy)
                    # (?:\s*<@|$) = Stop at mention or end of string (non-capturing group)
                    user_name_match: Optional[re.Match[str]] = re.search(r'([^<>@]+?)(?:\s*<@|$)', field.value)
                    if user_name_match:
                        user_name = user_name_match.group(1).strip()  # Extract and trim whitespace
                        logger.info(f"Extracted username: {user_name}")
                    
                # === DETECT REASON FIELD ===
                # Look for fields with "reason" in the name
                # Contains the explanation/justification for the mute
                elif 'reason' in field_name_lower:
                    reason = field.value.strip()  # Extract and trim whitespace
                    logger.info(f"Extracted reason: {reason}")
            
            # === STORE EXTRACTED MUTE REASON ===
            # Only store if we successfully extracted a reason
            # Use dual-key storage (by ID and username) for reliability
            if reason:
                # === STORE BY USER ID (PRIMARY) ===
                # User ID is most reliable - never changes even if user changes username
                # This is the preferred lookup method
                if user_id:
                    self.prison_handler.mute_reasons[user_id] = reason
                    logger.success(f"Stored mute reason for user ID {user_id}: {reason}")
                
                # === STORE BY USERNAME (FALLBACK) ===
                # Also store by username for fallback lookups
                # Username can change, so this is secondary
                # Store in lowercase for case-insensitive lookups
                if user_name:
                    self.prison_handler.mute_reasons[user_name.lower()] = reason
                    logger.success(f"Stored mute reason for username {user_name}: {reason}")
            else:
                # === LOG WARNING IF REASON NOT FOUND ===
                # This helps identify embed formats we don't support yet
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
        # === VERIFY MEMBER HAS ROLES ATTRIBUTE ===
        # Safety check - ensure member object has roles (should always be true)
        # Prevents AttributeError if member is partial or invalid
        if hasattr(member, 'roles'):
            # === ITERATE THROUGH MEMBER'S ROLES ===
            # Check each role the member has
            for role in member.roles:
                # === CHECK IF ROLE MATCHES MUTED ROLE ID ===
                # If member has the configured muted role, they are imprisoned
                if role.id == muted_role_id:
                    return True  # User is muted
        
        # === USER NOT MUTED ===
        # Either member has no roles or doesn't have muted role
        return False