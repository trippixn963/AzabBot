"""
Azab Discord Bot - Input Validators
===================================

Comprehensive input validation utilities for safe data handling.

Features:
- Discord ID validation with range checking
- Message content sanitization
- Username validation and truncation
- Channel and role validation
- SQL injection prevention
- Rate limit validation
- Timestamp validation
- List of IDs validation
- Discord embed validation
- High-level input sanitization wrapper

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import Optional, Union, List, Any
from datetime import datetime
import discord

from src.core.logger import logger


class ValidationError(Exception):
    """Custom exception for validation failures"""

    pass


class Validators:
    """Input validation utilities"""

    # Discord limits
    DISCORD_ID_MIN = 10000000000000000  # 17 digits minimum
    DISCORD_ID_MAX = 9999999999999999999  # 19 digits maximum
    DISCORD_USERNAME_MAX = 32
    DISCORD_MESSAGE_MAX = 2000
    DISCORD_EMBED_TITLE_MAX = 256
    DISCORD_EMBED_DESC_MAX = 4096
    DISCORD_EMBED_FIELD_MAX = 1024
    DISCORD_CHANNEL_NAME_MAX = 100
    DISCORD_ROLE_NAME_MAX = 100

    # Database limits
    DB_REASON_MAX = 500
    DB_MESSAGE_MAX = 500
    DB_USERNAME_MAX = 32

    # Rate limits
    MIN_COOLDOWN = 1  # seconds
    MAX_COOLDOWN = 3600  # 1 hour

    @staticmethod
    def validate_discord_id(user_id: Any, field_name: str = "user_id") -> int:
        """
        Validate and sanitize Discord ID.

        Args:
            user_id: The ID to validate
            field_name: Name of field for error messages

        Returns:
            Valid Discord ID as integer

        Raises:
            ValidationError: If ID is invalid
        """
        # DESIGN: Accept string IDs and convert to int for flexibility
        # Discord.py sometimes returns IDs as strings from API responses
        # isdigit() prevents injection attempts with non-numeric strings
        if isinstance(user_id, str):
            if not user_id.isdigit():
                raise ValidationError(f"{field_name} must be numeric, got: {user_id}")
            user_id = int(user_id)

        # DESIGN: Type check after conversion to catch invalid types
        # Prevents passing objects, lists, dicts that could cause crashes
        if not isinstance(user_id, int):
            raise ValidationError(
                f"{field_name} must be an integer, got type: {type(user_id).__name__}"
            )

        # DESIGN: Validate Discord ID range (17-19 digits)
        # Discord snowflake IDs are always within this range
        # Out-of-range IDs indicate data corruption or malicious input
        if user_id < Validators.DISCORD_ID_MIN or user_id > Validators.DISCORD_ID_MAX:
            raise ValidationError(
                f"{field_name} out of valid Discord ID range: {user_id}"
            )

        return user_id

    @staticmethod
    def validate_username(
        username: Optional[str], allow_none: bool = False
    ) -> Optional[str]:
        """
        Validate and sanitize Discord username.

        Args:
            username: Username to validate
            allow_none: Whether None is acceptable

        Returns:
            Sanitized username or None

        Raises:
            ValidationError: If username is invalid
        """
        # DESIGN: Allow None for optional username fields (database defaults)
        # Some operations don't require username if user_id is available
        if username is None:
            if allow_none:
                return None
            raise ValidationError("Username cannot be None")

        if not isinstance(username, str):
            raise ValidationError(
                f"Username must be string, got: {type(username).__name__}"
            )

        # DESIGN: Strip leading/trailing whitespace before validation
        # Users sometimes copy-paste usernames with spaces
        username = username.strip()

        if not username:
            if allow_none:
                return None
            raise ValidationError("Username cannot be empty")

        # DESIGN: Truncate to Discord's 32-character username limit
        # Longer usernames indicate corrupted data or API changes
        # Log warning for monitoring but don't fail operation
        if len(username) > Validators.DISCORD_USERNAME_MAX:
            logger.warning(
                f"Username truncated from {len(username)} to {Validators.DISCORD_USERNAME_MAX} chars"
            )
            username = username[: Validators.DISCORD_USERNAME_MAX]

        # DESIGN: Remove potentially harmful characters for Discord mentions/embeds
        # <> for mention injection, @ for false mentions, #&! for embed formatting
        # Prevents users from crafting malicious usernames that break Discord UI
        username = re.sub(r"[<>@#&!]", "", username)

        # DESIGN: Escape single/double quotes for SQL safety
        # Double the quotes instead of removing (preserves O'Brien as O''Brien)
        # Works with parameterized queries as extra layer of protection
        username = username.replace("'", "''").replace('"', '""')

        return username

    @staticmethod
    def validate_message_content(content: Optional[str], max_length: int = None) -> str:
        """
        Validate and sanitize message content.

        Args:
            content: Message content to validate
            max_length: Maximum allowed length

        Returns:
            Sanitized message content

        Raises:
            ValidationError: If content is invalid
        """
        # DESIGN: Return placeholder for None content instead of failing
        # Empty messages are valid in Discord (attachments-only, embeds)
        # Placeholder prevents database NULL constraints from breaking
        if content is None:
            return "[Empty message]"

        if not isinstance(content, str):
            raise ValidationError(
                f"Message content must be string, got: {type(content).__name__}"
            )

        # DESIGN: Normalize whitespace to prevent storage bloat
        # split() without args splits on any whitespace (spaces, tabs, newlines)
        # ' '.join() collapses multiple spaces into single space
        # Reduces storage size and improves AI context quality
        content = " ".join(content.split())

        # DESIGN: Default to Discord's 2000 character message limit
        # Custom max_length supports database field limits (500 chars)
        # Ensures stored content never exceeds Discord or database constraints
        if max_length is None:
            max_length = Validators.DISCORD_MESSAGE_MAX

        # DESIGN: Truncate with ellipsis suffix for user awareness
        # -3 leaves room for "..." suffix to indicate truncation
        # Log warning for monitoring potential data loss
        if len(content) > max_length:
            logger.warning(
                f"Message truncated from {len(content)} to {max_length} chars"
            )
            content = content[: max_length - 3] + "..."

        # DESIGN: SQL injection protection via quote escaping
        # Double single/double quotes to escape them in SQL strings
        # Works with parameterized queries as defense-in-depth
        content = content.replace("'", "''").replace('"', '""')

        return content if content else "[Empty message]"

    @staticmethod
    def validate_channel_id(channel_id: Any, bot_client: discord.Client = None) -> int:
        """
        Validate Discord channel ID.

        Args:
            channel_id: Channel ID to validate
            bot_client: Optional bot client to verify channel exists

        Returns:
            Valid channel ID

        Raises:
            ValidationError: If channel ID is invalid
        """
        # DESIGN: Reuse validate_discord_id for range and type checking
        # DRY principle - all ID validation logic centralized in one method
        channel_id = Validators.validate_discord_id(channel_id, "channel_id")

        # DESIGN: Optional existence check via bot client
        # Catches typos in config before runtime errors occur
        # get_channel() checks bot's cache (fast, no API call)
        # None if channel deleted, bot removed, or ID incorrect
        if bot_client:
            channel = bot_client.get_channel(channel_id)
            if not channel:
                raise ValidationError(f"Channel {channel_id} not found")

        return channel_id

    @staticmethod
    def validate_role_id(role_id: Any, guild: discord.Guild = None) -> int:
        """
        Validate Discord role ID.

        Args:
            role_id: Role ID to validate
            guild: Optional guild to verify role exists

        Returns:
            Valid role ID

        Raises:
            ValidationError: If role ID is invalid
        """
        # DESIGN: Reuse validate_discord_id for consistency
        # Role IDs follow same snowflake format as user/channel IDs
        role_id = Validators.validate_discord_id(role_id, "role_id")

        # DESIGN: Optional guild-specific existence check
        # Roles are server-specific, must check within correct guild
        # get_role() checks guild's role cache (fast, no API call)
        # Fails if role deleted or bot lost permissions
        if guild:
            role = guild.get_role(role_id)
            if not role:
                raise ValidationError(f"Role {role_id} not found in guild")

        return role_id

    @staticmethod
    def validate_mute_reason(reason: Optional[str]) -> str:
        """
        Validate and sanitize mute reason.

        Args:
            reason: Mute reason to validate

        Returns:
            Sanitized mute reason
        """
        # DESIGN: Return default placeholder instead of failing for missing reasons
        # Moderators often skip reasons when muting (quick actions during spam)
        # Placeholder provides context while allowing operation to succeed
        if not reason or not isinstance(reason, str):
            return "No reason provided"

        reason = reason.strip()

        if not reason:
            return "No reason provided"

        # DESIGN: Truncate to database field limit (500 chars)
        # Database constraint would cause INSERT failure for longer reasons
        # Ellipsis suffix indicates there's more content not shown
        # Log warning for monitoring potential data loss
        if len(reason) > Validators.DB_REASON_MAX:
            logger.warning(
                f"Mute reason truncated from {len(reason)} to {Validators.DB_REASON_MAX} chars"
            )
            reason = reason[: Validators.DB_REASON_MAX - 3] + "..."

        # DESIGN: SQL injection protection via quote escaping
        # Mute reasons come from moderator input (less trusted than config)
        # Defense-in-depth: works with parameterized queries
        reason = reason.replace("'", "''").replace('"', '""')

        return reason

    @staticmethod
    def validate_cooldown(seconds: Any) -> int:
        """
        Validate cooldown duration.

        Args:
            seconds: Cooldown in seconds

        Returns:
            Valid cooldown duration

        Raises:
            ValidationError: If cooldown is invalid
        """
        # DESIGN: Accept string cooldowns from environment variables or config
        # os.getenv() returns strings, need conversion to int for comparisons
        # isdigit() prevents injection attempts like "10; DROP TABLE"
        if isinstance(seconds, str):
            if not seconds.isdigit():
                raise ValidationError(f"Cooldown must be numeric, got: {seconds}")
            seconds = int(seconds)

        if not isinstance(seconds, (int, float)):
            raise ValidationError(
                f"Cooldown must be number, got: {type(seconds).__name__}"
            )

        seconds = int(seconds)

        # DESIGN: Enforce minimum 1s cooldown to prevent rate limit abuse
        # < 1s allows too many operations per second, risks Discord API ban
        # Protects both bot and Discord API from excessive requests
        if seconds < Validators.MIN_COOLDOWN:
            raise ValidationError(
                f"Cooldown too short: {seconds}s (minimum: {Validators.MIN_COOLDOWN}s)"
            )

        # DESIGN: Enforce maximum 1 hour cooldown for user experience
        # Longer cooldowns feel unresponsive to users
        # 3600s (1 hour) is reasonable balance between protection and UX
        if seconds > Validators.MAX_COOLDOWN:
            raise ValidationError(
                f"Cooldown too long: {seconds}s (maximum: {Validators.MAX_COOLDOWN}s)"
            )

        return seconds

    @staticmethod
    def validate_timestamp(timestamp: Any) -> datetime:
        """
        Validate and convert timestamp.

        Args:
            timestamp: Timestamp to validate

        Returns:
            Valid datetime object

        Raises:
            ValidationError: If timestamp is invalid
        """
        # DESIGN: Accept datetime objects directly (already valid)
        # Avoids unnecessary conversion when datetime already provided
        if isinstance(timestamp, datetime):
            return timestamp

        # DESIGN: Accept ISO format strings from JSON or API responses
        # fromisoformat() handles "2025-11-09T14:30:00" format
        # Common format for config files, API responses, database exports
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                raise ValidationError(f"Invalid timestamp format: {timestamp}")

        # DESIGN: Accept Unix timestamps (seconds since 1970-01-01)
        # fromtimestamp() handles both int and float (supports milliseconds)
        # Discord timestamps, database timestamps often in Unix format
        # OSError catches timestamps outside valid range (year 1970-2038 on 32-bit)
        if isinstance(timestamp, (int, float)):
            try:
                return datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                raise ValidationError(f"Invalid timestamp value: {timestamp}")

        raise ValidationError(
            f"Timestamp must be datetime, string, or number, got: {type(timestamp).__name__}"
        )

    @staticmethod
    def validate_list_of_ids(id_list: Any, field_name: str = "id_list") -> List[int]:
        """
        Validate a list of Discord IDs.

        Args:
            id_list: List of IDs to validate
            field_name: Name for error messages

        Returns:
            List of valid Discord IDs

        Raises:
            ValidationError: If any ID is invalid
        """
        # DESIGN: Return empty list for None/empty input (graceful handling)
        # Allows optional ID lists in config without requiring special handling
        if not id_list:
            return []

        # DESIGN: Accept comma-separated strings from environment variables
        # FAMILY_USER_IDS="123,456,789" is more readable than array syntax
        # strip() removes whitespace, if x.strip() filters empty strings
        if isinstance(id_list, str):
            id_list = [x.strip() for x in id_list.split(",") if x.strip()]

        if not isinstance(id_list, (list, tuple)):
            raise ValidationError(
                f"{field_name} must be list or comma-separated string"
            )

        # DESIGN: Skip invalid IDs instead of failing entire list
        # One corrupted ID shouldn't break entire feature
        # Log warnings for monitoring but continue processing valid IDs
        # enumerate() tracks index for better error messages
        validated = []
        for idx, item in enumerate(id_list):
            try:
                validated.append(
                    Validators.validate_discord_id(item, f"{field_name}[{idx}]")
                )
            except ValidationError as e:
                logger.warning(f"Skipping invalid ID in {field_name}: {e}")
                continue

        return validated

    @staticmethod
    def sanitize_sql_value(value: Any) -> str:
        """
        Sanitize value for SQL queries.

        Args:
            value: Value to sanitize

        Returns:
            SQL-safe string
        """
        # DESIGN: Return SQL NULL keyword for None values
        # Proper SQL NULL instead of Python "None" string
        # Prevents "WHERE column = 'None'" bugs in queries
        if value is None:
            return "NULL"

        # DESIGN: Convert all types to string for consistent handling
        # Handles int, float, bool, custom objects uniformly
        value = str(value)

        # DESIGN: Escape quotes to prevent SQL injection
        # Double quotes instead of backslash escaping (SQL standard)
        # Works with both single and double-quoted SQL strings
        value = value.replace("'", "''").replace('"', '""')

        # DESIGN: Remove dangerous SQL keywords as defense-in-depth
        # \b word boundary prevents false positives (DROPBOX → DROPBOX)
        # Case-insensitive matching catches DROP, drop, Drop, etc.
        # Complements parameterized queries, not a replacement
        sql_keywords = [
            "DROP",
            "DELETE",
            "INSERT",
            "UPDATE",
            "ALTER",
            "CREATE",
            "EXEC",
            "EXECUTE",
        ]
        for keyword in sql_keywords:
            value = re.sub(rf"\b{keyword}\b", "", value, flags=re.IGNORECASE)

        return value

    @staticmethod
    def validate_embed(embed: discord.Embed) -> discord.Embed:
        """
        Validate and truncate Discord embed fields.

        Args:
            embed: Embed to validate

        Returns:
            Valid embed within Discord limits

        Raises:
            ValidationError: If embed is invalid
        """
        if not isinstance(embed, discord.Embed):
            raise ValidationError(
                f"Expected Discord Embed, got: {type(embed).__name__}"
            )

        # DESIGN: Validate title length (256 char Discord limit)
        # Truncate with ellipsis instead of failing to preserve functionality
        # Log warning for monitoring potential UX issues
        if embed.title and len(embed.title) > Validators.DISCORD_EMBED_TITLE_MAX:
            logger.warning(f"Embed title truncated from {len(embed.title)} chars")
            embed.title = embed.title[: Validators.DISCORD_EMBED_TITLE_MAX - 3] + "..."

        # DESIGN: Validate description length (4096 char Discord limit)
        # Largest single field in embed, most likely to exceed limit
        # Truncate instead of fail to maintain embed functionality
        if (
            embed.description
            and len(embed.description) > Validators.DISCORD_EMBED_DESC_MAX
        ):
            logger.warning(
                f"Embed description truncated from {len(embed.description)} chars"
            )
            embed.description = (
                embed.description[: Validators.DISCORD_EMBED_DESC_MAX - 3] + "..."
            )

        # DESIGN: Validate all field names and values
        # Field names max 256 chars, values max 1024 chars
        # Iterate through embed.fields list to check each field
        # Modify in-place since fields are mutable EmbedProxy objects
        for field in embed.fields:
            if len(field.name) > 256:
                field.name = field.name[:253] + "..."
            if len(field.value) > Validators.DISCORD_EMBED_FIELD_MAX:
                field.value = (
                    field.value[: Validators.DISCORD_EMBED_FIELD_MAX - 3] + "..."
                )

        # DESIGN: Check total embed size (6000 char Discord limit)
        # Sum of title + description + all field names/values
        # Discord enforces this limit server-side, fail early to prevent API errors
        # or '' handles None values from optional fields
        total_size = len(embed.title or "") + len(embed.description or "")
        for field in embed.fields:
            total_size += len(field.name) + len(field.value)

        if total_size > 6000:
            raise ValidationError(
                f"Embed exceeds 6000 character limit: {total_size} chars"
            )

        return embed


class InputSanitizer:
    """High-level input sanitization wrapper"""

    @staticmethod
    def sanitize_user_input(
        user_id: Any = None,
        username: Any = None,
        message: Any = None,
        channel_id: Any = None,
        reason: Any = None,
    ) -> dict:
        """
        Sanitize common user input fields.

        Args:
            user_id: Discord user ID
            username: Username
            message: Message content
            channel_id: Channel ID
            reason: Mute/action reason

        Returns:
            Dictionary of sanitized values
        """
        # DESIGN: Centralized sanitization for all common input fields
        # Single function handles all validation instead of scattered calls
        # Returns dict with all fields, even if some fail validation
        # Graceful degradation: invalid fields get safe defaults, operation continues
        result: dict[str, Any] = {}

        # DESIGN: Try-except per field for graceful failure handling
        # One invalid field doesn't block others from being sanitized
        # Log warnings for monitoring but don't stop operation
        # Each field gets safe default on failure (None, "Unknown User", etc.)
        try:
            if user_id is not None:
                result["user_id"] = Validators.validate_discord_id(user_id)
        except ValidationError as e:
            logger.warning(f"Invalid user_id: {e}")
            result["user_id"] = None

        try:
            if username is not None:
                result["username"] = Validators.validate_username(
                    username, allow_none=True
                )
        except ValidationError as e:
            logger.warning(f"Invalid username: {e}")
            result["username"] = "Unknown User"

        try:
            if message is not None:
                result["message"] = Validators.validate_message_content(message)
        except ValidationError as e:
            logger.warning(f"Invalid message: {e}")
            result["message"] = "[Invalid message]"

        try:
            if channel_id is not None:
                result["channel_id"] = Validators.validate_channel_id(channel_id)
        except ValidationError as e:
            logger.warning(f"Invalid channel_id: {e}")
            result["channel_id"] = None

        try:
            if reason is not None:
                result["reason"] = Validators.validate_mute_reason(reason)
        except ValidationError as e:
            logger.warning(f"Invalid reason: {e}")
            result["reason"] = "No reason provided"

        return result
