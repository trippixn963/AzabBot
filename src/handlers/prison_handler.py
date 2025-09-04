"""
Azab Discord Bot - Prison Handler
=================================

Handles prisoner welcome and release functionality for muted users.
Manages the prison channel interactions and general channel release messages.

Features:
- Welcome messages for newly muted users
- Release messages when users are unmuted
- Mute reason tracking and storage
- AI-powered contextual responses

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from typing import Optional, Dict

from src.core.logger import logger
from src.services.ai_service import AIService


class PrisonHandler:
    """
    Manages prisoner (muted user) welcome and release operations.
    
    Handles:
    - Detecting when users get muted/unmuted
    - Sending welcome messages to prison channel
    - Sending release messages to general channel
    - Tracking mute reasons for contextual responses
    """
    
    def __init__(self, bot, ai_service: AIService):
        """
        Initialize the prison handler.
        
        Args:
            bot: The Discord bot instance
            ai_service: AI service for generating responses
        """
        self.bot = bot
        self.ai = ai_service
        self.mute_reasons: Dict[int, str] = {}  # Store mute reasons {user_id: reason}
    
    async def handle_new_prisoner(self, member: discord.Member):
        """
        Welcome a newly muted user to prison with savage ragebait.
        
        FIRST scans the logs channel for mute embeds to extract the mute reason,
        THEN generates a contextual AI response to mock the user about
        their specific offense.
        
        Args:
            member (discord.Member): The newly muted Discord member
        """
        try:
            logger.prisoner_event("ARRIVING", member.name)
            
            # Get required channels
            logs_channel = self.bot.get_channel(self.bot.logs_channel_id)
            prison_channel = self.bot.get_channel(self.bot.prison_channel_id)
            
            
            # Validate channels exist
            if not logs_channel or not prison_channel:
                logger.error("Channel Config", "Prison or logs channel not found")
                return
            
            # FIRST: Extract mute reason from logs channel
            # Wait for the mute embed to appear in logs (moderation bots need time to post)
            # Wait for mute embed silently
            await asyncio.sleep(5)  # Give enough time for the mute bot to post the embed
            
            # Check if we already have the mute reason stored
            # Try both user ID and username (case-insensitive) for maximum reliability
            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            if mute_reason:
                # Found stored reason
                pass
            else:
                # Scan logs channel for mute embed
                # Look through recent messages to find the mute embed
                # Scanning for mute reason
                
                messages_checked = 0
                async for message in logs_channel.history(limit=50):  # Check more messages
                    messages_checked += 1
                    if message.embeds:
                        # Process all embeds in this message
                        await self.bot.mute_handler.process_mute_embed(message)
                        
                        # Check if we now have the reason for this specific user
                        mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
                        if mute_reason:
                            # Found reason after scanning
                            break
                
                # Scanned messages for reason
            
            if not mute_reason:
                logger.warning("Mute Reason", f"Not found for {member.name}")
            
            # SECOND: Generate contextual welcome message AFTER extracting reason
            # Create different prompts based on whether we found the mute reason
            # Generate welcome message
            
            if mute_reason:
                # Contextual prompt with specific mute reason for savage mocking
                welcome_prompt = (
                    f"Welcome a prisoner who just got thrown in jail for: '{mute_reason}'. "
                    f"Mock them brutally and specifically about why they got jailed. "
                    f"Make fun of their mute reason. Be savage and reference their specific offense. "
                    f"Tell them they're stuck in prison now with you, the prison bot. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                # Generic prompt when mute reason is unknown
                welcome_prompt = (
                    f"Welcome a prisoner to jail. "
                    f"Mock them for getting locked up. Be savage about being stuck in prison. "
                    f"Make jokes about them being trapped here with you. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            
            # Generate AI response for the welcome
            # Pass mute_reason to AI for contextual responses
            response = await self.ai.generate_response(
                welcome_prompt,
                member.display_name,
                True,  # They're muted
                mute_reason
            )
            
            # THIRD: Send welcome message to prison channel
            # Format: Header + mention + AI-generated savage response
            welcome_msg = f"🔒 **NEW PRISONER ARRIVAL** 🔒\n\n{member.mention}\n\n{response}"
            await prison_channel.send(welcome_msg)
            
            # Log the welcome event
            logger.prisoner_event("WELCOMED", str(member), mute_reason)
            
        except Exception as e:
            logger.error("Prisoner Welcome", str(e))
    
    async def handle_prisoner_release(self, member: discord.Member):
        """
        Send a message when a user gets unmuted (freed from prison).
        
        Sends a sarcastic/mocking message to the general chat when someone
        gets unmuted, making fun of their time in prison.
        
        Args:
            member (discord.Member): The newly unmuted Discord member
        """
        try:
            logger.prisoner_event("RELEASING", member.name)
            
            # Get the general channel
            general_channel = self.bot.get_channel(self.bot.general_channel_id)
            
            if not general_channel:
                logger.error("Channel Config", "General channel not found")
                return
            
            # Get their mute reason if we have it
            # Try both user ID and username for maximum reliability
            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            # Generate a release message
            # Create different prompts based on whether we have the original offense
            if mute_reason:
                # Contextual release prompt with specific offense reference
                release_prompt = (
                    f"Someone just got released from prison where they were locked up for: '{mute_reason}'. "
                    f"Mock them sarcastically about being freed. Make jokes about their time in jail. "
                    f"Act like they probably didn't learn their lesson. "
                    f"Be sarcastic about them being 'reformed'. Keep it under 50 words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                # Generic release prompt when offense is unknown
                release_prompt = (
                    f"Someone just got released from prison. "
                    f"Mock them about finally being free. Be sarcastic about their jail time. "
                    f"Make jokes about them probably going back soon. Keep it under 50 words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            
            # Generate AI response
            # Pass mute_reason to AI for contextual release messages
            response = await self.ai.generate_response(
                release_prompt,
                member.display_name,
                False,  # They're NOT muted anymore
                mute_reason
            )
            
            # Send release message to general channel
            # Format: Header + mention + AI-generated sarcastic response
            release_msg = f"🔓 **PRISONER RELEASED** 🔓\n\n{member.mention} {response}"
            await general_channel.send(release_msg)
            
            # Clear their mute reason since they're free now
            # Clean up both user ID and username mappings
            if member.id in self.mute_reasons:
                del self.mute_reasons[member.id]
            if member.name.lower() in self.mute_reasons:
                del self.mute_reasons[member.name.lower()]
            
            # Log the release event
            logger.prisoner_event("FREED", str(member), mute_reason)
            
        except Exception as e:
            logger.error("Prisoner Release", str(e))