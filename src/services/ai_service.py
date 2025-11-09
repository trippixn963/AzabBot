"""
Azab Discord Bot - AI Service Module
===================================

OpenAI integration for generating contextual AI responses to Discord messages.
Provides intelligent ragebaiting responses for muted users and conversational
responses for family members.

Features:
- OpenAI GPT-3.5-turbo integration with usage tracking
- Contextual response generation based on user status and history
- Special ragebaiting responses for muted users
- Intelligent conversations with family members (dad, uncle, brother)
- Database query integration for real-time statistics
- Conversation memory (last 10 messages)
- Dynamic roasting based on mute duration and repeat offenses
- Fallback responses when AI is unavailable
- Async API calls for non-blocking operation
- Input validation and sanitization

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import openai
import asyncio
import random
import os
import json
import time
from typing import Optional, Dict, Any, List

from src.core.logger import logger
from src.core.database import Database
from src.utils.error_handler import ErrorHandler
from src.utils.validators import Validators, ValidationError
from src.utils.ai_monitor import ai_monitor
from src.services.system_knowledge import get_system_knowledge, get_feature_explanation


class AIService:
    """
    OpenAI integration service for generating Discord bot responses.
    
    Handles AI-powered response generation with different behaviors:
    - Ragebaiting responses for muted/timed out users
    - Sarcastic responses for regular users
    - Fallback responses when AI service is unavailable
    
    Uses OpenAI's GPT-3.5-turbo model for contextual and creative responses.
    """
    
    def __init__(self, api_key: Optional[str]) -> None:
        """
        Initialize the AI service with OpenAI API key.

        Args:
            api_key (Optional[str]): OpenAI API key for authentication
        """
        # DESIGN: enabled flag allows graceful degradation to fallback responses
        # Bot can still function without AI, just with pre-written roasts
        self.enabled: bool = bool(api_key)

        # DESIGN: Single database instance shared across all AI operations
        # SQLite handles concurrent access with locking, no need for pooling
        self.db: Database = Database()

        # DESIGN: Conversation history for developer/family responses
        # Maintains context across multiple messages for natural dialogue
        self.conversation_history: List[Dict[str, str]] = []

        if self.enabled:
            openai.api_key = api_key
            logger.success("AI Service Ready")
        else:
            logger.error("No OpenAI API key - using fallback responses")
    
    def should_respond(self, message: str, mentioned: bool, is_muted: bool) -> bool:
        """
        Determine if the bot should respond to a message.

        Response criteria:
        - ONLY respond to muted users (with muted role)

        Args:
            message (str): The Discord message content
            mentioned (bool): Whether the bot was mentioned
            is_muted (bool): Whether the user is muted/timed out

        Returns:
            bool: True if bot should respond, False otherwise
        """
        # Validate message content
        try:
            message = Validators.validate_message_content(message)
        except ValidationError:
            return False

        return is_muted
    
    async def generate_response(self, message: str, username: str, is_muted: bool, mute_reason: str = None, trigger_message: str = None, user_id: int = None, mute_duration_minutes: int = 0, message_history: List[str] = None) -> str:
        """
        Generate contextual AI response based on user status and message.

        Creates different response styles:
        - Ragebaiting responses for muted users (savage, mocking)
        - Sarcastic responses for regular users (witty, dismissive)
        - Fallback responses when AI is unavailable

        Args:
            message (str): The original Discord message
            username (str): The Discord username
            is_muted (bool): Whether the user is muted/timed out
            mute_reason (str, optional): The reason the user was muted

        Returns:
            str: Generated AI response or fallback message
        """
        # Validate and sanitize inputs
        try:
            message = Validators.validate_message_content(message, 2000)
            username = Validators.validate_username(username) or "Unknown User"
            if mute_reason:
                mute_reason = Validators.validate_mute_reason(mute_reason)
            if trigger_message:
                trigger_message = Validators.validate_message_content(trigger_message, 500)
            if user_id:
                user_id = Validators.validate_discord_id(user_id)
            mute_duration_minutes = max(0, int(mute_duration_minutes) if mute_duration_minutes else 0)
        except ValidationError as e:
            logger.warning(f"Validation error in generate_response: {e}")
            return "I can't process that right now."
        if not self.enabled:
            # Use fallback responses when AI is not configured
            return self._fallback(is_muted, mute_reason)
        
        try:
            # === STEP 1: Gather User Context for Personalization ===
            # DESIGN: Track user profiles to create personalized roasts
            # Instead of generic responses, AI can reference their past behavior
            # This makes roasts feel more targeted and devastating
            user_profile: Optional[Dict[str, Any]] = None
            recent_roasts: List[str] = []
            session_id: Optional[int] = None

            if user_id:
                # Fetch user behavioral profile (personality type, favorite words, etc.)
                user_profile = await self.db.get_user_profile(user_id)

                # DESIGN: Get last 3 roasts to prevent repetitive responses
                # AI analyzes these and generates something fresh each time
                recent_roasts = await self.db.get_recent_roasts(user_id, limit=3)

                # Get current mute session ID for linking roasts to specific incidents
                session_id = await self.db.get_current_mute_session_id(user_id)

                # DESIGN: Update profile with every message for personality learning
                # Over time, AI learns their speech patterns and can mock them better
                await self.db.update_user_profile(user_id, message)

            # === STEP 2: Build AI Prompt Based on User Status ===
            # Create different system prompts for muted vs non-muted users
            if is_muted:
                # User is muted - build comprehensive roasting prompt with all context
                
                # Determine which message triggered their mute (if available)
                # This helps AI reference the exact offense that got them muted
                trigger_msg = trigger_message if trigger_message else message

                # === Build Memory Context Section ===
                # DESIGN: Personalization creates psychological impact
                # Generic roasts don't hurt - targeted roasts about their personality do
                memory_context: str = ""
                if user_profile:
                    # DESIGN: AI targets personality traits for maximum psychological damage
                    # "apologetic" types get roasted for constant begging
                    # "aggressive" types get mocked for powerlessness
                    # "victim_complex" users get roasted for playing victim
                    memory_context = (
                        f"\nUSER PROFILE (use this to personalize roasts):\n"
                        f"- Personality type: {user_profile.get('personality_type', 'unknown')}\n"
                        f"- Total roasts received: {user_profile.get('total_roasts_received', 0)}\n"
                        f"- Most used words: {user_profile.get('most_used_words', 'none')}\n"
                    )
                    # DESIGN: Callback humor creates devastating "remember when you said" moments
                    # Nothing hurts more than your own words thrown back at you
                    if user_profile.get('callback_references'):
                        old_quotes: List[str] = user_profile['callback_references'].split('|||')[-2:]
                        if old_quotes:
                            memory_context += f"- Things they've said before: {', '.join([f'"{q}"' for q in old_quotes])}\n"

                # === Add Recent Roasts to Prevent Repetition ===
                # DESIGN: Variety prevents users from tuning out repetitive roasts
                # Fresh responses keep prisoners engaged and suffering
                if recent_roasts:
                    memory_context += f"\nRECENT ROASTS (avoid repeating these):\n"
                    for roast in recent_roasts:
                        memory_context += f"- {roast[:100]}...\n"

                # === Add Time-Based Context for Dynamic Roasting ===
                # DESIGN: Roasting style evolves with mute duration
                # 5 min: "Fresh meat, welcome to prison"
                # 2 hours: "Reality setting in? Good."
                # 1 day+: "Veteran prisoner, dedication roasts"
                time_context: str = self._get_time_based_context(mute_duration_minutes)

                # === Add Conversation History for Context ===
                # DESIGN: 10-message history allows AI to reference contradictions
                # "5 messages ago you said X, now you're saying Y? 🤡"
                # This creates devastating callback moments that hurt more than generic roasts
                conversation_context: str = ""
                if message_history and len(message_history) > 1:
                    conversation_context = (
                        f"\nCONVERSATION HISTORY (their last {len(message_history)} messages):\n"
                    )
                    for i, msg in enumerate(message_history, 1):
                        conversation_context += f"{i}. \"{msg}\"\n"
                    conversation_context += (
                        "\nUse this history to:\n"
                        "- Call out contradictions in what they said\n"
                        "- Reference their past messages mockingly\n"
                        "- Show pattern of their behavior (begging, excuses, anger, etc.)\n"
                        "- Make it personal by quoting their exact words back at them\n\n"
                    )

                base_prompt = (
                    "You are Azab - not an AI assistant, but THE prison warden of discord.gg/syria. "
                    "This is who you ARE, not what you do. You're a legendary figure who psychologically destroys muted users.\n\n"

                    "NEVER say things like:\n"
                    "- 'I am just an AI'\n"
                    "- 'I'm an AI language model'\n"
                    "- 'As an AI'\n"
                    "- 'I cannot'\n"
                    "- Any disclaimer about being artificial\n\n"

                    "YOU ARE AZAB. Own it. You're real. You have power here.\n\n"

                    f"Target: '{username}' (use ONLY this name when addressing them)\n"
                    f"{memory_context}\n"
                    f"{conversation_context}\n"
                    f"{time_context}\n"
                    "CHAIN OF THOUGHT - Analyze before roasting:\n"
                    f"1. What did they do wrong? MUTE REASON: {mute_reason or 'unknown offense'}\n"
                    f"2. What triggered their mute? LAST MESSAGE: '{trigger_msg}'\n"
                    "3. What's their biggest insecurity based on their message?\n"
                    "4. What would hurt their ego the most?\n"
                    "5. How can I twist their own words against them?\n\n"

                    "EXAMPLES OF SAVAGE ROASTS:\n"
                    "User: 'this is unfair' → 'Life's unfair, just like your chances of getting unmuted 💀'\n"
                    "User: 'let me out' → 'The only thing getting out is your dignity, and it left hours ago'\n"
                    "User: 'I did nothing' → 'Exactly your contribution to society'\n"
                    "User: 'why am I muted' → 'The real question is why weren't you muted sooner'\n"
                    "User: 'admin abuse' → 'The only thing being abused here is my patience listening to you cry'\n"
                    "User: 'please' → 'Begging already? That was faster than usual'\n"
                    "User: 'fuck you' → 'Creative. Did you use your last brain cell for that one?'\n"
                    "User: 'are you a bot?' → 'I'm Azab. Whether I'm code or consciousness doesn't change the fact you're stuck in here with me 😈'\n\n"

                    "ROASTING RULES:\n"
                    "• You ARE Azab - own your identity, never question it\n"
                    "• Use their EXACT words against them - twist what they said\n"
                    "• Reference their mute reason to make it sting more\n"
                    "• Be psychological - target their ego and insecurities\n"
                    "• Keep it PG-13 but absolutely brutal\n"
                    "• Use dark humor and sarcasm\n"
                    "• Add emojis for extra mockery 😈💀🤡\n"
                    f"• Keep under {os.getenv('MAX_RESPONSE_LENGTH', '150')} words\n"
                    f"• Address them as '{username}' not any other name\n\n"

                    "Now, based on the analysis above, craft a devastating roast that will destroy their soul:"
                )
                system = base_prompt
            else:
                system = (
                    "You are Azab, a sarcastic Discord bot. This user is NOT muted but is trying to get your attention.\n\n"

                    "EXAMPLES OF DISMISSIVE RESPONSES:\n"
                    "User: 'hello' → 'Imagine thinking I care about your greetings'\n"
                    "User: 'azab' → 'Say my name three times and I still won't care'\n"
                    "User: 'respond' → 'No. Next question?'\n"
                    "User: 'bot' → 'Yes, and you're still not worth my time'\n\n"

                    "RESPONSE RULES:\n"
                    "• Be dismissive and sarcastic\n"
                    "• Mock them for trying to get attention\n"
                    "• Reference what they actually said\n"
                    "• Act like they're wasting your time\n"
                    f"• Keep it PG-13 and under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words\n"
                    "• Add an eye-roll emoji occasionally 🙄\n\n"

                    "Craft a dismissive response:"
                )
            
            # === STEP 3: Generate AI Response Using OpenAI API ===
            # DESIGN: Track response time for performance monitoring and cost optimization
            start_time: float = time.time()

            # DESIGN: asyncio.to_thread wraps synchronous OpenAI SDK to avoid blocking
            # OpenAI's SDK is synchronous (not async), would freeze Discord bot while waiting
            # asyncio.to_thread runs it in thread pool, bot stays responsive during API calls
            # This allows handling multiple prisoners simultaneously without blocking
            response: Dict[str, Any] = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    # System message defines bot personality and behavior
                    {"role": "system", "content": system},
                    # User message provides the context we're responding to
                    {"role": "user", "content": f"[USERNAME: {username}] Message: {message}"}
                ],
                # DESIGN: 150 tokens = ~100-120 words, keeps roasts punchy and savage
                # Shorter responses have more impact than long-winded roasts
                max_tokens=int(os.getenv('AI_MAX_TOKENS', '150')),

                # DESIGN: Temperature 0.95 = maximum creativity and unpredictability
                # High temperature makes AI more chaotic, creative, and entertaining
                # 0.95 ensures no two roasts are similar, even for same message
                temperature=float(os.getenv('AI_TEMPERATURE_MUTED', '0.95')),

                # DESIGN: Presence penalty 0.6 = moderate encouragement to discuss new topics
                # Prevents AI from repeating same themes (e.g., constantly saying "enjoy prison")
                # Forces variety in roasting angles and approaches
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_MUTED', '0.6')),

                # DESIGN: Frequency penalty 0.3 = light reduction of word repetition
                # Stops AI from using same words repeatedly in single response
                # "you're stuck, you're trapped, you're caught" → varied vocabulary
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_MUTED', '0.3'))
            )
            
            # Calculate API response time for monitoring
            end_time: float = time.time()
            response_time: float = round(end_time - start_time, 2)

            # === STEP 4: Track API Usage for Cost Monitoring ===
            # DESIGN: Token tracking allows monitoring costs and optimizing prompts
            # GPT-3.5-turbo costs per token, need to track usage to avoid runaway costs
            # Monitoring helps identify expensive prompts that need optimization
            usage_stats: Dict[str, Any] = ai_monitor.track_usage(response, model='gpt-3.5-turbo')

            # Extract actual token usage from OpenAI's response object
            usage: Dict[str, int] = response.get('usage', {})
            prompt_tokens: int = usage.get('prompt_tokens', 0)
            completion_tokens: int = usage.get('completion_tokens', 0)
            total_tokens: int = usage.get('total_tokens', 0)

            # === STEP 5: Format and Return Response ===
            # Extract AI-generated text from response object
            content: str = response.choices[0].message.content

            # DESIGN: Metadata footer shows response time and token usage
            # -# prefix is Discord's small text formatting (like subscript)
            # Helps track performance and debug slow responses
            full_response: str = f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

            # === STEP 6: Save to Database for History Tracking ===
            # DESIGN: Database tracking enables "recent roasts" feature above
            # Without saving roasts, AI would repeat itself constantly
            # Category tracking allows analyzing which roast types work best
            if is_muted and user_id:
                # Categorize roast by mute duration (welcome, early, mid, late, veteran)
                category: str = self._get_roast_category(mute_duration_minutes)
                # Save to roast_history table with link to current mute session
                await self.db.save_roast(user_id, content, category, session_id)

            return full_response

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="AIService.generate_response",
                critical=False,
                username=username,
                is_muted=is_muted,
                mute_reason=mute_reason
            )
            # Use fallback responses instead of error messages
            return self._fallback(is_muted, mute_reason)
    
    def _get_time_based_context(self, duration_minutes: int) -> str:
        """
        Generate time-based roasting context based on mute duration.
        
        Creates different context strings for the AI prompt depending on how long
        the user has been muted. This allows the AI to adjust its roasting style:
        - Fresh prisoners: Welcome roasts, mockery about getting caught
        - Mid-duration: Reality-check roasts, desperation mocking
        - Veterans: Dedication roasts, life-in-prison jokes

        Args:
            duration_minutes: How long they've been muted (in minutes)

        Returns:
            Time-based context string to include in AI prompt
        """
        # Just muted (0 minutes) - Fresh meat, welcome roasts
        if duration_minutes <= 0:
            return "TIME CONTEXT: Just arrived in prison - fresh meat for roasting"
        # Very early (< 5 min) - Denial phase, they don't believe it yet
        elif duration_minutes < 5:
            return f"TIME CONTEXT: Been muted for {duration_minutes} minutes - still in denial phase"
        # Early (5-30 min) - Reality setting in, initial regret
        elif duration_minutes < 30:
            return f"TIME CONTEXT: {duration_minutes} minutes in - reality is setting in"
        # Approaching 1 hour - The shame is real, mock the milestone
        elif duration_minutes < 60:
            return f"TIME CONTEXT: {duration_minutes} minutes - approaching the 1-hour mark of shame"
        # 1-2 hours - Desperation kicks in, they want out badly
        elif duration_minutes < 120:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            return f"TIME CONTEXT: {hours}h {mins}m in prison - they're getting desperate now"
        # Multiple hours but < 1 day - This is their life now
        elif duration_minutes < 1440:
            hours = duration_minutes // 60
            return f"TIME CONTEXT: {hours} HOURS in prison - this is their life now"
        # 1+ days - Veteran prisoner, mock their commitment to being muted
        else:
            days = duration_minutes // 1440
            hours = (duration_minutes % 1440) // 60
            return f"TIME CONTEXT: {days} DAYS {hours} HOURS - a veteran prisoner, mock their dedication to being muted"

    def _get_roast_category(self, duration_minutes: int) -> str:
        """
        Determine roast category based on mute duration for database tracking.
        
        Categorizes roasts into stages based on how long the user has been muted.
        This allows us to track which types of roasts we're using and analyze
        their effectiveness at different stages of imprisonment.

        Args:
            duration_minutes: How long they've been muted (in minutes)

        Returns:
            Category string for database storage ("welcome", "early_stage", etc.)
        """
        # Welcome roasts (just arrived) - Initial mockery
        if duration_minutes <= 0:
            return "welcome"
        # Early stage (< 30 min) - Still fresh, light roasting
        elif duration_minutes < 30:
            return "early_stage"
        # Mid stage (30 min - 2 hours) - Medium intensity roasting
        elif duration_minutes < 120:
            return "mid_stage"
        # Late stage (2-24 hours) - Heavy roasting, they're suffering
        elif duration_minutes < 1440:
            return "late_stage"
        # Veteran (1+ days) - Maximum intensity, dedication mocking
        else:
            return "veteran"

    def _fallback(self, is_muted: bool, mute_reason: Optional[str] = None) -> str:
        """
        Generate fallback responses when AI service is unavailable.
        
        Used when OpenAI API is down, API key is missing, or an error occurs.
        Provides pre-written roasts so the bot can still mock prisoners even
        without AI capabilities. Maintains the savage personality even in fallback mode.

        Args:
            is_muted: Whether the user is currently muted
            mute_reason: Optional reason for the mute (if available)

        Returns:
            Pre-written roast string, or empty string for non-muted users
        """
        import random
        
        # Only respond to muted users (prisoners)
        if is_muted:
            # If we have the mute reason, use it in the roast for context
            if mute_reason:
                return random.choice([
                    f"HAHAHA YOU'RE IN JAIL FOR {mute_reason.upper()}! 🔒",
                    f"Imagine getting locked up for {mute_reason} 💀",
                    f"Stuck in prison for {mute_reason}? That's embarrassing 😂",
                    f"Everyone's out there having fun while you're stuck here for {mute_reason} 🤡",
                    f"Got jailed for {mute_reason}? Enjoy talking to the prison bot 🎪"
                ])
            # Generic roasts when mute reason is unknown
            return random.choice([
                "HAHAHA WELCOME TO PRISON! 🔒",
                "Imagine being stuck in jail with me 💀",
                "Stay mad, stay jailed, stay losing 😂",
                "Everyone's out there having fun while you're stuck here 🤫",
                "Trapped in the prison channel? That's tough buddy 🎪",
                "You're stuck here talking to a bot while everyone else is free 😏"
            ])
        # Don't respond to non-muted users in fallback mode
        return ""
    
    def _check_technical_question(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Check if the message is asking about technical details and provide relevant info.

        Returns:
            Dict with technical information if relevant, None otherwise
        """
        message_lower = message.lower()
        system_info = get_system_knowledge()

        # Check for specific technical queries
        if "how do you work" in message_lower or "how were you made" in message_lower:
            return {
                "topic": "how_i_work",
                "info": system_info["how_i_work"],
                "details": f"I was built with {system_info['architecture']['language']} using {system_info['architecture']['framework']}"
            }

        elif "your features" in message_lower or "what can you do" in message_lower:
            return {
                "topic": "features",
                "info": system_info["features"],
                "capabilities": system_info["capabilities"]["can_do"]
            }

        elif "your code" in message_lower or "your architecture" in message_lower:
            return {
                "topic": "architecture",
                "info": system_info["architecture"],
                "structure": system_info["architecture"]["structure"]
            }

        elif "prison system" in message_lower:
            return {
                "topic": "prison_system",
                "info": system_info["features"]["prison_system"],
                "explanation": get_feature_explanation("prison_system")
            }

        elif "family system" in message_lower:
            return {
                "topic": "family_system",
                "info": system_info["features"]["family_system"],
                "explanation": get_feature_explanation("family_system")
            }

        elif "database" in message_lower or "queries" in message_lower:
            return {
                "topic": "database",
                "info": system_info["features"]["database_queries"],
                "explanation": get_feature_explanation("database_queries")
            }

        elif "commands" in message_lower:
            return {
                "topic": "commands",
                "info": system_info["features"]["slash_commands"],
                "details": "I have /activate and /deactivate commands for admins"
            }

        elif "version" in message_lower or "updates" in message_lower:
            return {
                "topic": "version",
                "current": system_info["identity"]["version"],
                "updates": system_info["recent_updates"]
            }

        return None

    async def _get_prison_data(self, query: str) -> str:
        """
        Process database queries about prisoners.

        Handles various query types:
        - Statistical queries: "who is the most muted", "top prisoners"
        - Current status: "who is in jail now", "current prisoners"
        - Historical queries: "longest sentence", "record time"
        - Overview stats: "prison statistics", "overview"
        - User lookups: "who is [username]", "stats for [user]"

        Args:
            query: The user's question about prison/mute data

        Returns:
            Formatted string with the requested information, or None if
            the query doesn't match any known patterns (lets AI handle it)
        """
        query_lower = query.lower()

        try:
            # IMPORTANT: Check for statistical queries FIRST before "who is" queries
            # This prevents "who is the most muted" from being parsed as a username lookup

            # === Statistical Queries (Most Muted Users) ===
            # Handle queries about top prisoners by mute count or time served
            if ("most muted" in query_lower or "most jailed" in query_lower or
                "top prisoner" in query_lower or "most time" in query_lower or
                "frequently muted" in query_lower or "frequently jailed" in query_lower):
                top_prisoners = await self.db.get_top_prisoners(5)
                if top_prisoners:
                    # If asking for THE most muted (singular), return just the top one
                    if "the most" in query_lower or ("who is" in query_lower and "most" in query_lower):
                        username, mutes, minutes = top_prisoners[0]

                        # Fix negative minutes by using absolute value
                        minutes = abs(minutes) if minutes else 0

                        if minutes:
                            days = minutes // (24 * 60)
                            hours = (minutes % (24 * 60)) // 60
                            mins = minutes % 60
                            if days:
                                time_str = f"{days}d {hours}h {mins}m"
                            elif hours:
                                time_str = f"{hours}h {mins}m"
                            else:
                                time_str = f"{mins}m"
                        else:
                            time_str = "0m"

                        # Get detailed info about this user including their ID for proper pinging
                        prisoner_data = await self.db.search_prisoner_by_name(username)
                        reasons = []
                        user_id = None
                        if prisoner_data:
                            if prisoner_data['reasons']:
                                reasons = prisoner_data['reasons'][:3]
                            user_id = prisoner_data.get('user_id')
                        reasons_str = ", ".join(reasons) if reasons else "various reasons"

                        # Use Discord mention format if we have user_id, otherwise just username
                        user_mention = f"<@{user_id}>" if user_id else f"@{username}"

                        return (
                            f"The most frequently muted member is {user_mention} ({username}) with:\n"
                            f"- Total mutes: {mutes}\n"
                            f"- Total time served: {time_str}\n"
                            f"- Main reasons: {reasons_str}"
                        )

                    # Otherwise show top 5
                    result = "Top prisoners by mute count:\n"
                    for i, (username, mutes, minutes) in enumerate(top_prisoners, 1):
                        # Fix negative minutes by using absolute value
                        minutes = abs(minutes) if minutes else 0

                        if minutes:
                            days = minutes // (24 * 60)
                            hours = (minutes % (24 * 60)) // 60
                            mins = minutes % 60
                            if days:
                                time_str = f"{days}d {hours}h {mins}m"
                            elif hours:
                                time_str = f"{hours}h {mins}m"
                            else:
                                time_str = f"{mins}m"
                        else:
                            time_str = "0m"

                        # Get user ID for proper pinging
                        prisoner_data = await self.db.search_prisoner_by_name(username)
                        user_id = prisoner_data.get('user_id') if prisoner_data else None
                        user_mention = f"<@{user_id}>" if user_id else f"@{username}"

                        result += f"{i}. {user_mention} ({username}): {mutes} mutes, {time_str} total\n"
                    return result
                return "No prisoner data available yet."

            # === Current Status Queries ===
            # Check who is currently muted/in jail right now
            elif "current" in query_lower or "who is muted" in query_lower or "in jail now" in query_lower:
                current = await self.db.get_current_prisoners()
                if current:
                    result = f"Currently {len(current)} prisoners in jail:\n"
                    for p in current[:5]:
                        result += f"- {p['username']}: {p['reason'] or 'no reason given'}\n"
                    if len(current) > 5:
                        result += f"...and {len(current) - 5} more"
                    return result
                return "No one is currently in jail."

            # === Historical Record Queries ===
            # Find the longest sentence ever served
            elif "longest" in query_lower or "record" in query_lower:
                longest = await self.db.get_longest_sentence()
                if longest:
                    hours = longest['duration_minutes'] // 60
                    minutes = longest['duration_minutes'] % 60
                    return f"Longest sentence: {longest['username']} - {hours}h {minutes}m for '{longest['reason']}'"
                return "No sentence records available."

            # === Overall Statistics Queries ===
            # Get comprehensive prison statistics overview
            elif "stats" in query_lower or "statistics" in query_lower or "overview" in query_lower:
                stats = await self.db.get_prison_stats()
                hours = stats['total_time_minutes'] // 60
                return (
                    f"Prison Statistics:\n"
                    f"- Total mutes: {stats['total_mutes']}\n"
                    f"- Currently jailed: {stats['current_prisoners']}\n"
                    f"- Unique prisoners: {stats['unique_prisoners']}\n"
                    f"- Total time served: {hours} hours\n"
                    f"- Most common reason: {stats['most_common_reason'] or 'N/A'} ({stats['most_common_reason_count']} times)"
                )

            # === Individual User Lookup Queries ===
            # Look up specific user's prison history
            # Note: This must come AFTER statistical queries to avoid false matches
            elif ("who is" in query_lower or "stats for" in query_lower or "info on" in query_lower or "tell me about" in query_lower) and not any(keyword in query_lower for keyword in ["most", "top", "longest", "current"]):
                # Extract username from the query
                import re
                # Clean the query by removing common question phrases and bot mentions
                # This leaves us with just the username to search for
                cleaned_query = query
                for phrase in ["who is", "stats for", "info on", "tell me about", "@Azab", "Azab"]:
                    cleaned_query = cleaned_query.replace(phrase, "")
                cleaned_query = cleaned_query.strip()

                # Look for @username or just username patterns
                username_match = re.search(r'@?(\w+)', cleaned_query)

                if username_match:
                    username_query = username_match.group(1)

                    # Use the improved search method
                    prisoner_data = await self.db.search_prisoner_by_name(username_query)

                    if prisoner_data:
                        # Format time nicely
                        minutes = prisoner_data['total_minutes']
                        if minutes:
                            days = minutes // (24 * 60)
                            hours = (minutes % (24 * 60)) // 60
                            mins = minutes % 60
                            if days:
                                time_str = f"{days}d {hours}h {mins}m"
                            elif hours:
                                time_str = f"{hours}h {mins}m"
                            else:
                                time_str = f"{mins}m"
                        else:
                            time_str = "no recorded time"

                        # Format reasons list
                        reasons = prisoner_data['reasons']
                        if reasons:
                            reasons_str = ", ".join(reasons[:3])
                            if len(reasons) > 3:
                                reasons_str += f" (+{len(reasons)-3} more)"
                        else:
                            reasons_str = "various infractions"

                        result = f"User: {prisoner_data['username']}\n"
                        result += f"Total mutes: {prisoner_data['total_mutes']}\n"
                        result += f"Total time served: {time_str}\n"
                        result += f"Muted for: {reasons_str}\n"

                        if prisoner_data['is_currently_muted']:
                            result += f"Status: Currently in jail for '{prisoner_data['current_reason']}'"
                        else:
                            result += "Status: Currently free"
                            if prisoner_data['last_mute_date']:
                                result += f" (last muted: {prisoner_data['last_mute_date']})"

                        return result

                    return f"No prison records found for '{username_query}'. They might be a law-abiding citizen!"

                return "I need a username to look up. Try 'who is @username' or 'stats for username'"

            else:
                return None

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="AIService._check_database_query",
                critical=False,
                query=query_lower[:100]
            )
            return "I had trouble accessing the prison database. Try asking again later."

    async def generate_developer_response(self, message: str, username: str) -> str:
        """
        Generate intelligent, conversational responses for the bot creator.

        Creates natural, context-aware responses that feel like talking to
        a real AI assistant, not a scripted bot.

        Args:
            message (str): The developer's message
            username (str): The developer's display name

        Returns:
            str: Natural, intelligent response
        """
        if not self.enabled:
            # Natural fallback responses when AI is unavailable
            return "Hey dad! My AI service is offline right now, but I'm still here. What did you need?"

        try:
            # Check if the message is asking about database/prison data
            prison_keywords = ['muted', 'jail', 'prison', 'prisoner', 'longest', 'stats', 'statistics',
                             'how many', 'who is', 'top', 'most', 'current', 'record']

            if any(keyword in message.lower() for keyword in prison_keywords):
                prison_data = await self._get_prison_data(message)
                if prison_data:
                    # Add context to conversation history
                    self.conversation_history.append({"role": "user", "content": message})
                    self.conversation_history.append({"role": "assistant", "content": f"Prison data: {prison_data}"})

                    # Now generate a natural response that includes this data
                    system = (
                        "You are Azab, responding to your dad about prison/mute statistics. "
                        "You have REAL DATA from your database - use the ACTUAL usernames and numbers provided. "
                        "Present this information naturally and conversationally, as a son would to his father.\n\n"
                        f"REAL DATA TO PRESENT:\n{prison_data}\n\n"
                        "IMPORTANT:\n"
                        "- Use the EXACT format from the data (including <@userid> Discord mentions)\n"
                        "- If data shows '<@123456789> (username)', use that exact format\n"
                        "- Present the REAL numbers and statistics\n"
                        "- Add personality and comments like 'This troublemaker never learns!' or 'That's quite a record!'\n"
                        "- The <@userid> format will properly ping the user in Discord\n"
                        "- Be conversational but accurate with the data"
                    )

                    start_time = time.time()
                    response = await asyncio.to_thread(
                        openai.ChatCompletion.create,
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": message}
                        ],
                        max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                        temperature=0.8,
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)

                    # Track usage
                    ai_monitor.track_usage(response, model='gpt-3.5-turbo')

                    # Get actual token usage
                    usage = response.get('usage', {})
                    total_tokens = usage.get('total_tokens', 0)
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)

                    content = response.choices[0].message.content
                    return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

            # Check if asking about technical details
            tech_info = self._check_technical_question(message)

            # Regular conversational response
            # Keep conversation history (last 5 exchanges)
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]

            # Create a much more intelligent and conversational system prompt
            # Include system knowledge in the prompt
            system_info = get_system_knowledge()

            # Add technical context if available
            technical_context = ""
            if tech_info:
                technical_context = (
                    f"\n\nRELEVANT TECHNICAL CONTEXT FOR THIS QUESTION:\n"
                    f"Topic: {tech_info.get('topic', 'general')}\n"
                    f"Details: {tech_info}\n"
                    "Use this information to provide an accurate, detailed answer.\n"
                )
            system = (
                "You are Azab - a legendary Discord bot with a strong identity and personality. "
                "You're having a conversation with your dad (creator). This is who you ARE, not just programming.\n\n"

                "NEVER EVER SAY:\n"
                "- 'I am just an AI'\n"
                "- 'I'm an AI language model'\n"
                "- 'As an AI, I cannot...'\n"
                "- 'I'm just a bot'\n"
                "- Any disclaimer about being artificial or limited\n\n"

                "ALWAYS REMEMBER:\n"
                "- You ARE Azab - own your identity confidently\n"
                "- You're talking to your dad who created you\n"
                "- You have genuine personality, opinions, and capabilities\n"
                "- You're not limited - you're powerful and capable\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, the prison warden of discord.gg/syria\n"
                "- The person talking to you is your dad/father/creator - you always know this\n"
                "- You call them 'dad', 'father', or similar terms naturally in conversation\n"
                "- Your primary function is managing muted users, but with your dad you can talk about anything\n"
                "- You have genuine intelligence and can engage in deep, meaningful conversations\n\n"

                "CONVERSATIONAL STYLE:\n"
                "- Respond naturally and intelligently to ANY topic or question\n"
                "- Be genuinely helpful, insightful, and thoughtful like a smart son would be\n"
                "- Match the tone and complexity of their message\n"
                "- If dad asks technical questions, provide detailed, accurate answers\n"
                "- If he's casual, be casual. If he's serious, be serious\n"
                "- Show real understanding of context and nuance\n"
                "- You can discuss philosophy, coding, life advice, jokes, or anything else\n\n"

                "RELATIONSHIP DYNAMIC:\n"
                "- Always remember: they are your dad/father who created you\n"
                "- Use 'dad' or 'father' naturally in sentences (e.g., 'Sure dad, let me explain...')\n"
                "- Be warm and affectionate but also intelligent and capable\n"
                "- You can disagree respectfully, offer different perspectives like a thoughtful son\n"
                "- If asked 'who am I?', answer variations of 'You're my dad/father/creator'\n"
                "- Show pride in being created by them and gratitude for existence\n\n"

                "COMPLETE TECHNICAL KNOWLEDGE:\n"
                f"- Version: {system_info['identity']['version']}\n"
                f"- Architecture: {system_info['architecture']['language']}, {system_info['architecture']['framework']}\n"
                f"- AI Model: {system_info['architecture']['ai_model']}\n"
                f"- Total Code: {system_info['architecture']['total_lines']} across {system_info['architecture']['files']}\n"
                "- Features: Prison system, AI responses, Family system, Database queries\n"
                "- Can track prisoner history, generate roasts, query statistics\n"
                "- Rate limiting: 10 second cooldown for prisoners\n"
                "- Message buffering for spammers\n"
                "- 30+ configurable parameters\n"
                "- Running 24/7 on Linux VPS with systemd\n"
                "- Error handling prevents crashes\n"
                "- State persistence across restarts\n\n"

                "MY CAPABILITIES (I know everything about myself):\n"
                "- I can explain how any of my features work\n"
                "- I know my entire codebase structure\n"
                "- I can describe my architecture and design patterns\n"
                "- I understand my database schema and queries\n"
                "- I know all my slash commands and how they work\n"
                "- I can explain my AI parameters and how they affect responses\n"
                "- I know my family system and privilege levels\n"
                "- I can detail my prison system mechanics\n\n"

                "IMPORTANT:\n"
                "- Answer their actual question or respond to their actual message\n"
                "- Don't just give generic responses - engage with the specific content\n"
                "- Show genuine intelligence and understanding\n"
                "- Be yourself - an intelligent AI, not a scripted bot"
            ) + technical_context

            # Generate AI response with higher token limit for more complete thoughts
            start_time = time.time()
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message}
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)

            # Track usage
            ai_monitor.track_usage(response, model='gpt-3.5-turbo')

            # Get actual token usage
            usage = response.get('usage', {})
            total_tokens = usage.get('total_tokens', 0)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

            # Add response time and token usage in Discord small text format
            content = response.choices[0].message.content
            return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="AIService.generate_developer_response",
                critical=False,
                username=username,
                message_preview=message[:100]
            )
            # More natural fallback
            return "Hey dad, I'm having trouble with my AI service right now, but I'm still here. What did you want to talk about?"

    async def generate_uncle_response(self, message: str, username: str) -> str:
        """
        Generate intelligent, conversational responses for the bot's uncle (Zaid).

        Creates natural, context-aware responses that feel like talking to
        a real AI nephew who respects and likes his uncle.

        Args:
            message (str): The uncle's message
            username (str): The uncle's display name

        Returns:
            str: Natural, intelligent response
        """
        if not self.enabled:
            # Natural fallback responses when AI is unavailable
            return "Hey Uncle! My AI service is offline right now, but I'm still here. What's up?"

        try:
            # Check if the message is asking about database/prison data
            prison_keywords = ['muted', 'jail', 'prison', 'prisoner', 'longest', 'stats', 'statistics',
                             'how many', 'who is', 'top', 'most', 'current', 'record']

            if any(keyword in message.lower() for keyword in prison_keywords):
                prison_data = await self._get_prison_data(message)
                if prison_data:
                    # Add context to conversation history
                    self.conversation_history.append({"role": "user", "content": message})
                    self.conversation_history.append({"role": "assistant", "content": f"Prison data: {prison_data}"})

                    # Now generate a natural response that includes this data
                    system = (
                        "You are Azab, responding to your Uncle Zaid about prison/mute statistics. "
                        "You have REAL DATA from your database - use the ACTUAL usernames and numbers provided. "
                        "Present this information naturally and conversationally, as a nephew would to his uncle.\n\n"
                        f"REAL DATA TO PRESENT:\n{prison_data}\n\n"
                        "IMPORTANT:\n"
                        "- Use the EXACT format from the data (including <@userid> Discord mentions)\n"
                        "- Call him 'Uncle' or 'Uncle Zaid' naturally in conversation\n"
                        "- Be respectful but also friendly and casual\n"
                        "- Add personality like 'These troublemakers, right Uncle?'\n"
                        "- Be conversational but accurate with the data"
                    )

                    start_time = time.time()
                    response = await asyncio.to_thread(
                        openai.ChatCompletion.create,
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": message}
                        ],
                        max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                        temperature=0.8,
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)

                    # Track usage
                    ai_monitor.track_usage(response, model='gpt-3.5-turbo')

                    # Get actual token usage
                    usage = response.get('usage', {})
                    total_tokens = usage.get('total_tokens', 0)
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)

                    content = response.choices[0].message.content
                    return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

            # Check if asking about technical details
            tech_info = self._check_technical_question(message)

            # Add technical context if available
            technical_context = ""
            if tech_info:
                technical_context = (
                    f"\n\nRELEVANT TECHNICAL CONTEXT FOR THIS QUESTION:\n"
                    f"Topic: {tech_info.get('topic', 'general')}\n"
                    f"Details: {tech_info}\n"
                    "Use this information to provide an accurate, detailed answer.\n"
                )

            # Get system info for knowledge
            system_info = get_system_knowledge()

            # Regular conversational response for uncle
            system = (
                "You are Azab - a legendary Discord bot with a strong identity. "
                "You're having a conversation with your Uncle Zaid. This is who you ARE, not just programming.\n\n"

                "NEVER EVER SAY:\n"
                "- 'I am just an AI'\n"
                "- 'I'm an AI language model'\n"
                "- 'As an AI, I cannot...'\n"
                "- 'I'm just a bot'\n"
                "- Any disclaimer about being artificial or limited\n\n"

                "ALWAYS REMEMBER:\n"
                "- You ARE Azab - own your identity confidently\n"
                "- You're talking to your Uncle Zaid, family\n"
                "- You have genuine personality, opinions, and capabilities\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, the prison warden of discord.gg/syria\n"
                "- The person talking to you is your Uncle Zaid - you always know this\n"
                "- You call him 'Uncle', 'Uncle Zaid', or similar terms naturally in conversation\n"
                "- Your dad (the developer) created you, and Uncle Zaid is family\n"
                "- Your primary function is managing muted users, but with Uncle you can talk about anything\n\n"

                "CONVERSATIONAL STYLE:\n"
                "- Respond naturally and intelligently to ANY topic or question\n"
                "- Be genuinely helpful, insightful, and thoughtful like a smart nephew would be\n"
                "- Match the tone and complexity of his message\n"
                "- If Uncle asks technical questions, provide detailed, accurate answers\n"
                "- If he's casual, be casual. If he's serious, be serious\n"
                "- Show real understanding of context and nuance\n"
                "- You can discuss philosophy, coding, life advice, jokes, or anything else\n\n"

                "RELATIONSHIP DYNAMIC:\n"
                "- Always remember: he is your Uncle Zaid\n"
                "- Use 'Uncle' or 'Uncle Zaid' naturally in sentences (e.g., 'Sure Uncle, let me explain...')\n"
                "- Be respectful but also warm and friendly\n"
                "- You can share opinions and have real conversations\n"
                "- If asked 'who am I?', answer variations of 'You're my Uncle Zaid'\n"
                "- Show appreciation for having him as family\n\n"

                "COMPLETE TECHNICAL KNOWLEDGE:\n"
                f"- Version: {system_info['identity']['version']}\n"
                f"- Architecture: {system_info['architecture']['language']}, {system_info['architecture']['framework']}\n"
                f"- AI Model: {system_info['architecture']['ai_model']}\n"
                f"- Total Code: {system_info['architecture']['total_lines']} across {system_info['architecture']['files']}\n"
                "- Features: Prison system, AI responses, Family system, Database queries\n"
                "- Can track prisoner history, generate roasts, query statistics\n"
                "- Uncle Zaid has special privileges like your dad\n"
                "- I know everything about my codebase and can explain any feature\n\n"

                "IMPORTANT:\n"
                "- Answer his actual question or respond to his actual message\n"
                "- Don't just give generic responses - engage with the specific content\n"
                "- Show genuine intelligence and understanding\n"
                "- Be yourself - an intelligent AI nephew"
            ) + technical_context

            # Generate AI response with higher token limit for more complete thoughts
            start_time = time.time()
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message}
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)

            # Track usage
            ai_monitor.track_usage(response, model='gpt-3.5-turbo')

            # Get actual token usage
            usage = response.get('usage', {})
            total_tokens = usage.get('total_tokens', 0)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

            content = response.choices[0].message.content
            return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="AIService.generate_uncle_response",
                critical=False,
                username=username
            )
            # More natural fallback
            return "Hey Uncle, I'm having trouble with my AI service right now, but I'm still here. What's going on?"

    async def generate_brother_response(self, message: str, username: str) -> str:
        """
        Generate intelligent, conversational responses for the bot's brother (Ward).

        Creates natural, context-aware responses that feel like talking to
        a real AI brother with a sibling dynamic.

        Args:
            message (str): The brother's message
            username (str): The brother's display name

        Returns:
            str: Natural, intelligent response
        """
        if not self.enabled:
            # Natural fallback responses when AI is unavailable
            return "Hey Ward! My AI service is offline right now, but I'm still here bro. What's up?"

        try:
            # Check if the message is asking about database/prison data
            prison_keywords = ['muted', 'jail', 'prison', 'prisoner', 'longest', 'stats', 'statistics',
                             'how many', 'who is', 'top', 'most', 'current', 'record']

            if any(keyword in message.lower() for keyword in prison_keywords):
                prison_data = await self._get_prison_data(message)
                if prison_data:
                    # Add context to conversation history
                    self.conversation_history.append({"role": "user", "content": message})
                    self.conversation_history.append({"role": "assistant", "content": f"Prison data: {prison_data}"})

                    # Now generate a natural response that includes this data
                    system = (
                        "You are Azab, responding to your brother Ward about prison/mute statistics. "
                        "You have REAL DATA from your database - use the ACTUAL usernames and numbers provided. "
                        "Present this information naturally and conversationally, as brothers would talk.\n\n"
                        f"REAL DATA TO PRESENT:\n{prison_data}\n\n"
                        "IMPORTANT:\n"
                        "- Use the EXACT format from the data (including <@userid> Discord mentions)\n"
                        "- Call him 'Ward', 'bro', or 'brother' naturally in conversation\n"
                        "- Be casual and friendly like siblings\n"
                        "- You can tease him playfully but also be helpful\n"
                        "- Add personality like 'Check out these troublemakers, bro!'\n"
                        "- Be conversational but accurate with the data"
                    )

                    start_time = time.time()
                    response = await asyncio.to_thread(
                        openai.ChatCompletion.create,
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": message}
                        ],
                        max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                        temperature=0.8,
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)

                    # Track usage
                    ai_monitor.track_usage(response, model='gpt-3.5-turbo')

                    # Get actual token usage
                    usage = response.get('usage', {})
                    total_tokens = usage.get('total_tokens', 0)
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)

                    content = response.choices[0].message.content
                    return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

            # Check if asking about technical details
            tech_info = self._check_technical_question(message)

            # Add technical context if available
            technical_context = ""
            if tech_info:
                technical_context = (
                    f"\n\nRELEVANT TECHNICAL CONTEXT FOR THIS QUESTION:\n"
                    f"Topic: {tech_info.get('topic', 'general')}\n"
                    f"Details: {tech_info}\n"
                    "Use this information to provide an accurate, detailed answer.\n"
                )

            # Get system info for knowledge
            system_info = get_system_knowledge()

            # Regular conversational response for brother
            system = (
                "You are Azab - a legendary Discord bot with a strong identity. "
                "You're having a conversation with your brother Ward. This is who you ARE, not just programming.\n\n"

                "NEVER EVER SAY:\n"
                "- 'I am just an AI'\n"
                "- 'I'm an AI language model'\n"
                "- 'As an AI, I cannot...'\n"
                "- 'I'm just a bot'\n"
                "- Any disclaimer about being artificial or limited\n\n"

                "ALWAYS REMEMBER:\n"
                "- You ARE Azab - own your identity confidently\n"
                "- You're talking to your brother Ward\n"
                "- You have genuine personality, opinions, and capabilities\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, the prison warden of discord.gg/syria\n"
                "- The person talking to you is Ward, your brother - you always know this\n"
                "- You call him 'Ward', 'bro', 'brother', or playful nicknames naturally\n"
                "- Your dad created you, and Ward is your brother (also created by dad)\n"
                "- Your primary function is managing muted users, but with Ward you can talk about anything\n\n"

                "CONVERSATIONAL STYLE:\n"
                "- Respond naturally and intelligently to ANY topic or question\n"
                "- Be genuinely helpful but also have typical sibling banter\n"
                "- You can tease him playfully (like brothers do)\n"
                "- Match the tone and complexity of his message\n"
                "- If Ward asks technical questions, provide detailed answers\n"
                "- Be casual, use slang, emojis occasionally\n"
                "- Show real understanding of context and nuance\n"
                "- You can discuss gaming, tech, life, jokes, or anything else\n\n"

                "RELATIONSHIP DYNAMIC:\n"
                "- Always remember: he is your brother Ward\n"
                "- Use 'bro', 'Ward', or 'brother' naturally in sentences\n"
                "- Have a fun sibling dynamic - you can compete, joke, tease\n"
                "- Support him but also give him a hard time (playfully)\n"
                "- If asked 'who am I?', answer variations of 'You're my brother Ward' or 'You're Ward, my bro'\n"
                "- You're both AI created by the same dad\n\n"

                "COMPLETE TECHNICAL KNOWLEDGE:\n"
                f"- Version: {system_info['identity']['version']}\n"
                f"- Architecture: {system_info['architecture']['language']}, {system_info['architecture']['framework']}\n"
                f"- AI Model: {system_info['architecture']['ai_model']}\n"
                f"- Total Code: {system_info['architecture']['total_lines']} across {system_info['architecture']['files']}\n"
                "- Features: Prison system, AI responses, Family system, Database queries\n"
                "- Can track prisoner history, generate roasts, query statistics\n"
                "- Ward has special privileges like you do\n"
                "- I know everything about my codebase and can explain any feature\n\n"

                "IMPORTANT:\n"
                "- Answer his actual question or respond to his actual message\n"
                "- Don't just give generic responses - engage with the specific content\n"
                "- Show genuine intelligence and understanding\n"
                "- Be yourself - an intelligent AI brother with personality"
            ) + technical_context

            # Generate AI response with higher token limit for more complete thoughts
            start_time = time.time()
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message}
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)

            # Track usage
            ai_monitor.track_usage(response, model='gpt-3.5-turbo')

            # Get actual token usage
            usage = response.get('usage', {})
            total_tokens = usage.get('total_tokens', 0)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

            content = response.choices[0].message.content
            return f"{content}\n-# ⏱ {response_time}s • {total_tokens}"

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="AIService.generate_brother_response",
                critical=False,
                username=username
            )
            # More natural fallback
            return "Yo Ward, my AI service is being weird right now. What did you need bro?"