"""
Test module for bot commands functionality.

This module tests the Discord bot command handling, including command registration,
execution, error handling, and response formatting.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from discord.ext import commands
from discord import Embed, Color

from src.bot.commands import (
    setup_commands,
    ping_command,
    help_command,
    status_command,
    stats_command,
    prison_command,
    torture_command,
    release_command,
    info_command,
    admin_command,
)


class TestCommands:
    """Test cases for bot commands."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock()
        bot.add_command = Mock()
        return bot

    @pytest.fixture
    def mock_context(self):
        """Create a mock command context."""
        context = Mock()
        context.send = AsyncMock()
        context.author = Mock()
        context.author.id = 123456
        context.author.name = "TestUser"
        context.guild = Mock()
        context.guild.id = 789012
        context.guild.name = "TestGuild"
        context.channel = Mock()
        context.channel.id = 345678
        context.channel.name = "general"
        return context

    def test_setup_commands(self, mock_bot):
        """Test command setup registration."""
        setup_commands(mock_bot)
        
        # Verify all commands were added
        assert mock_bot.add_command.call_count >= 8  # At least 8 commands

    @pytest.mark.asyncio
    async def test_ping_command(self, mock_context):
        """Test ping command response."""
        await ping_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert "Pong!" in response
        assert "ms" in response

    @pytest.mark.asyncio
    async def test_help_command(self, mock_context):
        """Test help command response."""
        await help_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert isinstance(response, Embed)
        assert "SaydnayaBot Commands" in response.title
        assert "Available commands" in response.description

    @pytest.mark.asyncio
    async def test_status_command(self, mock_context):
        """Test status command response."""
        with patch('src.bot.commands.get_bot_status') as mock_status:
            mock_status.return_value = {
                'status': 'online',
                'uptime': '1h 30m',
                'guilds': 5,
                'users': 100
            }
            
            await status_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert isinstance(response, Embed)
            assert "Bot Status" in response.title

    @pytest.mark.asyncio
    async def test_stats_command(self, mock_context):
        """Test stats command response."""
        with patch('src.bot.commands.get_bot_statistics') as mock_stats:
            mock_stats.return_value = {
                'total_messages': 1000,
                'commands_used': 500,
                'active_users': 50
            }
            
            await stats_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert isinstance(response, Embed)
            assert "Bot Statistics" in response.title

    @pytest.mark.asyncio
    async def test_prison_command_no_args(self, mock_context):
        """Test prison command without arguments."""
        mock_context.message.content = "!prison"
        
        await prison_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert "Usage" in response

    @pytest.mark.asyncio
    async def test_prison_command_with_user(self, mock_context):
        """Test prison command with user mention."""
        mock_context.message.content = "!prison @TestUser"
        mock_context.message.mentions = [Mock(id=999, name="TestUser")]
        
        with patch('src.bot.commands.imprison_user') as mock_imprison:
            mock_imprison.return_value = True
            
            await prison_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "imprisoned" in response.lower()

    @pytest.mark.asyncio
    async def test_torture_command_no_session(self, mock_context):
        """Test torture command without active session."""
        mock_context.message.content = "!torture"
        
        with patch('src.bot.commands.get_active_torture_session') as mock_session:
            mock_session.return_value = None
            
            await torture_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "no active session" in response.lower()

    @pytest.mark.asyncio
    async def test_torture_command_with_session(self, mock_context):
        """Test torture command with active session."""
        mock_context.message.content = "!torture"
        
        with patch('src.bot.commands.get_active_torture_session') as mock_session:
            mock_session.return_value = {
                'prisoner_id': 999,
                'start_time': '2024-01-01 12:00:00',
                'duration': '30m'
            }
            
            with patch('src.bot.commands.execute_torture') as mock_execute:
                mock_execute.return_value = "Torture result"
                
                await torture_command(mock_context)
                
                mock_context.send.assert_called_once()
                response = mock_context.send.call_args[0][0]
                assert "Torture result" in response

    @pytest.mark.asyncio
    async def test_release_command_no_user(self, mock_context):
        """Test release command without user mention."""
        mock_context.message.content = "!release"
        mock_context.message.mentions = []
        
        await release_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert "Usage" in response

    @pytest.mark.asyncio
    async def test_release_command_with_user(self, mock_context):
        """Test release command with user mention."""
        mock_context.message.content = "!release @TestUser"
        mock_context.message.mentions = [Mock(id=999, name="TestUser")]
        
        with patch('src.bot.commands.release_user') as mock_release:
            mock_release.return_value = True
            
            await release_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "released" in response.lower()

    @pytest.mark.asyncio
    async def test_info_command(self, mock_context):
        """Test info command response."""
        await info_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert isinstance(response, Embed)
        assert "SaydnayaBot Information" in response.title

    @pytest.mark.asyncio
    async def test_admin_command_no_permission(self, mock_context):
        """Test admin command without permission."""
        mock_context.author.guild_permissions.administrator = False
        
        await admin_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert "permission" in response.lower()

    @pytest.mark.asyncio
    async def test_admin_command_with_permission(self, mock_context):
        """Test admin command with permission."""
        mock_context.author.guild_permissions.administrator = True
        mock_context.message.content = "!admin status"
        
        with patch('src.bot.commands.get_admin_status') as mock_admin:
            mock_admin.return_value = "Admin status info"
            
            await admin_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "Admin status info" in response

    @pytest.mark.asyncio
    async def test_command_error_handling(self, mock_context):
        """Test command error handling."""
        mock_context.send.side_effect = Exception("Discord API error")
        
        with pytest.raises(Exception):
            await ping_command(mock_context)

    @pytest.mark.asyncio
    async def test_command_with_invalid_user(self, mock_context):
        """Test command with invalid user mention."""
        mock_context.message.content = "!prison @InvalidUser"
        mock_context.message.mentions = []
        
        await prison_command(mock_context)
        
        mock_context.send.assert_called_once()
        response = mock_context.send.call_args[0][0]
        assert "valid user" in response.lower()

    @pytest.mark.asyncio
    async def test_command_rate_limiting(self, mock_context):
        """Test command rate limiting."""
        with patch('src.bot.commands.check_rate_limit') as mock_rate_limit:
            mock_rate_limit.return_value = False
            
            await ping_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "rate limit" in response.lower()

    @pytest.mark.asyncio
    async def test_command_logging(self, mock_context):
        """Test command execution logging."""
        with patch('src.bot.commands.log_command_execution') as mock_log:
            await ping_command(mock_context)
            
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0]
            assert call_args[0] == mock_context.author.id
            assert call_args[1] == "ping"

    @pytest.mark.asyncio
    async def test_command_cooldown(self, mock_context):
        """Test command cooldown functionality."""
        with patch('src.bot.commands.check_cooldown') as mock_cooldown:
            mock_cooldown.return_value = 30.0  # 30 seconds remaining
            
            await ping_command(mock_context)
            
            mock_context.send.assert_called_once()
            response = mock_context.send.call_args[0][0]
            assert "30" in response
            assert "seconds" in response

    @pytest.mark.asyncio
    async def test_command_help_formatting(self, mock_context):
        """Test help command formatting."""
        await help_command(mock_context)
        
        mock_context.send.assert_called_once()
        embed = mock_context.send.call_args[0][0]
        
        assert embed.color == Color.blue()
        assert len(embed.fields) > 0
        
        # Check that each field has a name and value
        for field in embed.fields:
            assert field.name
            assert field.value

    @pytest.mark.asyncio
    async def test_command_permission_check(self, mock_context):
        """Test command permission checking."""
        mock_context.author.guild_permissions.manage_messages = False
        
        with patch('src.bot.commands.require_permission') as mock_permission:
            mock_permission.side_effect = Exception("Permission denied")
            
            with pytest.raises(Exception):
                await admin_command(mock_context)

    @pytest.mark.asyncio
    async def test_command_argument_parsing(self, mock_context):
        """Test command argument parsing."""
        mock_context.message.content = "!prison @User1 @User2"
        mock_context.message.mentions = [
            Mock(id=111, name="User1"),
            Mock(id=222, name="User2")
        ]
        
        with patch('src.bot.commands.imprison_user') as mock_imprison:
            mock_imprison.return_value = True
            
            await prison_command(mock_context)
            
            # Should handle multiple users
            assert mock_imprison.call_count == 2

    @pytest.mark.asyncio
    async def test_command_cleanup(self, mock_context):
        """Test command cleanup functionality."""
        with patch('src.bot.commands.cleanup_command_resources') as mock_cleanup:
            await ping_command(mock_context)
            
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_metrics(self, mock_context):
        """Test command metrics collection."""
        with patch('src.bot.commands.record_command_metric') as mock_metrics:
            await ping_command(mock_context)
            
            mock_metrics.assert_called_once()
            call_args = mock_metrics.call_args[0]
            assert call_args[0] == "ping"
            assert call_args[1] == mock_context.author.id
