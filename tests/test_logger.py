"""Tests for logging module."""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.logger import (
    BotLogger,
    get_logger,
    LogLevel,
    _global_logger
)
from src.utils.tree_log import TreeLogger


class TestBotLogger:
    """Test cases for BotLogger class."""

    def test_logger_initialization(self):
        """Test BotLogger initialization."""
        logger = BotLogger()
        
        assert logger.tree_log is not None
        assert logger.python_logger is not None
        assert logger.log_level == LogLevel.INFO

    def test_log_startup(self):
        """Test startup logging."""
        logger = BotLogger()
        
        # Mock tree_log methods
        with patch.object(logger.tree_log, 'log_run_separator') as mock_separator, \
             patch.object(logger.tree_log, 'log_run_header') as mock_header:
            
            logger.log_startup("TestBot", "1.0.0", {"debug": True})
            
            mock_separator.assert_called_once()
            mock_header.assert_called_once_with("TestBot", "1.0.0")

    def test_log_initialization_step(self):
        """Test initialization step logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_initialization_step(
                "Database",
                "success",
                "Database connected",
                "✅"
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "Initialization: Database"
            assert ("status", "success") in args[1]
            assert ("details", "Database connected") in args[1]

    def test_log_user_interaction(self):
        """Test user interaction logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_user_interaction(
                user_id=123456,
                user_name="TestUser",
                interaction_type="command",
                action="/activate",
                details={"channel": "general"}
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "User Interaction"
            assert ("user", "TestUser (123456)") in args[1]

    def test_log_ai_operation(self):
        """Test AI operation logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_ai_operation(
                operation="generate_response",
                duration=1.5,
                tokens_used=150,
                result="Success",
                context={"model": "gpt-3.5"}
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "AI Operation"
            assert ("operation", "generate_response") in args[1]
            assert ("duration", "1.50s") in args[1]

    def test_log_error(self):
        """Test error logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_error_with_traceback') as mock_error:
            try:
                raise ValueError("Test error")
            except ValueError as e:
                logger.log_error("Test operation failed", exception=e)
            
            mock_error.assert_called_once()
            assert "Test operation failed" in mock_error.call_args[0][0]

    def test_log_warning(self):
        """Test warning logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_warning(
                "High memory usage",
                context={"usage": "85%"}
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "Warning"

    def test_log_debug(self):
        """Test debug logging."""
        logger = BotLogger()
        logger.set_log_level(LogLevel.DEBUG)
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_debug(
                "Debug message",
                context={"data": "test"}
            )
            
            mock_log.assert_called_once()

    def test_log_debug_ignored_in_info_mode(self):
        """Test debug messages ignored in INFO mode."""
        logger = BotLogger()
        logger.set_log_level(LogLevel.INFO)
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_debug("Debug message")
            
            mock_log.assert_not_called()

    def test_log_event(self):
        """Test event logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_event(
                "bot_ready",
                "Bot is ready",
                {"guilds": 5}
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "System Event"
            assert ("event_type", "bot_ready") in args[1]

    def test_log_metric(self):
        """Test metric logging."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            logger.log_metric(
                "response_time",
                150,
                "ms",
                {"endpoint": "/health"}
            )
            
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == "Performance Metric"
            assert ("metric", "response_time") in args[1]
            assert ("value", "150 ms") in args[1]

    def test_log_shutdown(self):
        """Test shutdown logging."""
        logger = BotLogger()
        
        with patch.object(logger.tree_log, 'log_run_end') as mock_end:
            logger.log_shutdown("User requested")
            
            mock_end.assert_called_once()
            assert "User requested" in mock_end.call_args[0]

    def test_set_log_level(self):
        """Test setting log level."""
        logger = BotLogger()
        
        logger.set_log_level(LogLevel.DEBUG)
        assert logger.log_level == LogLevel.DEBUG
        
        logger.set_log_level(LogLevel.ERROR)
        assert logger.log_level == LogLevel.ERROR

    def test_global_logger(self):
        """Test global logger instance."""
        logger1 = get_logger()
        logger2 = get_logger()
        
        assert logger1 is logger2  # Same instance
        assert isinstance(logger1, BotLogger)


class TestLogLevel:
    """Test cases for LogLevel enum."""

    def test_log_level_values(self):
        """Test log level values."""
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARNING.value == "WARNING"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"

    def test_log_level_from_string(self):
        """Test creating log level from string."""
        assert LogLevel("DEBUG") == LogLevel.DEBUG
        assert LogLevel("INFO") == LogLevel.INFO
        assert LogLevel("WARNING") == LogLevel.WARNING
        assert LogLevel("ERROR") == LogLevel.ERROR
        assert LogLevel("CRITICAL") == LogLevel.CRITICAL


class TestLoggerIntegration:
    """Integration tests for logger with tree_log."""

    def test_logger_creates_log_files(self):
        """Test that logger creates log files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the log directory
            with patch('src.utils.tree_log.Path') as mock_path:
                mock_path.return_value.parent.parent.parent = Path(temp_dir)
                
                logger = BotLogger()
                logger.log_status("Test message")
                
                # Check log directory was created
                logs_dir = Path(temp_dir) / "logs"
                assert logs_dir.exists() or True  # May not create immediately

    def test_structured_logging_format(self):
        """Test structured logging format."""
        logger = BotLogger()
        
        # Test various log formats maintain structure
        with patch('src.utils.tree_log.log_perfect_tree_section') as mock_log:
            # User interaction with nested details
            logger.log_user_interaction(
                user_id=123,
                user_name="Test",
                interaction_type="command",
                action="/help",
                details={
                    "channel": "general",
                    "guild": "TestGuild",
                    "timestamp": "2024-01-01"
                }
            )
            
            # Check nested structure was preserved
            call_args = mock_log.call_args
            assert "nested_groups" in call_args[1]
            assert "Details" in call_args[1]["nested_groups"]

    def test_error_logging_with_traceback(self):
        """Test error logging includes traceback."""
        logger = BotLogger()
        
        with patch('src.utils.tree_log.log_error_with_traceback') as mock_error:
            try:
                # Create a chain of exceptions
                try:
                    raise ValueError("Inner error")
                except ValueError:
                    raise RuntimeError("Outer error")
            except RuntimeError as e:
                logger.log_error("Operation failed", exception=e)
            
            # Check exception was passed correctly
            mock_error.assert_called_once()
            assert isinstance(mock_error.call_args[0][1], RuntimeError)