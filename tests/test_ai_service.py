"""Tests for AI service module."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.ai_service import AIService, ConversationContext
from src.core.exceptions import (
    ServiceError,
    ExternalServiceError,
    InvalidInputError
)


class TestConversationContext:
    """Test cases for ConversationContext class."""

    def test_conversation_context_creation(self):
        """Test ConversationContext initialization."""
        context = ConversationContext(
            prisoner_id=123,
            prisoner_name="TestUser",
            reason="Test reason",
            duration="1 hour",
            personality_traits=["curious", "anxious"]
        )
        
        assert context.prisoner_id == 123
        assert context.prisoner_name == "TestUser"
        assert len(context.personality_traits) == 2
        assert len(context.messages) == 0

    def test_add_message(self):
        """Test adding messages to context."""
        context = ConversationContext(123, "TestUser")
        
        context.add_message("user", "Hello")
        context.add_message("assistant", "Hi there")
        
        assert len(context.messages) == 2
        assert context.messages[0]["role"] == "user"
        assert context.messages[1]["content"] == "Hi there"

    def test_get_context_prompt(self):
        """Test context prompt generation."""
        context = ConversationContext(
            prisoner_id=123,
            prisoner_name="TestUser",
            reason="spamming",
            duration="30 minutes",
            personality_traits=["anxious", "confused"]
        )
        
        prompt = context.get_context_prompt()
        
        assert "TestUser" in prompt
        assert "spamming" in prompt
        assert "30 minutes" in prompt
        assert "anxious" in prompt
        assert "confused" in prompt


class TestAIService:
    """Test cases for AIService class."""

    @pytest.mark.asyncio
    async def test_service_initialization(self):
        """Test AIService initialization."""
        service = AIService()
        
        # Start service
        await service.start()
        assert service.is_healthy()
        
        # Stop service
        await service.stop()

    @pytest.mark.asyncio
    async def test_generate_response_success(self):
        """Test successful response generation."""
        service = AIService()
        
        # Mock OpenAI client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            context = ConversationContext(123, "TestUser")
            response = await service.generate_response("Hello", context)
            
            assert response == "Test response"
            assert service.metrics["total_requests"] == 1
            assert service.metrics["successful_requests"] == 1

    @pytest.mark.asyncio
    async def test_generate_response_with_retry(self):
        """Test response generation with retry logic."""
        service = AIService()
        
        # Mock OpenAI client to fail once then succeed
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Success after retry"))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[Exception("Temporary error"), mock_response]
            )
            
            context = ConversationContext(123, "TestUser")
            response = await service.generate_response("Hello", context)
            
            assert response == "Success after retry"
            assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_response_all_retries_fail(self):
        """Test response generation when all retries fail."""
        service = AIService()
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("Persistent error")
            )
            
            context = ConversationContext(123, "TestUser")
            
            with pytest.raises(ExternalServiceError):
                await service.generate_response("Hello", context)
            
            assert service.metrics["failed_requests"] == 1

    @pytest.mark.asyncio
    async def test_content_filtering(self):
        """Test content filtering in responses."""
        service = AIService()
        
        # Mock response with filtered content
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(
            content="Hello discord.gg/invite and @everyone"
        ))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            context = ConversationContext(123, "TestUser")
            response = await service.generate_response("Hello", context)
            
            assert "discord.gg" not in response
            assert "@everyone" not in response
            assert "[filtered]" in response

    @pytest.mark.asyncio
    async def test_conversation_cache(self):
        """Test conversation caching."""
        service = AIService()
        
        context = ConversationContext(123, "TestUser")
        
        # Add to cache
        service._add_to_cache(123, context)
        
        # Retrieve from cache
        cached = service._get_from_cache(123)
        assert cached is not None
        assert cached.prisoner_id == 123
        
        # Clear cache
        service.clear_conversation_cache(123)
        assert service._get_from_cache(123) is None

    @pytest.mark.asyncio
    async def test_analyze_personality(self):
        """Test personality analysis."""
        service = AIService()
        
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(
            content="anxious, defensive, confused"
        ))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            history = [
                {"role": "user", "content": "Why am I here?"},
                {"role": "assistant", "content": "Tell me about what happened."},
                {"role": "user", "content": "I don't know what you mean!"}
            ]
            
            traits = await service.analyze_personality(history)
            
            assert len(traits) == 3
            assert "anxious" in traits
            assert "defensive" in traits
            assert "confused" in traits

    @pytest.mark.asyncio
    async def test_should_respond_logic(self):
        """Test response probability logic."""
        service = AIService()
        
        # Test always responds to questions
        assert await service.should_respond("Why am I here?", 0.0) is True
        assert await service.should_respond("What did I do?", 0.0) is True
        
        # Test always responds to keywords
        assert await service.should_respond("admin please help", 0.0) is True
        assert await service.should_respond("this is unfair", 0.0) is True
        
        # Test probability-based responses
        with patch('random.random', return_value=0.3):
            assert await service.should_respond("Hello", 0.5) is True
            assert await service.should_respond("Hello", 0.2) is False

    @pytest.mark.asyncio
    async def test_service_health_check(self):
        """Test service health monitoring."""
        service = AIService()
        
        # Initially unhealthy (not started)
        assert not service.is_healthy()
        
        # Start service
        await service.start()
        assert service.is_healthy()
        
        # Simulate failures
        service.metrics["failed_requests"] = 15
        service.metrics["total_requests"] = 20
        assert not service.is_healthy()  # >10% failure rate
        
        # Stop service
        await service.stop()
        assert not service.is_healthy()

    @pytest.mark.asyncio
    async def test_empty_response_handling(self):
        """Test handling of empty AI responses."""
        service = AIService()
        
        # Mock empty response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=""))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            context = ConversationContext(123, "TestUser")
            response = await service.generate_response("Hello", context)
            
            # Should return fallback response
            assert response != ""
            assert len(response) > 0

    @pytest.mark.asyncio
    async def test_cache_expiration(self):
        """Test conversation cache expiration."""
        service = AIService()
        service._cache_duration = 0.1  # 0.1 seconds for testing
        
        context = ConversationContext(123, "TestUser")
        service._add_to_cache(123, context)
        
        # Should be in cache
        assert service._get_from_cache(123) is not None
        
        # Wait for expiration
        await asyncio.sleep(0.2)
        
        # Should be expired
        assert service._get_from_cache(123) is None

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test handling concurrent requests."""
        service = AIService()
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Concurrent response"))]
        
        with patch.object(service, '_openai_client') as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            
            # Create multiple contexts
            contexts = [
                ConversationContext(i, f"User{i}")
                for i in range(5)
            ]
            
            # Make concurrent requests
            tasks = [
                service.generate_response(f"Message {i}", contexts[i])
                for i in range(5)
            ]
            
            responses = await asyncio.gather(*tasks)
            
            assert len(responses) == 5
            assert all(r == "Concurrent response" for r in responses)
            assert service.metrics["total_requests"] == 5