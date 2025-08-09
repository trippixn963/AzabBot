# =============================================================================
# SaydnayaBot - Advanced Configuration Management System
# =============================================================================
# Professional configuration management with validation, type safety, and
# comprehensive error handling. Supports multiple configuration sources,
# environment variable validation, and secure configuration loading.
#
# This module provides a robust configuration system that can handle complex
# configuration scenarios with proper validation and error reporting.
# =============================================================================

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from src.core.exceptions import (
    ConfigurationError,
    InvalidConfigurationError,
    MissingConfigurationError,
)


@dataclass
class ConfigField:
    """
    Configuration field definition with validation and metadata.

    Defines how a configuration field should be processed, validated,
    and used throughout the application.
    """

    name: str
    field_type: Type
    default: Any = None
    required: bool = False
    description: str = ""
    validator: Optional[Callable[[Any], bool]] = None
    transformer: Optional[Callable[[Any], Any]] = None
    sensitive: bool = False  # Whether to hide value in logs
    deprecated: bool = False
    deprecated_message: str = ""


class ConfigurationManager:
    """
    Advanced configuration management system for SaydnayaBot.

    Features:
    - Type-safe configuration loading
    - Multiple configuration sources (.env files, environment variables, JSON)
    - Comprehensive validation with custom validators
    - Secure handling of sensitive configuration
    - Configuration change detection and reloading
    - Deprecation warnings and migration support
    - Detailed error reporting with context

    Configuration Priority (highest to lowest):
    1. Environment variables
    2. .env file in config/ directory
    3. Default values
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the configuration manager.

        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path.cwd()  # Root directory
        self.env_file = self.config_dir / ".env"
        self._config_data: Dict[str, Any] = {}
        self._field_definitions: Dict[str, ConfigField] = {}
        self._loaded = False

        # Define all configuration fields
        self._define_configuration_fields()

    def _define_configuration_fields(self):
        """Define all configuration fields with validation and metadata."""
        fields = [
            # Core Discord Configuration
            ConfigField(
                name="DISCORD_TOKEN",
                field_type=str,
                required=True,
                description="Discord bot token for authentication",
                sensitive=True,
                validator=lambda x: len(x) > 50 and x.startswith(("Bot ", "MTk")),
            ),
            ConfigField(
                name="DEVELOPER_ID",
                field_type=int,
                required=True,
                description="Discord user ID of the bot developer",
                transformer=lambda x: int(x) if isinstance(x, str) else x,
            ),
            # Target Channel Configuration
            ConfigField(
                name="TARGET_CHANNEL_IDS",
                field_type=list,
                default=[],
                description="List of channel IDs to monitor",
                transformer=lambda x: (
                    [int(id_.strip()) for id_ in x.split(",") if id_.strip()]
                    if isinstance(x, str)
                    else x
                ),
            ),
            ConfigField(
                name="PRISON_CHANNEL_IDS",
                field_type=list,
                default=[],
                description="List of prison channel IDs for enhanced harassment",
                transformer=lambda x: (
                    [int(id_.strip()) for id_ in x.split(",") if id_.strip()]
                    if isinstance(x, str)
                    else x
                ),
            ),
            # User Management
            ConfigField(
                name="IGNORE_USER_IDS",
                field_type=list,
                default=[],
                description="List of user IDs to ignore",
                transformer=lambda x: (
                    [id_.strip() for id_ in x.split(",") if id_.strip()]
                    if isinstance(x, str)
                    else x
                ),
            ),
            ConfigField(
                name="REQUIRED_ROLE_ID",
                field_type=int,
                default=None,
                description="Required role ID for bot to respond to users",
            ),
            # AI Configuration
            ConfigField(
                name="OPENAI_API_KEY",
                field_type=str,
                required=True,
                description="OpenAI API key for AI response generation",
                sensitive=True,
                validator=lambda x: x.startswith("sk-") and len(x) > 40,
            ),
            ConfigField(
                name="AI_MODEL",
                field_type=str,
                default="gpt-3.5-turbo",
                description="OpenAI model to use for response generation",
                validator=lambda x: x in ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo"],
            ),
            ConfigField(
                name="MAX_RESPONSE_LENGTH",
                field_type=int,
                default=200,
                description="Maximum length of AI responses in tokens",
                validator=lambda x: 50 <= x <= 1000,
            ),
            # Response Behavior Configuration
            ConfigField(
                name="RESPONSE_PROBABILITY",
                field_type=float,
                default=0.3,
                description="Probability of responding to messages in normal channels",
                validator=lambda x: 0.0 <= x <= 1.0,
            ),
            ConfigField(
                name="PRISON_MODE",
                field_type=bool,
                default=False,
                description="Whether to treat target channels as prison channels",
            ),
            # Rate Limiting Configuration
            ConfigField(
                name="USER_COOLDOWN_MINUTES",
                field_type=int,
                default=5,
                description="Cooldown between responses to the same user (normal channels)",
                validator=lambda x: x >= 0,
            ),
            ConfigField(
                name="CHANNEL_COOLDOWN_MINUTES",
                field_type=int,
                default=2,
                description="Cooldown between responses in the same channel (normal channels)",
                validator=lambda x: x >= 0,
            ),
            ConfigField(
                name="PRISON_USER_COOLDOWN_MINUTES",
                field_type=float,
                default=1.0,
                description="Cooldown between responses to the same user (prison channels)",
                validator=lambda x: x >= 0.0,
            ),
            ConfigField(
                name="PRISON_CHANNEL_COOLDOWN_MINUTES",
                field_type=float,
                default=0.5,
                description="Cooldown between responses in the same channel (prison channels)",
                validator=lambda x: x >= 0.0,
            ),
            ConfigField(
                name="MAX_DAILY_RESPONSES",
                field_type=int,
                default=100,
                description="Maximum responses per day",
                validator=lambda x: x > 0,
            ),
            # Feature Toggles
            # Syrian Context
            ConfigField(
                name="SYRIAN_CONTEXT",
                field_type=bool,
                default=True,
                description="Whether to include Syrian cultural context in responses",
            ),
            # Logging Configuration
            ConfigField(
                name="LOG_LEVEL",
                field_type=str,
                default="INFO",
                description="Logging level",
                validator=lambda x: x.upper()
                in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            ),
            ConfigField(
                name="ENABLE_DEBUG_LOGGING",
                field_type=bool,
                default=False,
                description="Whether to enable debug logging",
            ),
            # Azab Character Configuration
            ConfigField(
                name="AZAB_MODE_ENABLED",
                field_type=bool,
                default=True,
                description="Whether to enable Azab torturer personality in prison channels",
            ),
            ConfigField(
                name="AZAB_PROBABILITY",
                field_type=float,
                default=0.7,
                description="Probability of using Azab personality in prison channels",
                validator=lambda x: 0.0 <= x <= 1.0,
            ),
            # Log Management Configuration
            ConfigField(
                name="LOG_DIR",
                field_type=str,
                default="logs",
                description="Directory for log files",
            ),
            ConfigField(
                name="LOG_RETENTION_DAYS",
                field_type=int,
                default=7,
                description="Days to retain log files before deletion",
                validator=lambda x: x >= 1,
            ),
            ConfigField(
                name="LOG_COMPRESS_AFTER_DAYS",
                field_type=int,
                default=1,
                description="Compress logs older than this many days",
                validator=lambda x: x >= 1,
            ),
            ConfigField(
                name="ERROR_LOG_RETENTION_DAYS",
                field_type=int,
                default=30,
                description="Days to retain error log files",
                validator=lambda x: x >= 1,
            ),
            ConfigField(
                name="MAX_LOG_FILE_SIZE_MB",
                field_type=int,
                default=10,
                description="Maximum log file size in MB before rotation",
                validator=lambda x: x >= 1,
            ),
        ]

        for field in fields:
            self._field_definitions[field.name] = field

    def load_configuration(self) -> Dict[str, Any]:
        """
        Load configuration from all sources with validation.

        Returns:
            Dict containing all loaded configuration values

        Raises:
            ConfigurationError: If configuration loading or validation fails
        """
        try:
            # Load from .env file first
            self._load_env_file()

            # Process all defined fields
            for field_name, field_def in self._field_definitions.items():
                try:
                    value = self._get_field_value(field_def)
                    self._config_data[field_name] = value

                    # Log deprecation warnings
                    if field_def.deprecated:
                        from src.core.logger import log_warning

                        warning_msg = (
                            f"Configuration field '{field_name}' is deprecated"
                        )
                        if field_def.deprecated_message:
                            warning_msg += f": {field_def.deprecated_message}"
                        log_warning(warning_msg)

                except Exception as e:
                    if field_def.required:
                        raise MissingConfigurationError(field_name) from e
                    # Use default value for optional fields
                    self._config_data[field_name] = field_def.default

            self._loaded = True
            return self._config_data.copy()

        except Exception as e:
            if isinstance(e, (ConfigurationError,)):
                raise
            raise ConfigurationError(f"Failed to load configuration: {str(e)}") from e

    def _load_env_file(self):
        """Load environment variables from .env file."""
        if not self.env_file.exists():
            # Create config directory if it doesn't exist
            self.config_dir.mkdir(parents=True, exist_ok=True)
            return

        try:
            with open(self.env_file, "r", encoding="utf-8") as f:
                for _line_num, line in enumerate(f, 1):
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue

                    # Parse key=value pairs
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]

                        # Set environment variable (only if not already set)
                        if key not in os.environ:
                            os.environ[key] = value

        except Exception as e:
            raise ConfigurationError(f"Failed to load .env file: {str(e)}") from e

    def _get_field_value(self, field_def: ConfigField) -> Any:
        """
        Get and validate a configuration field value.

        Args:
            field_def: Field definition

        Returns:
            Processed and validated field value

        Raises:
            InvalidConfigurationError: If validation fails
        """
        # Get raw value from environment
        raw_value = os.environ.get(field_def.name)

        if raw_value is None:
            if field_def.required:
                raise MissingConfigurationError(field_def.name)
            return field_def.default

        try:
            # Convert to appropriate type
            if field_def.field_type is bool:
                processed_value = self._parse_bool(raw_value)
            elif field_def.field_type is int:
                processed_value = int(raw_value)
            elif field_def.field_type is float:
                processed_value = float(raw_value)
            elif field_def.field_type is list:
                processed_value = (
                    raw_value  # Will be transformed if transformer is provided
                )
            else:
                processed_value = raw_value

            # Apply transformer if provided
            if field_def.transformer:
                processed_value = field_def.transformer(processed_value)

            # Validate value
            if field_def.validator and not field_def.validator(processed_value):
                raise InvalidConfigurationError(
                    field_def.name,
                    processed_value,
                    f"validation failed: {field_def.description}",
                )

            return processed_value

        except (ValueError, TypeError) as e:
            raise InvalidConfigurationError(
                field_def.name, raw_value, field_def.field_type.__name__
            ) from e

    def _parse_bool(self, value: str) -> bool:
        """Parse string value to boolean."""
        if isinstance(value, bool):
            return value

        value = value.lower().strip()
        if value in ("true", "1", "yes", "on", "enabled"):
            return True
        elif value in ("false", "0", "no", "off", "disabled"):
            return False
        else:
            raise ValueError(f"Cannot parse '{value}' as boolean")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        if not self._loaded:
            self.load_configuration()

        return self._config_data.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        """Get configuration value as string."""
        value = self.get(key, default)
        return str(value) if value is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get configuration value as integer."""
        value = self.get(key, default)
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get configuration value as float."""
        value = self.get(key, default)
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        return default

    def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Get configuration value as list."""
        value = self.get(key, default or [])
        if isinstance(value, list):
            return value
        return default or []

    def require(self, key: str) -> Any:
        """
        Get a required configuration value.

        Args:
            key: Configuration key

        Returns:
            Configuration value

        Raises:
            MissingConfigurationError: If key is missing
        """
        value = self.get(key)
        if value is None:
            raise MissingConfigurationError(key)
        return value

    def has(self, key: str) -> bool:
        """Check if configuration key exists and has a non-None value."""
        if not self._loaded:
            self.load_configuration()

        return key in self._config_data and self._config_data[key] is not None

    def validate_all(self) -> List[str]:
        """
        Validate all configuration values.

        Returns:
            List of validation errors (empty if all valid)
        """
        errors = []

        if not self._loaded:
            try:
                self.load_configuration()
            except ConfigurationError as e:
                errors.append(str(e))
                return errors

        for field_name, field_def in self._field_definitions.items():
            try:
                value = self._config_data.get(field_name)

                if field_def.required and value is None:
                    errors.append(f"Required field '{field_name}' is missing")
                    continue

                if value is not None and field_def.validator:
                    if not field_def.validator(value):
                        errors.append(
                            f"Field '{field_name}' failed validation: {field_def.description}"
                        )

            except Exception as e:
                errors.append(f"Error validating field '{field_name}': {str(e)}")

        return errors

    def get_configuration_summary(
        self, include_sensitive: bool = False
    ) -> Dict[str, Any]:
        """
        Get a summary of current configuration for logging/debugging.

        Args:
            include_sensitive: Whether to include sensitive values

        Returns:
            Configuration summary dictionary
        """
        if not self._loaded:
            self.load_configuration()

        summary = {}

        for key, value in self._config_data.items():
            field_def = self._field_definitions.get(key)

            if field_def and field_def.sensitive and not include_sensitive:
                summary[key] = "***HIDDEN***" if value else "Not configured"
            elif isinstance(value, list) and len(value) > 5:
                summary[key] = f"[{len(value)} items]"
            else:
                summary[key] = value

        return summary

    def reload_configuration(self) -> bool:
        """
        Reload configuration from all sources.

        Returns:
            True if configuration changed, False otherwise
        """
        old_config = self._config_data.copy()
        self._config_data.clear()
        self._loaded = False

        try:
            self.load_configuration()
            return old_config != self._config_data
        except Exception:
            # Restore old configuration on failure
            self._config_data = old_config
            self._loaded = True
            raise


# =============================================================================
# Global Configuration Instance
# =============================================================================

# Create global configuration manager instance
_global_config = ConfigurationManager()


# Convenience functions for global access
def load_configuration() -> Dict[str, Any]:
    """Load configuration from all sources."""
    return _global_config.load_configuration()


def get_config() -> ConfigurationManager:
    """Get the global configuration manager."""
    return _global_config


def get(key: str, default: Any = None) -> Any:
    """Get configuration value."""
    return _global_config.get(key, default)


def get_str(key: str, default: str = "") -> str:
    """Get configuration value as string."""
    return _global_config.get_str(key, default)


def get_int(key: str, default: int = 0) -> int:
    """Get configuration value as integer."""
    return _global_config.get_int(key, default)


def get_float(key: str, default: float = 0.0) -> float:
    """Get configuration value as float."""
    return _global_config.get_float(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    """Get configuration value as boolean."""
    return _global_config.get_bool(key, default)


def get_list(key: str, default: Optional[List] = None) -> List:
    """Get configuration value as list."""
    return _global_config.get_list(key, default)


def require(key: str) -> Any:
    """Get required configuration value."""
    return _global_config.require(key)
