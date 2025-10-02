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
Version: v2.3.0
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
        # Convert to int if string
        if isinstance(user_id, str):
            if not user_id.isdigit():
                raise ValidationError(f"{field_name} must be numeric, got: {user_id}")
            user_id = int(user_id)

        # Check if it's an integer
        if not isinstance(user_id, int):
            raise ValidationError(f"{field_name} must be an integer, got type: {type(user_id).__name__}")

        # Validate Discord ID range
        if user_id < Validators.DISCORD_ID_MIN or user_id > Validators.DISCORD_ID_MAX:
            raise ValidationError(f"{field_name} out of valid Discord ID range: {user_id}")

        return user_id

    @staticmethod
    def validate_username(username: Optional[str], allow_none: bool = False) -> Optional[str]:
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
        if username is None:
            if allow_none:
                return None
            raise ValidationError("Username cannot be None")

        if not isinstance(username, str):
            raise ValidationError(f"Username must be string, got: {type(username).__name__}")

        # Strip whitespace
        username = username.strip()

        if not username:
            if allow_none:
                return None
            raise ValidationError("Username cannot be empty")

        # Truncate to Discord limit
        if len(username) > Validators.DISCORD_USERNAME_MAX:
            logger.warning(f"Username truncated from {len(username)} to {Validators.DISCORD_USERNAME_MAX} chars")
            username = username[:Validators.DISCORD_USERNAME_MAX]

        # Remove potentially harmful characters
        username = re.sub(r'[<>@#&!]', '', username)

        # Prevent SQL injection
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
        if content is None:
            return "[Empty message]"

        if not isinstance(content, str):
            raise ValidationError(f"Message content must be string, got: {type(content).__name__}")

        # Strip excessive whitespace
        content = ' '.join(content.split())

        # Use default Discord limit if not specified
        if max_length is None:
            max_length = Validators.DISCORD_MESSAGE_MAX

        # Truncate if too long
        if len(content) > max_length:
            logger.warning(f"Message truncated from {len(content)} to {max_length} chars")
            content = content[:max_length - 3] + "..."

        # Prevent SQL injection
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
        channel_id = Validators.validate_discord_id(channel_id, "channel_id")

        # Optionally verify channel exists
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
        role_id = Validators.validate_discord_id(role_id, "role_id")

        # Optionally verify role exists
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
        if not reason or not isinstance(reason, str):
            return "No reason provided"

        reason = reason.strip()

        if not reason:
            return "No reason provided"

        # Truncate to database limit
        if len(reason) > Validators.DB_REASON_MAX:
            logger.warning(f"Mute reason truncated from {len(reason)} to {Validators.DB_REASON_MAX} chars")
            reason = reason[:Validators.DB_REASON_MAX - 3] + "..."

        # Prevent SQL injection
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
        if isinstance(seconds, str):
            if not seconds.isdigit():
                raise ValidationError(f"Cooldown must be numeric, got: {seconds}")
            seconds = int(seconds)

        if not isinstance(seconds, (int, float)):
            raise ValidationError(f"Cooldown must be number, got: {type(seconds).__name__}")

        seconds = int(seconds)

        if seconds < Validators.MIN_COOLDOWN:
            raise ValidationError(f"Cooldown too short: {seconds}s (minimum: {Validators.MIN_COOLDOWN}s)")

        if seconds > Validators.MAX_COOLDOWN:
            raise ValidationError(f"Cooldown too long: {seconds}s (maximum: {Validators.MAX_COOLDOWN}s)")

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
        if isinstance(timestamp, datetime):
            return timestamp

        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                raise ValidationError(f"Invalid timestamp format: {timestamp}")

        if isinstance(timestamp, (int, float)):
            try:
                return datetime.fromtimestamp(timestamp)
            except (ValueError, OSError):
                raise ValidationError(f"Invalid timestamp value: {timestamp}")

        raise ValidationError(f"Timestamp must be datetime, string, or number, got: {type(timestamp).__name__}")

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
        if not id_list:
            return []

        if isinstance(id_list, str):
            # Handle comma-separated string
            id_list = [x.strip() for x in id_list.split(',') if x.strip()]

        if not isinstance(id_list, (list, tuple)):
            raise ValidationError(f"{field_name} must be list or comma-separated string")

        validated = []
        for idx, item in enumerate(id_list):
            try:
                validated.append(Validators.validate_discord_id(item, f"{field_name}[{idx}]"))
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
        if value is None:
            return "NULL"

        # Convert to string
        value = str(value)

        # Escape quotes
        value = value.replace("'", "''").replace('"', '""')

        # Remove potential SQL commands
        sql_keywords = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'CREATE', 'EXEC', 'EXECUTE']
        for keyword in sql_keywords:
            value = re.sub(rf'\b{keyword}\b', '', value, flags=re.IGNORECASE)

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
            raise ValidationError(f"Expected Discord Embed, got: {type(embed).__name__}")

        # Validate title
        if embed.title and len(embed.title) > Validators.DISCORD_EMBED_TITLE_MAX:
            logger.warning(f"Embed title truncated from {len(embed.title)} chars")
            embed.title = embed.title[:Validators.DISCORD_EMBED_TITLE_MAX - 3] + "..."

        # Validate description
        if embed.description and len(embed.description) > Validators.DISCORD_EMBED_DESC_MAX:
            logger.warning(f"Embed description truncated from {len(embed.description)} chars")
            embed.description = embed.description[:Validators.DISCORD_EMBED_DESC_MAX - 3] + "..."

        # Validate fields
        for field in embed.fields:
            if len(field.name) > 256:
                field.name = field.name[:253] + "..."
            if len(field.value) > Validators.DISCORD_EMBED_FIELD_MAX:
                field.value = field.value[:Validators.DISCORD_EMBED_FIELD_MAX - 3] + "..."

        # Check total embed size (6000 char limit)
        total_size = len(embed.title or '') + len(embed.description or '')
        for field in embed.fields:
            total_size += len(field.name) + len(field.value)

        if total_size > 6000:
            raise ValidationError(f"Embed exceeds 6000 character limit: {total_size} chars")

        return embed


class InputSanitizer:
    """High-level input sanitization wrapper"""

    @staticmethod
    def sanitize_user_input(
        user_id: Any = None,
        username: Any = None,
        message: Any = None,
        channel_id: Any = None,
        reason: Any = None
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
        result = {}

        try:
            if user_id is not None:
                result['user_id'] = Validators.validate_discord_id(user_id)
        except ValidationError as e:
            logger.warning(f"Invalid user_id: {e}")
            result['user_id'] = None

        try:
            if username is not None:
                result['username'] = Validators.validate_username(username, allow_none=True)
        except ValidationError as e:
            logger.warning(f"Invalid username: {e}")
            result['username'] = "Unknown User"

        try:
            if message is not None:
                result['message'] = Validators.validate_message_content(message)
        except ValidationError as e:
            logger.warning(f"Invalid message: {e}")
            result['message'] = "[Invalid message]"

        try:
            if channel_id is not None:
                result['channel_id'] = Validators.validate_channel_id(channel_id)
        except ValidationError as e:
            logger.warning(f"Invalid channel_id: {e}")
            result['channel_id'] = None

        try:
            if reason is not None:
                result['reason'] = Validators.validate_mute_reason(reason)
        except ValidationError as e:
            logger.warning(f"Invalid reason: {e}")
            result['reason'] = "No reason provided"

        return result