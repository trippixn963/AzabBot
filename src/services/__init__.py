"""
Azab Discord Bot - Services Package
==================================

External service integrations for the Azab Discord bot.
This package contains integrations with third-party services
like AI providers and other external APIs.

Services:
- ai_service.py: OpenAI integration for AI-powered responses

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

from .ai_service import AIService

__all__ = ['AIService']