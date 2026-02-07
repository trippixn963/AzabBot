"""
AzabBot - AI Service
====================

Centralized AI service using OpenAI API for intelligent features.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
import json
import time
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
    TICKET_SUMMARY_SYSTEM,
    TICKET_SUMMARY_TEMPLATE,
    ATTACHMENT_ACKNOWLEDGMENT,
    FALLBACK_GREETING,
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

# Maximum tokens for summary (shorter)
MAX_SUMMARY_TOKENS = 200

# Timeout for API calls (seconds)
API_TIMEOUT = 30.0

# Maximum AI follow-up responses per ticket (not counting initial greeting)
MAX_FOLLOWUP_RESPONSES = 3

# Cooldown between AI responses to same ticket (seconds)
AI_RESPONSE_COOLDOWN = 5.0


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
    last_response_time: float = 0.0  # Timestamp of last AI response
    messages: List[Dict[str, str]] = field(default_factory=list)  # Conversation history

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self.messages.append({"role": "user", "content": content})

    def add_ai_message(self, content: str) -> None:
        """Add an AI response to history."""
        self.messages.append({"role": "assistant", "content": content})
        self.response_count += 1
        self.last_response_time = time.time()

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

    def is_on_cooldown(self) -> bool:
        """Check if AI is on response cooldown."""
        return (time.time() - self.last_response_time) < AI_RESPONSE_COOLDOWN

    def to_dict(self) -> dict:
        """Serialize conversation for database storage."""
        return {
            "ticket_id": self.ticket_id,
            "category": self.category,
            "subject": self.subject,
            "response_count": self.response_count,
            "last_response_time": self.last_response_time,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TicketConversation":
        """Deserialize conversation from database."""
        conv = cls(
            ticket_id=data["ticket_id"],
            category=data["category"],
            subject=data["subject"],
            response_count=data.get("response_count", 0),
            last_response_time=data.get("last_response_time", 0.0),
        )
        conv.messages = data.get("messages", [])
        return conv


# =============================================================================
# AI Service
# =============================================================================

class AIService:
    """
    Service for AI-powered features using OpenAI API.

    This service provides:
    - Ticket greeting generation with contextual questions
    - Follow-up conversation with context tracking
    - Summary generation for staff when claiming
    - Attachment acknowledgment
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
                ("Response Cooldown", f"{AI_RESPONSE_COOLDOWN}s"),
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

            # Persist to database
            self._save_conversation(ticket_id, conv)

            logger.tree("AI Conversation Started", [
                ("Ticket ID", ticket_id),
                ("Category", category),
                ("Max Responses", str(MAX_FOLLOWUP_RESPONSES)),
            ], emoji="🤖")

    async def end_conversation(self, ticket_id: str) -> Optional[TicketConversation]:
        """
        End and clean up conversation tracking for a ticket.

        Called when ticket is claimed or closed.

        Args:
            ticket_id: The ticket ID.

        Returns:
            The ended conversation (for summary generation), or None.
        """
        async with self._conversations_lock:
            conv = self._conversations.pop(ticket_id, None)
            if conv:
                # Clear from database
                self._delete_conversation(ticket_id)

                logger.tree("AI Conversation Ended", [
                    ("Ticket ID", ticket_id),
                    ("Responses Given", str(conv.response_count)),
                    ("Total Messages", str(len(conv.messages))),
                ], emoji="🤖")
            return conv

    async def get_conversation(self, ticket_id: str) -> Optional[TicketConversation]:
        """Get conversation for a ticket (from memory or database)."""
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)
            if conv:
                return conv

            # Try to load from database
            conv = self._load_conversation(ticket_id)
            if conv:
                self._conversations[ticket_id] = conv
            return conv

    async def can_respond_to_ticket(self, ticket_id: str) -> bool:
        """
        Check if AI can still respond to a ticket.

        Args:
            ticket_id: The ticket ID.

        Returns:
            True if AI can respond (conversation exists, under limit, not on cooldown).
        """
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)
            if not conv:
                # Try to load from database
                conv = self._load_conversation(ticket_id)
                if conv:
                    self._conversations[ticket_id] = conv

            if not conv:
                return False

            # Check response limit
            if not conv.can_respond():
                return False

            # Check cooldown
            if conv.is_on_cooldown():
                logger.tree("AI Response Skipped (Cooldown)", [
                    ("Ticket ID", ticket_id),
                    ("Cooldown", f"{AI_RESPONSE_COOLDOWN}s"),
                ], emoji="🤖")
                return False

            return True

    # =========================================================================
    # Database Persistence
    # =========================================================================

    def _save_conversation(self, ticket_id: str, conv: TicketConversation) -> None:
        """Save conversation to database."""
        try:
            if hasattr(self.bot, "ticket_service") and self.bot.ticket_service:
                data = json.dumps(conv.to_dict())
                self.bot.ticket_service.db.save_ai_conversation(ticket_id, data)
        except Exception as e:
            logger.warning("Failed to Save AI Conversation", [("Error", str(e)[:50])])

    def _load_conversation(self, ticket_id: str) -> Optional[TicketConversation]:
        """Load conversation from database."""
        try:
            if hasattr(self.bot, "ticket_service") and self.bot.ticket_service:
                data = self.bot.ticket_service.db.get_ai_conversation(ticket_id)
                if data:
                    conv = TicketConversation.from_dict(json.loads(data))
                    logger.tree("AI Conversation Restored", [
                        ("Ticket ID", ticket_id),
                        ("Messages", str(len(conv.messages))),
                        ("Responses Given", str(conv.response_count)),
                    ], emoji="🤖")
                    return conv
        except Exception as e:
            logger.warning("Failed to Load AI Conversation", [("Error", str(e)[:50])])
        return None

    def _delete_conversation(self, ticket_id: str) -> None:
        """Delete conversation from database."""
        try:
            if hasattr(self.bot, "ticket_service") and self.bot.ticket_service:
                self.bot.ticket_service.db.delete_ai_conversation(ticket_id)
        except Exception as e:
            logger.warning("Failed to Delete AI Conversation", [("Error", str(e)[:50])])

    def _update_conversation(self, ticket_id: str, conv: TicketConversation) -> None:
        """Update conversation in database."""
        self._save_conversation(ticket_id, conv)

    # =========================================================================
    # Ticket Greeting Generation
    # =========================================================================

    async def generate_ticket_greeting(
        self,
        ticket_id: str,
        category: str,
        subject: str,
        description: str,
        case_id: Optional[str] = None,
        case_reason: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate an AI-powered greeting for a new ticket.

        Args:
            ticket_id: The ticket ID (for conversation tracking).
            category: The ticket category (support, partnership, etc.)
            subject: The ticket subject provided by user.
            description: The ticket description provided by user.
            case_id: Optional case ID (for appeal tickets).
            case_reason: Optional mute reason (for appeal tickets).

        Returns:
            Generated greeting message, or fallback if generation fails.
        """
        if not self.enabled:
            logger.debug("AI greeting skipped (service disabled)")
            return None

        # Build case context for appeal tickets
        case_context = ""
        if category == "appeal" and case_id and case_reason:
            case_context = f"\n**Case Info:** Case `{case_id}` - Mute reason: \"{case_reason}\"\nIMPORTANT: You already know the mute reason above. Do NOT ask the user what they were muted for."

        # Build the user prompt from template
        user_prompt = TICKET_GREETING_TEMPLATE.format(
            category=category.title(),
            subject=subject,
            description=description,
            case_context=case_context,
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

            # Fallback on empty response
            logger.tree("AI Fallback Greeting Used", [
                ("Ticket ID", ticket_id),
                ("Reason", "Empty AI response"),
                ("Category", category),
            ], emoji="🤖")
            return FALLBACK_GREETING

        except asyncio.TimeoutError:
            logger.tree("AI Fallback Greeting Used", [
                ("Ticket ID", ticket_id),
                ("Reason", "API timeout"),
                ("Timeout", f"{API_TIMEOUT}s"),
            ], emoji="🤖")
            return FALLBACK_GREETING

        except Exception as e:
            logger.tree("AI Fallback Greeting Used", [
                ("Ticket ID", ticket_id),
                ("Reason", "Generation failed"),
                ("Error", str(e)[:50]),
            ], emoji="🤖")
            return FALLBACK_GREETING

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
            logger.debug("Skipping AI Response for Empty Message", [("Ticket", ticket_id)])
            return None

        # Get conversation and check if we can respond
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)
            if not conv:
                # Try loading from database
                conv = self._load_conversation(ticket_id)
                if conv:
                    self._conversations[ticket_id] = conv

            if not conv:
                logger.debug("No AI Conversation Found", [("Ticket", ticket_id)])
                return None

            if not conv.can_respond():
                logger.tree("AI Response Limit Reached", [
                    ("Ticket ID", ticket_id),
                    ("Responses Given", str(conv.response_count)),
                    ("Max Allowed", str(MAX_FOLLOWUP_RESPONSES)),
                ], emoji="🤖")
                return None

            if conv.is_on_cooldown():
                logger.debug("AI on Cooldown", [("Ticket", ticket_id)])
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
                            # Persist update
                            self._update_conversation(ticket_id, self._conversations[ticket_id])

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
    # Attachment Acknowledgment
    # =========================================================================

    def get_attachment_acknowledgment(self, attachment_count: int) -> str:
        """
        Get a message acknowledging user attachments.

        Args:
            attachment_count: Number of attachments in the message.

        Returns:
            Acknowledgment message.
        """
        file_text = "it" if attachment_count == 1 else "them"
        return ATTACHMENT_ACKNOWLEDGMENT.format(
            file_count=attachment_count,
            file_text=file_text,
        )

    # =========================================================================
    # Summary Generation (for staff)
    # =========================================================================

    async def generate_ticket_summary(self, ticket_id: str) -> Optional[str]:
        """
        Generate a summary of the AI conversation for staff.

        Called when staff claims a ticket.

        Args:
            ticket_id: The ticket ID.

        Returns:
            Summary of the conversation, or None if not available.
        """
        if not self.enabled:
            return None

        # Get conversation (don't pop it yet, let end_conversation handle that)
        async with self._conversations_lock:
            conv = self._conversations.get(ticket_id)

        if not conv or len(conv.messages) < 2:
            # No meaningful conversation to summarize
            return None

        # Build summary prompt
        user_prompt = TICKET_SUMMARY_TEMPLATE.format(
            category=conv.category.title(),
            subject=conv.subject,
            conversation_history=conv.get_history_text(),
        )

        try:
            response = await self._client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": TICKET_SUMMARY_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=MAX_SUMMARY_TOKENS,
                temperature=0.3,  # Lower temperature for factual summary
            )

            if response.choices and response.choices[0].message:
                generated = response.choices[0].message.content
                if generated:
                    summary = generated.strip()
                    logger.tree("AI Summary Generated", [
                        ("Ticket ID", ticket_id),
                        ("Messages Summarized", str(len(conv.messages))),
                        ("Tokens Used", str(response.usage.total_tokens) if response.usage else "?"),
                    ], emoji="🤖")
                    return summary

            return None

        except Exception as e:
            logger.error("AI summary generation failed", [
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
