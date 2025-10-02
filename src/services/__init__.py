"""
Azab Discord Bot - Services Package
==================================

External service integrations for the Azab Discord bot.
This package contains integrations with third-party services
like AI providers and other external APIs.

Services:
- AIService: OpenAI GPT-3.5-turbo integration for AI-powered responses
- system_knowledge: Bot capability information for AI self-awareness

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

from .ai_service import AIService

__all__ = ['AIService']