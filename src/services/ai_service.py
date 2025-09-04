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
Version: Modular
"""

import openai
import asyncio
import random
from typing import Optional

from src.core.logger import logger


class AIService:
    """
    OpenAI integration service for generating Discord bot responses.
    
    Handles AI-powered response generation with different behaviors:
    - Ragebaiting responses for muted/timed out users
    - Sarcastic responses for regular users
    - Fallback responses when AI service is unavailable
    
    Uses OpenAI's GPT-3.5-turbo model for contextual and creative responses.
    """
    
    def __init__(self, api_key: Optional[str]):
        """
        Initialize the AI service with OpenAI API key.
        
        Args:
            api_key (Optional[str]): OpenAI API key for authentication
        """
        self.enabled = bool(api_key)
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
                    "Keep responses under 100 words. Use emojis. "
                    "IMPORTANT: Use their name directly without quotes (e.g., 'Golden' should be just Golden). "
                    "NEVER say they can't respond or can't reply - they CAN respond, they're just stuck in jail."
                )
                system = base_prompt
            else:
                system = (
                    "You are Azab, a Discord bot. This user is NOT muted. "
                    "Respond sarcastically to their message. Mock them for trying to get your attention. "
                    "Be witty and reference what they actually said. "
                    "Keep it PG-13 and under 50 words."
                )
            
            # Generate AI response using OpenAI API
            response = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"The user {username} said: {message}"}
                ],
                max_tokens=150,
                temperature=0.95,        # High creativity
                presence_penalty=0.6,    # Encourage new topics
                frequency_penalty=0.3    # Reduce repetition
            )
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            # Use fallback responses instead of error messages
            return self._fallback(is_muted, mute_reason)
    
    def _fallback(self, is_muted: bool, mute_reason: str = None) -> str:
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