"""
AzabBot - AI Service
====================

Centralized AI service using OpenAI API for intelligent features.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Dict, List

from openai import AsyncOpenAI

from src.core.logger import logger
from src.core.config import get_config

from .prompts import (
    TICKET_ASSISTANT_SYSTEM,
    TICKET_GREETING_TEMPLATE,
    TICKET_FOLLOWUP_SYSTEM,
    TICKET_FOLLOWUP_TEMPLATE,
    FINAL_RESPONSE_NOTE,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# OpenAI model to use (cost-effective and fast)
AI_MODEL = "gpt-4o-mini"

# Maximum tokens for responses
MAX_TOKENS = 500

# Timeout for API calls (seconds)
API_TIMEOUT = 30.0

# Maximum AI follow-up responses per ticket (not counting initial greeting)
MAX_FOLLOWUP_RESPONSES = 3


# =============================================================================
# Conversation Tracking
# =============================================================================

@dataclass
class TicketConversation:
    """Tracks AI conversation state for a ticket."""

    ticket_id: str
    category: str
    subject: str
    response_count: int = 0  # Number of AI follow-up responses sent
    messages: List[Dict[str, str]] = field(default_factory=list)  # Conversation history

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self.messages.append({"role": "user", "content": content})

    def add_ai_message(self, content: str) -> None:
        """Add an AI response to history."""
        self.messages.append({"role": "assistant", "content": content})
        self.response_count += 1

    def get_history_text(self) -> str:
        """Get conversation history as formatted text."""
        lines = []
        for msg in self.messages:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"**{role}:** {msg['content']}")
        return "\n\n".join(lines)

    def can_respond(self) -> bool:
        """Check if AI can still respond (under limit)."""
        return self.response_count < MAX_FOLLOWUP_RESPONSES


# =============================================================================
# AI Service
# =============================================================================

class AIService:
    """
    Service for AI-powered features using OpenAI API.

    This service provides:
    - Ticket greeting generation with contextual questions
    - Follow-up conversation with context tracking
    - Automatic handoff when staff claims ticket

    Thread Safety:
        OpenAI's AsyncOpenAI client is thread-safe for async operations.
        Conversation tracking uses asyncio.Lock for dict access.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the AI service.

        Args:
            bot: The AzabBot instance.
        """
        self.bot = bot
        self.config = get_config()
        self._client: Optional[AsyncOpenAI] = None
        self._enabled: bool = False

        # Conversation tracking: ticket_id -> TicketConversation
        self._conversations: Dict[str, TicketConversation] = {}
        self._conversations_lock = asyncio.Lock()

        # Initialize client if API key is available
        if self.config.openai_api_key:
            self._client = AsyncOpenAI(
                api_key=self.config.openai_api_key,
                timeout=API_TIMEOUT,
            )
            self._enabled = True
            logger.tree("AI Service Initialized", [
                ("Model", AI_MODEL),
                ("Max Tokens", str(MAX_TOKENS)),
                ("Max Follow-ups", str(MAX_FOLLOWUP_RESPONSES)),
                ("Timeout", f"{API_TIMEOUT}s"),
            ], emoji="🤖")
        else:
            logger.warning("AI Service disabled (no OPENAI_API_KEY configured)")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if AI service is enabled."""
        return self._enabled and self._client is not None

    # =========================================================================
    # Conversation Management
    # =========================================================================

    async def start_conversation(
        self,
        ticket_id: str,
        category: str,
        subject: str,
        initial_greeting: str,
    ) -> None:
        """
        Start tracking a conversation for a ticket.

        Args:
            ticket_id: The ticket ID.
            category: The ticket category.
            subject: The ticket subject.
            initial_greeting: The AI's initial greeting message.
        """
        async with self._conversations_lock:
            conv = TicketConversation(
                ticket_id=ticket_id,
                category=category,
                subject=subject,
            )
            # Add the initial greeting as AI's first message
            conv.messages.append({"role": "assistant", "content": initial_greeting})
            self._conversations[ticket_id] = conv

            logger.tree("AI Conversation Started", [
                ("Ticket ID", ticket_id),
                ("Category", category),
                ("Max Responses", str(MAX_FOLLOWUP_RESPONSES)),
            ], emoji="🤖")

    async def end_conversation(self, ticket_id: str) -> None:
        """
        End and clean up conversation tracking for a ticket.

        Called when ticket is claimed or closed.

        Args:
            ticket_id: The ticket ID.
        """
        async with self._conversations_lock:
            if ticket_id in self._conversations:
                conv = self._conversations.pop(ticket_id)
                logger.tree("AI Conversation Ended", [
                    ("Ticket ID", ticket_id),
                    ("Responses Given", str(conv.response_count)),
                    ("Total Messages", str(len(conv.messages))),
                ], emoji="🤖")

    async def can_respond_to_ticket(self, ticket_id: str) -> bool:
        """
        Check if AI can still respond to a ticket.

        Args:
            ticket_id: The ticket ID.

        Returns:
            True if AI can respond (conversation exists and under limit).
        """
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)
            return conv is not None and conv.can_respond()

    # =========================================================================
    # Ticket Greeting Generation
    # =========================================================================

    async def generate_ticket_greeting(
        self,
        ticket_id: str,
        category: str,
        subject: str,
        description: str,
    ) -> Optional[str]:
        """
        Generate an AI-powered greeting for a new ticket.

        Args:
            ticket_id: The ticket ID (for conversation tracking).
            category: The ticket category (support, partnership, etc.)
            subject: The ticket subject provided by user.
            description: The ticket description provided by user.

        Returns:
            Generated greeting message, or None if generation fails.
        """
        if not self.enabled:
            logger.debug("AI greeting skipped (service disabled)")
            return None

        # Build the user prompt from template
        user_prompt = TICKET_GREETING_TEMPLATE.format(
            category=category.title(),
            subject=subject,
            description=description,
        )

        try:
            response = await self._client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": TICKET_ASSISTANT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=MAX_TOKENS,
                temperature=0.7,
            )

            if response.choices and response.choices[0].message:
                generated = response.choices[0].message.content
                if generated:
                    greeting = generated.strip()

                    # Start conversation tracking
                    await self.start_conversation(
                        ticket_id=ticket_id,
                        category=category,
                        subject=subject,
                        initial_greeting=greeting,
                    )

                    logger.tree("AI Greeting Generated", [
                        ("Ticket ID", ticket_id),
                        ("Category", category),
                        ("Subject", subject[:50]),
                        ("Tokens Used", str(response.usage.total_tokens) if response.usage else "?"),
                    ], emoji="🤖")
                    return greeting

            logger.warning("AI response was empty", [
                ("Ticket ID", ticket_id),
                ("Category", category),
            ])
            return None

        except asyncio.TimeoutError:
            logger.error("AI API timeout", [
                ("Ticket ID", ticket_id),
                ("Timeout", f"{API_TIMEOUT}s"),
            ])
            return None

        except Exception as e:
            logger.error("AI greeting generation failed", [
                ("Ticket ID", ticket_id),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Follow-up Response Generation
    # =========================================================================

    async def generate_followup_response(
        self,
        ticket_id: str,
        user_message: str,
    ) -> Optional[str]:
        """
        Generate an AI follow-up response to a user message.

        Args:
            ticket_id: The ticket ID.
            user_message: The user's latest message.

        Returns:
            Generated response, or None if generation fails or limit reached.
        """
        if not self.enabled:
            return None

        # Skip empty messages (e.g., just attachments)
        if not user_message or not user_message.strip():
            logger.debug(f"Skipping AI response for empty message in ticket {ticket_id}")
            return None

        # Get conversation and check if we can respond
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)
            if not conv:
                logger.debug(f"No AI conversation found for ticket {ticket_id}")
                return None

            if not conv.can_respond():
                logger.tree("AI Response Limit Reached", [
                    ("Ticket ID", ticket_id),
                    ("Responses Given", str(conv.response_count)),
                    ("Max Allowed", str(MAX_FOLLOWUP_RESPONSES)),
                ], emoji="🤖")
                return None

            # Add user message to history
            conv.add_user_message(user_message)

            # Get conversation data for prompt
            category = conv.category
            subject = conv.subject
            history_text = conv.get_history_text()
            response_num = conv.response_count + 1  # What this response will be
            is_final = response_num >= MAX_FOLLOWUP_RESPONSES

        # Build the follow-up prompt with response number context
        final_note = FINAL_RESPONSE_NOTE if is_final else "Ask follow-up questions to gather more information."
        user_prompt = TICKET_FOLLOWUP_TEMPLATE.format(
            category=category.title(),
            subject=subject,
            conversation_history=history_text,
            latest_message=user_message,
            response_num=response_num,
            max_responses=MAX_FOLLOWUP_RESPONSES,
            final_response_note=final_note,
        )

        try:
            response = await self._client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": TICKET_FOLLOWUP_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=MAX_TOKENS,
                temperature=0.7,
            )

            if response.choices and response.choices[0].message:
                generated = response.choices[0].message.content
                if generated:
                    ai_response = generated.strip()

                    # Update conversation with AI response
                    async with self._conversations_lock:
                        if ticket_id in self._conversations:
                            self._conversations[ticket_id].add_ai_message(ai_response)

                    logger.tree("AI Follow-up Generated", [
                        ("Ticket ID", ticket_id),
                        ("Response #", str(response_num)),
                        ("Remaining", str(MAX_FOLLOWUP_RESPONSES - response_num)),
                        ("Tokens Used", str(response.usage.total_tokens) if response.usage else "?"),
                    ], emoji="🤖")
                    return ai_response

            logger.warning("AI follow-up was empty", [
                ("Ticket ID", ticket_id),
            ])
            return None

        except asyncio.TimeoutError:
            logger.error("AI API timeout (follow-up)", [
                ("Ticket ID", ticket_id),
                ("Timeout", f"{API_TIMEOUT}s"),
            ])
            return None

        except Exception as e:
            logger.error("AI follow-up generation failed", [
                ("Ticket ID", ticket_id),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Generic Response (for future features)
    # =========================================================================

    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = MAX_TOKENS,
        temperature: float = 0.7,
    ) -> Optional[str]:
        """
        Generic method for generating AI responses.

        Args:
            system_prompt: The system prompt defining AI behavior.
            user_message: The user's message/query.
            max_tokens: Maximum tokens for response.
            temperature: Creativity level (0.0-2.0).

        Returns:
            Generated response, or None if generation fails.
        """
        if not self.enabled:
            return None

        try:
            response = await self._client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

            if response.choices and response.choices[0].message:
                return response.choices[0].message.content.strip()

            return None

        except Exception as e:
            logger.error("AI response generation failed", [
                ("Error", str(e)[:100]),
            ])
            return None


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AIService"]
