"""Tests for configuration module."""

import os
from unittest.mock import patch

import pytest

from src.config.config import BotConfig, ConfigField, _global_config, get_config


class TestConfigField:
    """Test cases for ConfigField class."""

    def test_field_creation(self):
        """Test ConfigField creation with various options."""
        field = ConfigField(
            name="test_field",
            env_var="TEST_FIELD",
            default="default_value",
            description="Test field",
            field_type=str,
            required=False,
            validator=lambda x: x != "invalid",
            transformer=lambda x: x.upper(),
            sensitive=False,
            deprecated=False,
            deprecated_message=""
        )
        
        assert field.name == "test_field"
        assert field.env_var == "TEST_FIELD"
        assert field.default == "default_value"
        assert field.field_type == str
        assert field.validator("valid") is True
        assert field.validator("invalid") is False
        assert field.transformer("test") == "TEST"

    def test_field_validation(self):
        """Test field validation logic."""
        def validate_positive(x):
            return int(x) > 0
        
        field = ConfigField(
            name="positive_number",
            env_var="POSITIVE_NUM",
            field_type=int,
            validator=validate_positive
        )
        
        assert field.validator("5") is True
        assert field.validator("-5") is False
        assert field.validator("0") is False


class TestBotConfig:
    """Test cases for BotConfig class."""

    def test_config_initialization(self):
        """Test BotConfig initialization."""
        config = BotConfig()
        assert isinstance(config._config, dict)
        assert len(config._fields) > 0  # Should have default fields defined

    @patch.dict(os.environ, {"DISCORD_TOKEN": "test_token", "DEVELOPER_ID": "123456"})
    def test_load_config_from_env(self):
        """Test loading configuration from environment variables."""
        config = BotConfig()
        config.load()
        
        assert config.get("discord_token") == "test_token"
        assert config.get("developer_id") == 123456  # Should be transformed to int

    def test_config_validation_missing_required(self):
        """Test validation fails when required fields are missing."""
        config = BotConfig()
        with pytest.raises(ValueError, match="DISCORD_TOKEN"):
            config.validate()

    @patch.dict(os.environ, {
        "DISCORD_TOKEN": "test_token",
        "DEVELOPER_ID": "123456",
        "OPENAI_API_KEY": "test_key"
    })
    def test_config_validation_success(self):
        """Test successful validation with all required fields."""
        config = BotConfig()
        config.load()
        config.validate()  # Should not raise

    def test_config_get_with_default(self):
        """Test getting config value with default."""
        config = BotConfig()
        assert config.get("non_existent", "default") == "default"

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"})
    def test_config_log_level_validation(self):
        """Test log level validation."""
        config = BotConfig()
        config.load()
        assert config.get("log_level") == "DEBUG"

    @patch.dict(os.environ, {"LOG_LEVEL": "INVALID"})
    def test_config_invalid_log_level(self):
        """Test invalid log level handling."""
        config = BotConfig()
        with pytest.raises(ValueError, match="Invalid log level"):
            config.load()

    @patch.dict(os.environ, {"RESPONSE_PROBABILITY": "0.7"})
    def test_config_float_parsing(self):
        """Test float value parsing."""
        config = BotConfig()
        config.load()
        assert config.get("response_probability") == 0.7
        assert isinstance(config.get("response_probability"), float)

    @patch.dict(os.environ, {"PRISON_MODE": "true"})
    def test_config_bool_parsing(self):
        """Test boolean value parsing."""
        config = BotConfig()
        config.load()
        assert config.get("prison_mode") is True

    @patch.dict(os.environ, {"PRISON_CHANNEL_IDS": "123,456,789"})
    def test_config_list_parsing(self):
        """Test list value parsing."""
        config = BotConfig()
        config.load()
        channels = config.get("prison_channel_ids")
        assert channels == ["123", "456", "789"]
        assert len(channels) == 3

    def test_config_summary_excludes_sensitive(self):
        """Test that config summary excludes sensitive fields."""
        config = BotConfig()
        config._config["discord_token"] = "secret_token"
        config._config["developer_id"] = 123456
        
        summary = config.get_summary()
        assert "discord_token" not in summary
        assert "developer_id" in summary

    def test_global_config_instance(self):
        """Test global config instance creation."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2  # Should be same instance


class TestConfigFieldTypes:
    """Test various configuration field types."""

    @patch.dict(os.environ, {"DEVELOPER_ID": "not_a_number"})
    def test_invalid_int_field(self):
        """Test invalid integer field handling."""
        config = BotConfig()
        with pytest.raises(ValueError, match="must be an integer"):
            config.load()

    @patch.dict(os.environ, {"RESPONSE_PROBABILITY": "not_a_float"})
    def test_invalid_float_field(self):
        """Test invalid float field handling."""
        config = BotConfig()
        with pytest.raises(ValueError, match="must be a float"):
            config.load()

    @patch.dict(os.environ, {"RESPONSE_PROBABILITY": "1.5"})
    def test_probability_validation(self):
        """Test probability validation (0.0 to 1.0)."""
        config = BotConfig()
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            config.load()

    @patch.dict(os.environ, {"MAX_CACHE_SIZE": "-100"})
    def test_negative_cache_size(self):
        """Test negative cache size validation."""
        config = BotConfig()
        with pytest.raises(ValueError, match="must be positive"):
            config.load()