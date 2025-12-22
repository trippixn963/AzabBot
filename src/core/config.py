"""
Azab Discord Bot - Configuration Module
========================================

Centralized configuration management with environment variable validation.

DESIGN:
    This module provides a single source of truth for all configuration,
    loaded from environment variables at startup. Using a dataclass ensures
    type safety and immutability once loaded.

    Key patterns:
    - Singleton pattern via get_config() ensures one Config instance
    - Validation happens once at load time, not on every access
    - Permission helpers centralize authorization logic

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from dataclasses import dataclass
from typing import Optional, Set
from zoneinfo import ZoneInfo


# =============================================================================
# Timezone Configuration
# =============================================================================

NY_TZ = ZoneInfo("America/New_York")
"""
Eastern timezone for consistent timestamps across all bot operations.

DESIGN:
    Using America/New_York instead of a fixed UTC offset ensures automatic
    handling of EST/EDT transitions. All log timestamps and scheduled
    operations use this timezone.
"""


# =============================================================================
# Configuration Dataclass
# =============================================================================

@dataclass
class Config:
    """
    Bot configuration loaded from environment variables.

    DESIGN:
        Required fields raise ConfigValidationError if missing.
        Optional fields have sensible defaults for development.
        All IDs are integers to prevent string comparison bugs.

    Attributes:
        discord_token: Discord bot authentication token.
        developer_id: User ID of the bot developer.
        logs_channel_id: Channel ID for mod action logs.
        prison_channel_ids: Set of channel IDs where prisoners can be roasted.
        general_channel_id: Main server channel ID.
        muted_role_id: Role ID assigned to muted/timed-out users.
        openai_api_key: OpenAI API key for AI responses.
    """

    # -------------------------------------------------------------------------
    # Required: Discord
    # -------------------------------------------------------------------------

    discord_token: str
    developer_id: int

    # -------------------------------------------------------------------------
    # Required: Channels
    # -------------------------------------------------------------------------

    logs_channel_id: int
    prison_channel_ids: Set[int]
    general_channel_id: int

    # -------------------------------------------------------------------------
    # Required: Roles
    # -------------------------------------------------------------------------

    muted_role_id: int

    # -------------------------------------------------------------------------
    # Required: OpenAI
    # -------------------------------------------------------------------------

    openai_api_key: str

    # -------------------------------------------------------------------------
    # Optional: Channels
    # -------------------------------------------------------------------------

    polls_only_channel_id: Optional[int] = None
    permanent_polls_channel_id: Optional[int] = None
    case_log_forum_id: Optional[int] = None

    # -------------------------------------------------------------------------
    # Optional: Roles
    # -------------------------------------------------------------------------

    management_role_id: Optional[int] = None

    # -------------------------------------------------------------------------
    # Optional: Mod Tracker
    # -------------------------------------------------------------------------

    mod_server_id: Optional[int] = None
    mod_tracker_forum_id: Optional[int] = None
    mod_role_id: Optional[int] = None

    # -------------------------------------------------------------------------
    # Optional: Server Logs
    # -------------------------------------------------------------------------

    server_logs_forum_id: Optional[int] = None
    logging_guild_id: Optional[int] = None  # Only log events from this guild

    # -------------------------------------------------------------------------
    # Optional: AI Settings
    # -------------------------------------------------------------------------

    ai_model: str = "gpt-4o-mini"
    response_probability: int = 70
    max_response_length: int = 150

    # -------------------------------------------------------------------------
    # Optional: Rate Limiting
    # -------------------------------------------------------------------------

    cooldown_seconds: int = 10
    prisoner_cooldown_seconds: int = 30
    prisoner_batch_delay_seconds: float = 5.0

    # -------------------------------------------------------------------------
    # Optional: Limits
    # -------------------------------------------------------------------------

    mute_reason_max_length: int = 100
    message_content_max_length: int = 500
    log_truncate_length: int = 50
    prison_message_scan_limit: int = 500
    polls_cleanup_limit: int = 100
    message_history_size: int = 10

    # -------------------------------------------------------------------------
    # Optional: Display
    # -------------------------------------------------------------------------

    developer_name: str = "حَـــــنَّـــــا"
    server_name: str = "discord.gg/syria"

    # -------------------------------------------------------------------------
    # Optional: Permissions
    # -------------------------------------------------------------------------

    moderator_ids: Set[int] = None

    # -------------------------------------------------------------------------
    # Optional: Webhooks
    # -------------------------------------------------------------------------

    alert_webhook_url: Optional[str] = None
    error_webhook_url: Optional[str] = None


# =============================================================================
# Embed Colors
# =============================================================================

class EmbedColors:
    """
    Standardized embed colors for visual consistency.

    DESIGN:
        Using class constants instead of an enum for simpler access.
        Colors are chosen for accessibility and visual clarity.
    """

    SUCCESS = 0x00FF00   # Green - operation completed
    ERROR = 0xFF0000     # Red - operation failed
    WARNING = 0xFFFF00   # Yellow - caution needed
    INFO = 0x3498DB      # Blue - informational
    PRISON = 0x8B0000    # Dark red - prisoner context
    RELEASE = 0x00FF00   # Green - freedom


# =============================================================================
# Validation
# =============================================================================

class ConfigValidationError(Exception):
    """
    Raised when required configuration is missing or invalid.

    DESIGN:
        Custom exception type allows callers to distinguish config
        errors from other startup failures.
    """

    pass


def _parse_int(value: Optional[str], name: str) -> int:
    """
    Parse string to integer with descriptive error handling.

    Args:
        value: String value from environment variable.
        name: Variable name for error messages.

    Returns:
        Parsed integer value.

    Raises:
        ConfigValidationError: If value is missing or not a valid integer.
    """
    if not value:
        raise ConfigValidationError(f"Missing required: {name}")
    try:
        return int(value)
    except ValueError:
        raise ConfigValidationError(f"Invalid integer for {name}: {value}")


def _parse_int_optional(value: Optional[str]) -> Optional[int]:
    """
    Parse optional string to integer, returning None on failure.

    Args:
        value: String value from environment variable, may be None.

    Returns:
        Parsed integer or None if parsing fails.
    """
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_int_set(value: Optional[str]) -> Set[int]:
    """
    Parse comma-separated string to set of integers.

    Args:
        value: Comma-separated string of integers (e.g., "123,456,789").

    Returns:
        Set of parsed integers, empty set if input is None or empty.
    """
    if not value:
        return set()
    result = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            try:
                result.add(int(part))
            except ValueError:
                pass  # Skip invalid entries silently
    return result


# =============================================================================
# Configuration Loading
# =============================================================================

def load_config() -> Config:
    """
    Load and validate configuration from environment variables.

    DESIGN:
        Validates all required variables upfront before creating the
        Config object. This fail-fast approach prevents partial
        initialization and unclear runtime errors.

    Returns:
        Validated Config object with all settings.

    Raises:
        ConfigValidationError: If any required variable is missing or invalid.
    """
    missing = []

    # -------------------------------------------------------------------------
    # Collect Required Variables
    # -------------------------------------------------------------------------

    discord_token = os.getenv("DISCORD_TOKEN")
    if not discord_token:
        missing.append("DISCORD_TOKEN")

    developer_id_str = os.getenv("DEVELOPER_ID")
    if not developer_id_str:
        missing.append("DEVELOPER_ID")

    logs_channel_id_str = os.getenv("LOGS_CHANNEL_ID")
    if not logs_channel_id_str:
        missing.append("LOGS_CHANNEL_ID")

    prison_channel_ids_str = os.getenv("PRISON_CHANNEL_IDS")
    if not prison_channel_ids_str:
        missing.append("PRISON_CHANNEL_IDS")

    general_channel_id_str = os.getenv("GENERAL_CHANNEL_ID")
    if not general_channel_id_str:
        missing.append("GENERAL_CHANNEL_ID")

    muted_role_id_str = os.getenv("MUTED_ROLE_ID")
    if not muted_role_id_str:
        missing.append("MUTED_ROLE_ID")

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")

    # -------------------------------------------------------------------------
    # Fail Fast on Missing Required
    # -------------------------------------------------------------------------

    if missing:
        raise ConfigValidationError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    # -------------------------------------------------------------------------
    # Parse Required Values
    # -------------------------------------------------------------------------

    developer_id = _parse_int(developer_id_str, "DEVELOPER_ID")
    logs_channel_id = _parse_int(logs_channel_id_str, "LOGS_CHANNEL_ID")
    prison_channel_ids = _parse_int_set(prison_channel_ids_str)
    general_channel_id = _parse_int(general_channel_id_str, "GENERAL_CHANNEL_ID")
    muted_role_id = _parse_int(muted_role_id_str, "MUTED_ROLE_ID")

    # -------------------------------------------------------------------------
    # Parse Optional Values
    # -------------------------------------------------------------------------

    polls_only_channel_id = _parse_int_optional(os.getenv("POLLS_ONLY_CHANNEL_ID"))
    permanent_polls_channel_id = _parse_int_optional(os.getenv("PERMANENT_POLLS_CHANNEL_ID"))
    case_log_forum_id = _parse_int_optional(os.getenv("CASE_LOG_FORUM_ID"))
    management_role_id = _parse_int_optional(os.getenv("MANAGEMENT_ROLE_ID"))
    mod_server_id = _parse_int_optional(os.getenv("MOD_SERVER_ID"))
    mod_tracker_forum_id = _parse_int_optional(os.getenv("MOD_TRACKER_FORUM_ID"))
    mod_role_id = _parse_int_optional(os.getenv("MOD_ROLE_ID"))
    server_logs_forum_id = _parse_int_optional(os.getenv("SERVER_LOGS_FORUM_ID"))
    logging_guild_id = _parse_int_optional(os.getenv("LOGGING_GUILD_ID"))
    moderator_ids = _parse_int_set(os.getenv("MODERATOR_IDS"))

    # -------------------------------------------------------------------------
    # Build Config Object
    # -------------------------------------------------------------------------

    return Config(
        discord_token=discord_token,
        developer_id=developer_id,
        logs_channel_id=logs_channel_id,
        prison_channel_ids=prison_channel_ids,
        general_channel_id=general_channel_id,
        muted_role_id=muted_role_id,
        openai_api_key=openai_api_key,
        polls_only_channel_id=polls_only_channel_id,
        permanent_polls_channel_id=permanent_polls_channel_id,
        case_log_forum_id=case_log_forum_id,
        management_role_id=management_role_id,
        mod_server_id=mod_server_id,
        mod_tracker_forum_id=mod_tracker_forum_id,
        mod_role_id=mod_role_id,
        server_logs_forum_id=server_logs_forum_id,
        logging_guild_id=logging_guild_id,
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini"),
        response_probability=int(os.getenv("RESPONSE_PROBABILITY", "70")),
        max_response_length=int(os.getenv("MAX_RESPONSE_LENGTH", "150")),
        cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "10")),
        prisoner_cooldown_seconds=int(os.getenv("PRISONER_COOLDOWN_SECONDS", "30")),
        prisoner_batch_delay_seconds=float(os.getenv("PRISONER_BATCH_DELAY_SECONDS", "5.0")),
        mute_reason_max_length=int(os.getenv("MUTE_REASON_MAX_LENGTH", "100")),
        message_content_max_length=int(os.getenv("MESSAGE_CONTENT_MAX_LENGTH", "500")),
        log_truncate_length=int(os.getenv("LOG_TRUNCATE_LENGTH", "50")),
        prison_message_scan_limit=int(os.getenv("PRISON_MESSAGE_SCAN_LIMIT", "500")),
        developer_name=os.getenv("DEVELOPER_NAME", "حَـــــنَّـــــا"),
        server_name=os.getenv("SERVER_NAME", "discord.gg/syria"),
        moderator_ids=moderator_ids if moderator_ids else None,
        alert_webhook_url=os.getenv("ALERT_WEBHOOK_URL"),
        error_webhook_url=os.getenv("ERROR_WEBHOOK_URL"),
    )


# =============================================================================
# Global Config Instance
# =============================================================================

_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance, loading if needed.

    DESIGN:
        Singleton pattern ensures config is loaded once and reused.
        Thread-safe for Discord.py's async context since Python's
        GIL protects the assignment.

    Returns:
        The global Config instance.

    Raises:
        ConfigValidationError: On first call if config is invalid.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


# =============================================================================
# Permission Helpers
# =============================================================================

def is_developer(user_id: int) -> bool:
    """
    Check if user is the bot developer.

    Args:
        user_id: Discord user ID to check.

    Returns:
        True if user is the developer.
    """
    return user_id == get_config().developer_id


def is_moderator(user_id: int) -> bool:
    """
    Check if user is a moderator.

    Args:
        user_id: Discord user ID to check.

    Returns:
        True if user is in the moderator list.
    """
    config = get_config()
    if config.moderator_ids:
        return user_id in config.moderator_ids
    return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Core classes
    "Config",
    "ConfigValidationError",
    "EmbedColors",
    # Constants
    "NY_TZ",
    # Functions
    "get_config",
    "load_config",
    # Permission helpers
    "is_developer",
    "is_moderator",
]
