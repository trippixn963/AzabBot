"""
Azab Discord Bot - AI Service Module
=====================================

OpenAI integration for generating contextual AI responses.

DESIGN:
    This service generates personalized roasts for muted users using GPT-4o-mini.
    Prompts are crafted to twist the prisoner's own words against them while
    incorporating context like mute reason, duration, and chat history.

    Key features:
    - Context-aware roasts based on mute reason and duration
    - Avoids repeating recent roasts for the same user
    - Fallback responses when AI is unavailable

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from openai import AsyncOpenAI
import random
import time
from typing import Optional, List

from src.core.logger import logger
from src.core.database import get_db
from src.core.config import get_config
from src.utils.metrics import metrics, increment_counter


# =============================================================================
# AI Service Class
# =============================================================================

class AIService:
    """
    OpenAI integration service for generating Discord bot responses.

    DESIGN:
        Uses async OpenAI client for non-blocking API calls.
        Maintains roast history to avoid repetition.
        Categorizes roasts by mute duration stage.

    Attributes:
        config: Bot configuration.
        enabled: Whether AI service is available.
        client: AsyncOpenAI client instance.
        db: Database manager for roast history.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, api_key: Optional[str]) -> None:
        """
        Initialize the AI service.

        Args:
            api_key: OpenAI API key. If None, service uses fallback responses.
        """
        self.config = get_config()
        self.enabled = bool(api_key)
        self.db = get_db()

        if self.enabled:
            self.client = AsyncOpenAI(api_key=api_key)
            logger.tree("AI Service Initialized", [
                ("Status", "Online"),
                ("Model", self.config.ai_model),
                ("Max Tokens", str(self.config.max_response_length)),
            ], emoji="🤖")
        else:
            self.client = None
            logger.warning("No OpenAI API key - using fallback responses")

    # =========================================================================
    # Response Decision
    # =========================================================================

    def should_respond(self, message: str, mentioned: bool, is_muted: bool) -> bool:
        """
        Determine if the bot should respond to this message.

        DESIGN:
            Simple gate: only respond to muted users.
            Ignores empty messages and extremely long ones.

        Args:
            message: The message content.
            mentioned: Whether the bot was mentioned.
            is_muted: Whether the user is muted.

        Returns:
            True if bot should generate a response.
        """
        if not message or len(message) > 2000:
            return False
        return is_muted

    # =========================================================================
    # Response Generation
    # =========================================================================

    async def generate_response(
        self,
        message: str,
        username: str,
        is_muted: bool,
        mute_reason: Optional[str] = None,
        trigger_message: Optional[str] = None,
        user_id: Optional[int] = None,
        mute_duration_minutes: int = 0,
        message_history: Optional[List[str]] = None,
    ) -> str:
        """
        Generate contextual AI response for muted users.

        DESIGN:
            Builds prompt with full context: mute reason, duration,
            recent messages, and previous roasts to avoid.
            Response includes timing and token stats for debugging.

        Args:
            message: Current message content to respond to.
            username: User's display name.
            is_muted: Whether user is currently muted.
            mute_reason: Why they were muted (if known).
            trigger_message: Original triggering message.
            user_id: User's Discord ID for history lookup.
            mute_duration_minutes: How long they've been muted.
            message_history: Recent messages from this user.

        Returns:
            AI-generated roast with timing footer.
        """
        if not message:
            return ""

        # -------------------------------------------------------------------------
        # Truncate Inputs
        # -------------------------------------------------------------------------

        message = message[:2000]
        username = (username or "Unknown")[:50]
        if mute_reason:
            mute_reason = mute_reason[:100]
        mute_duration_minutes = max(0, int(mute_duration_minutes or 0))

        if not self.enabled:
            return self._fallback(is_muted, mute_reason)

        try:
            # -----------------------------------------------------------------
            # Get User Context
            # -----------------------------------------------------------------

            recent_roasts = []
            session_id = None

            if user_id:
                recent_roasts = await self.db.get_recent_roasts(user_id, limit=3)
                session_id = await self.db.get_current_mute_session_id(user_id)

            # -----------------------------------------------------------------
            # Build Prompt
            # -----------------------------------------------------------------

            if is_muted:
                system = self._build_muted_prompt(
                    username, mute_reason, trigger_message or message,
                    recent_roasts, mute_duration_minutes, message_history
                )
            else:
                system = self._build_dismissive_prompt()

            # -----------------------------------------------------------------
            # Generate Response
            # -----------------------------------------------------------------

            start_time = time.time()
            response = await self.client.chat.completions.create(
                model=self.config.ai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"[{username}]: {message}"},
                ],
                max_tokens=self.config.max_response_length,
                temperature=0.9,
                presence_penalty=0.5,
                frequency_penalty=0.3,
            )

            response_time = round(time.time() - start_time, 2)
            content = response.choices[0].message.content
            usage = response.usage

            # Record metrics
            metrics.record("api.openai", response_time * 1000)  # Convert to ms
            increment_counter("ai.requests")
            increment_counter("ai.tokens", usage.total_tokens)

            logger.tree("AI Response Generated", [
                ("User", username),
                ("Duration", f"{mute_duration_minutes}min"),
                ("Response Time", f"{response_time}s"),
                ("Tokens", str(usage.total_tokens)),
            ], emoji="💬")

            # -----------------------------------------------------------------
            # Save Roast to History
            # -----------------------------------------------------------------

            if is_muted and user_id and session_id:
                category = self._get_roast_category(mute_duration_minutes)
                await self.db.save_roast(user_id, content, category, session_id)

            return f"{content}\n-# {response_time}s | {usage.total_tokens} tokens"

        except Exception as e:
            increment_counter("ai.errors")
            logger.error("AI Response Generation Failed", [
                ("User", username),
                ("Error", str(e)[:100]),
            ])
            return self._fallback(is_muted, mute_reason)

    # =========================================================================
    # Prompt Building
    # =========================================================================

    def _build_muted_prompt(
        self,
        username: str,
        mute_reason: Optional[str],
        trigger_msg: str,
        recent_roasts: List[str],
        duration: int,
        history: Optional[List[str]],
    ) -> str:
        """
        Build prompt for muted users.

        DESIGN:
            Context-aware prompting based on mute duration stage.
            Includes recent roasts to avoid for variety.
            References their mute reason for targeted roasts.

        Args:
            username: Prisoner's display name.
            mute_reason: Why they were muted.
            trigger_msg: Message that triggered this response.
            recent_roasts: Previous roasts to avoid repeating.
            duration: Mute duration in minutes.
            history: Recent messages from this user.

        Returns:
            System prompt for the AI.
        """
        # -------------------------------------------------------------------------
        # Time Context
        # -------------------------------------------------------------------------

        if duration <= 0:
            time_ctx = "just arrived"
        elif duration < 30:
            time_ctx = f"{duration}min in"
        elif duration < 60:
            time_ctx = f"{duration}min, approaching 1hr mark"
        elif duration < 1440:
            time_ctx = f"{duration//60}h {duration%60}m in"
        else:
            time_ctx = f"{duration//1440}d {(duration%1440)//60}h - veteran prisoner"

        # -------------------------------------------------------------------------
        # Recent Roasts to Avoid
        # -------------------------------------------------------------------------

        avoid = ""
        if recent_roasts:
            avoid = f"\nAvoid similar to: {recent_roasts[0][:50]}..."

        # -------------------------------------------------------------------------
        # Conversation Context
        # -------------------------------------------------------------------------

        conv_ctx = ""
        if history and len(history) > 1:
            conv_ctx = f"\nRecent msgs: {' | '.join(history[-3:])}"

        return f"""You are Azab, the savage prison warden of discord.gg/syria. Psychologically destroy muted users.

Target: {username} | Reason: {mute_reason or 'unknown'} | Time: {time_ctx}
Last message: "{trigger_msg}"{avoid}{conv_ctx}

RULES:
- Twist their own words against them
- Reference their mute reason
- Be brutal but PG-13
- Under 100 words
- Never say "as an AI" or similar

Roast them:"""

    def _build_dismissive_prompt(self) -> str:
        """
        Build prompt for non-muted users trying to interact.

        Returns:
            System prompt for dismissive response.
        """
        return """You are Azab, a sarcastic Discord bot. This user isn't muted but wants attention.
Be dismissive and sarcastic. Mock them for wasting your time. Under 30 words."""

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_roast_category(self, duration_minutes: int) -> str:
        """
        Determine roast category based on mute duration.

        DESIGN:
            Categories help track roast progression.
            Longer mutes get more intense roasts.

        Args:
            duration_minutes: How long the user has been muted.

        Returns:
            Category string (welcome/early_stage/mid_stage/late_stage/veteran).
        """
        if duration_minutes <= 0:
            return "welcome"
        elif duration_minutes < 30:
            return "early_stage"
        elif duration_minutes < 120:
            return "mid_stage"
        elif duration_minutes < 1440:
            return "late_stage"
        return "veteran"

    def _fallback(self, is_muted: bool, mute_reason: Optional[str] = None) -> str:
        """
        Generate fallback responses when AI is unavailable.

        DESIGN:
            Simple, pre-written responses for reliability.
            Still incorporates mute reason when available.

        Args:
            is_muted: Whether user is muted.
            mute_reason: Why they were muted.

        Returns:
            Fallback response string.
        """
        if is_muted:
            if mute_reason:
                return random.choice([
                    f"HAHAHA YOU'RE IN JAIL FOR {mute_reason.upper()}!",
                    f"Imagine getting locked up for {mute_reason}",
                    f"Stuck in prison for {mute_reason}? Embarrassing",
                ])
            return random.choice([
                "HAHAHA WELCOME TO PRISON!",
                "Imagine being stuck in jail with me",
                "Stay mad, stay jailed",
            ])
        return ""


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AIService"]
