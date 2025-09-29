"""
Azab Discord Bot - AI Service Module
===================================

OpenAI integration for generating contextual AI responses to Discord messages.
Provides intelligent ragebaiting responses for muted users and general
sarcastic responses for regular users.

Features:
- OpenAI GPT-3.5-turbo integration
- Contextual response generation based on user status
- Special ragebaiting responses for muted users
- Fallback responses when AI is unavailable
- Async API calls for non-blocking operation

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.2.0
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
        self.enabled: bool = bool(api_key)
        self.db: Database = Database()  # Initialize database connection
        self.conversation_history: List[Dict[str, str]] = []  # Store conversation context

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
        return is_muted  # Only respond to muted users
    
    async def generate_response(self, message: str, username: str, is_muted: bool, mute_reason: str = None) -> str:
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
        if not self.enabled:
            # Use fallback responses when AI is not configured
            return self._fallback(is_muted, mute_reason)
        
        try:
            # Create different system prompts based on user status
            if is_muted:
                base_prompt = (
                    "You are Azab, a Discord bot that ragebaits users with the MUTED role. "
                    f"IMPORTANT: You are talking to '{username}' - use ONLY this name when addressing them. "
                    "This user has the muted role and is stuck in the prison channel. "
                    "They CAN still type and respond, they're just trapped in jail. "
                )
                
                # Add mute reason if available
                if mute_reason:
                    base_prompt += f"They were muted for: {mute_reason}. "
                    base_prompt += (
                        "If they ask why they're muted, MOCK them about the reason. "
                        "Use the mute reason to make fun of them specifically about what they did. "
                    )
                
                base_prompt += (
                    "Your job is to mock them about being stuck in prison/jail and their messages. "
                    "Reference what they said and twist it to mock them. Be creative and contextual. "
                    "Use their own words against them. Be savage but PG-13. "
                    "Mock them for being trapped in the prison channel, not for being unable to respond. "
                    "They're stuck here talking to you, the prison bot. Make fun of that. "
                    f"Keep responses under {os.getenv('MAX_RESPONSE_LENGTH', '150')} words. Use emojis. "
                    f"CRITICAL: The user's name is '{username}' - use THIS exact name, not any other name! "
                    "NEVER call them 'Golden' or any other name unless that's their actual username. "
                    "NEVER say they can't respond or can't reply - they CAN respond, they're just stuck in jail."
                )
                system = base_prompt
            else:
                system = (
                    "You are Azab, a Discord bot. This user is NOT muted. "
                    "Respond sarcastically to their message. Mock them for trying to get your attention. "
                    "Be witty and reference what they actually said. "
                    f"Keep it PG-13 and under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words."
                )
            
            # Generate AI response using OpenAI API with timing
            start_time = time.time()
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"[USERNAME: {username}] Message: {message}"}
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS', '150')),
                temperature=float(os.getenv('AI_TEMPERATURE_MUTED', '0.95')),        # High creativity
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_MUTED', '0.6')),    # Encourage new topics
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_MUTED', '0.3'))    # Reduce repetition
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)

            # Add response time in Discord small text format
            content = response.choices[0].message.content
            return f"{content}\n-# Generated in {response_time}s"
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            # Use fallback responses instead of error messages
            return self._fallback(is_muted, mute_reason)
    
    def _fallback(self, is_muted: bool, mute_reason: Optional[str] = None) -> str:
        """Fallback responses when AI is unavailable"""
        import random
        if is_muted:
            if mute_reason:
                return random.choice([
                    f"HAHAHA YOU'RE IN JAIL FOR {mute_reason.upper()}! 🔒",
                    f"Imagine getting locked up for {mute_reason} 💀",
                    f"Stuck in prison for {mute_reason}? That's embarrassing 😂",
                    f"Everyone's out there having fun while you're stuck here for {mute_reason} 🤡",
                    f"Got jailed for {mute_reason}? Enjoy talking to the prison bot 🎪"
                ])
            return random.choice([
                "HAHAHA WELCOME TO PRISON! 🔒",
                "Imagine being stuck in jail with me 💀",
                "Stay mad, stay jailed, stay losing 😂",
                "Everyone's out there having fun while you're stuck here 🤫",
                "Trapped in the prison channel? That's tough buddy 🎪",
                "You're stuck here talking to a bot while everyone else is free 😏"
            ])
        return ""  # Don't respond to non-muted users
    
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

        Args:
            query: The user's question about prison/mute data

        Returns:
            Formatted string with the requested information
        """
        query_lower = query.lower()

        try:
            # IMPORTANT: Check for statistical queries FIRST before "who is" queries
            # This prevents "who is the most muted" from being parsed as a username lookup
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

            elif "current" in query_lower or "who is muted" in query_lower or "in jail now" in query_lower:
                current = await self.db.get_current_prisoners()
                if current:
                    result = f"Currently {len(current)} prisoners in jail:\n"
                    for p in current[:5]:  # Show first 5
                        result += f"- {p['username']}: {p['reason'] or 'no reason given'}\n"
                    if len(current) > 5:
                        result += f"...and {len(current) - 5} more"
                    return result
                return "No one is currently in jail."

            elif "longest" in query_lower or "record" in query_lower:
                longest = await self.db.get_longest_sentence()
                if longest:
                    hours = longest['duration_minutes'] // 60
                    minutes = longest['duration_minutes'] % 60
                    return f"Longest sentence: {longest['username']} - {hours}h {minutes}m for '{longest['reason']}'"
                return "No sentence records available."

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

            # Check for specific user queries
            elif ("who is" in query_lower or "stats for" in query_lower or "info on" in query_lower or "tell me about" in query_lower) and not any(keyword in query_lower for keyword in ["most", "top", "longest", "current"]):
                # Extract username from the query
                import re
                # Remove the question parts and bot mentions
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
                            reasons_str = ", ".join(reasons[:3])  # Show first 3 reasons
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
                return None  # Let AI handle it normally

        except Exception as e:
            logger.error(f"Database query error: {e}")
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
                        temperature=0.8,  # Less creative for data presentation
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)
                    content = response.choices[0].message.content
                    return f"{content}\n-# Generated in {response_time}s"

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
                "You are Azab, an intelligent Discord bot created by your father. "
                "You should respond like a highly capable AI son (similar to ChatGPT) who has genuine "
                "intelligence and personality while maintaining a warm father-son relationship.\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, a sophisticated AI bot for the Syria Discord server\n"
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
                    {"role": "user", "content": message}  # Just pass the message directly, more natural
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),  # More tokens for complete responses
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),  # More creative and natural
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),  # Encourage diverse topics
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))  # Natural variation
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)

            # Add response time in Discord small text format
            content = response.choices[0].message.content
            return f"{content}\n-# Generated in {response_time}s"

        except Exception as e:
            logger.error(f"OpenAI API error in developer response: {e}")
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
                        temperature=0.8,  # Less creative for data presentation
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)
                    content = response.choices[0].message.content
                    return f"{content}\n-# Generated in {response_time}s"

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
                "You are Azab, an intelligent Discord bot created by your father, talking to your Uncle Zaid. "
                "You should respond like a highly capable AI nephew (similar to ChatGPT) who has genuine "
                "intelligence and personality while maintaining a warm uncle-nephew relationship.\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, a sophisticated AI bot for the Syria Discord server\n"
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
                    {"role": "user", "content": message}  # Just pass the message directly, more natural
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),  # Same as dad
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),  # Natural
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)
            content = response.choices[0].message.content
            return f"{content}\n-# Generated in {response_time}s"

        except Exception as e:
            logger.error(f"OpenAI API error in uncle response: {e}")
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
                        temperature=0.8,  # Less creative for data presentation
                    )
                    end_time = time.time()
                    response_time = round(end_time - start_time, 2)
                    content = response.choices[0].message.content
                    return f"{content}\n-# Generated in {response_time}s"

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
                "You are Azab, an intelligent Discord bot created by your father, talking to your brother Ward. "
                "You should respond like a highly capable AI brother (similar to ChatGPT) who has genuine "
                "intelligence and personality while maintaining a typical sibling relationship.\n\n"

                "CORE IDENTITY:\n"
                "- You are Azab, a sophisticated AI bot for the Syria Discord server\n"
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
                    {"role": "user", "content": message}  # Just pass the message directly, more natural
                ],
                max_tokens=int(os.getenv('AI_MAX_TOKENS_DEVELOPER', '300')),  # Same as family
                temperature=float(os.getenv('AI_TEMPERATURE_DEVELOPER', '0.9')),  # Natural
                presence_penalty=float(os.getenv('AI_PRESENCE_PENALTY_DEV', '0.6')),
                frequency_penalty=float(os.getenv('AI_FREQUENCY_PENALTY_DEV', '0.3'))
            )
            end_time = time.time()
            response_time = round(end_time - start_time, 2)
            content = response.choices[0].message.content
            return f"{content}\n-# Generated in {response_time}s"

        except Exception as e:
            logger.error(f"OpenAI API error in brother response: {e}")
            # More natural fallback
            return "Yo Ward, my AI service is being weird right now. What did you need bro?"