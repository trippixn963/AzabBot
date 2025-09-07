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
from typing import Optional, Dict, Any

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
    
    def __init__(self, bot: Any, ai_service: AIService) -> None:
        """
        Initialize the prison handler.
        
        Args:
            bot: The Discord bot instance
            ai_service: AI service for generating responses
        """
        self.bot: Any = bot
        self.ai: AIService = ai_service
        self.mute_reasons: Dict[int, str] = {}  # Store mute reasons {user_id: reason}
    
    async def handle_new_prisoner(self, member: discord.Member) -> None:
        """
        Welcome a newly muted user to prison with savage ragebait.
        
        FIRST scans the logs channel for mute embeds to extract the mute reason,
        THEN generates a contextual AI response to mock the user about
        their specific offense.
        
        Args:
            member (discord.Member): The newly muted Discord member
        """
        try:
            logger.info(f"Handling new prisoner: {member.name} (ID: {member.id})")
            
            # Get required channels
            logs_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.logs_channel_id)
            prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.prison_channel_id)
            
            logger.info(f"Channels - Logs: {logs_channel}, Prison: {prison_channel}")
            
            # Validate channels exist
            if not logs_channel or not prison_channel:
                logger.error(f"Channels not found - logs: {self.bot.logs_channel_id}, prison: {self.bot.prison_channel_id}")
                return
            
            # FIRST: Extract mute reason from logs channel
            # Wait for the mute embed to appear in logs (moderation bots need time to post)
            logger.info(f"Waiting for mute embed to appear in logs for {member.name}")
            await asyncio.sleep(5)  # Give enough time for the mute bot to post the embed
            
            # Check if we already have the mute reason stored
            # Try both user ID and username (case-insensitive) for maximum reliability
            mute_reason: Optional[str] = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            # Get prisoner's history for enhanced roasting
            prisoner_stats: Dict[str, Any] = await self.bot.db.get_prisoner_stats(member.id)
            
            if mute_reason:
                logger.info(f"Found stored mute reason for {member.name}: {mute_reason}")
            else:
                # Scan logs channel for mute embed
                # Look through recent messages to find the mute embed
                logger.info(f"Scanning logs channel for {member.name}'s mute reason...")
                
                messages_checked: int = 0
                async for message in logs_channel.history(limit=50):  # Check more messages
                    messages_checked += 1
                    if message.embeds:
                        # Process all embeds in this message
                        await self.bot.mute_handler.process_mute_embed(message)
                        
                        # Check if we now have the reason for this specific user
                        mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
                        if mute_reason:
                            logger.success(f"Found mute reason for {member.name}: {mute_reason}")
                            break
                
                logger.info(f"Scanned {messages_checked} messages in logs channel")
            
            if not mute_reason:
                logger.warning(f"Could not find mute reason for {member.name} - will use generic welcome")
            
            # SECOND: Generate contextual welcome message AFTER extracting reason
            # Create different prompts based on whether we found the mute reason
            logger.info(f"Generating welcome message for {member.name} with reason: {mute_reason or 'None'}")
            
            welcome_prompt: str
            if mute_reason:
                # Contextual prompt with specific mute reason and history for savage mocking
                welcome_prompt = (
                    f"Welcome a prisoner who just got thrown in jail for: '{mute_reason}'. "
                    f"Mock them brutally and specifically about why they got jailed. "
                )
                
                # Add history roasting if they're a repeat offender
                if prisoner_stats['total_mutes'] > 0:
                    welcome_prompt += (
                        f"This is their {prisoner_stats['total_mutes'] + 1}th time in prison! "
                        f"They've spent {prisoner_stats['total_minutes'] or 0} total minutes locked up before. "
                        f"Mock them for being a repeat offender who never learns. "
                    )
                
                welcome_prompt += (
                    f"Be savage and reference their specific offense. "
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
            response: str = await self.ai.generate_response(
                welcome_prompt,
                member.display_name,
                True,  # They're muted
                mute_reason
            )
            
            # THIRD: Send welcome message to prison channel
            # Format: Header + mention + AI-generated savage response
            welcome_msg: str = f"🔒 **NEW PRISONER ARRIVAL** 🔒\n\n{member.mention}\n\n{response}"
            await prison_channel.send(welcome_msg)
            
            # Update presence to show prisoner arrival
            asyncio.create_task(self.bot.presence_handler.show_prisoner_arrived())
            
            # Record mute in database
            await self.bot.db.record_mute(
                user_id=member.id,
                username=member.name,
                reason=mute_reason or "Unknown",
                muted_by=None  # We could extract this from embeds later
            )
            
            # Log the welcome event
            logger.tree("NEW PRISONER WELCOMED", [
                ("Prisoner", str(member)),
                ("Reason", mute_reason[:50] if mute_reason else "Unknown"),
                ("Times Muted", str(prisoner_stats['total_mutes'] + 1)),
                ("Welcome", response[:50])
            ], "⛓️")
            
        except Exception as e:
            logger.error(f"Failed to welcome prisoner: {e}")
    
    async def handle_prisoner_release(self, member: discord.Member) -> None:
        """
        Send a message when a user gets unmuted (freed from prison).
        
        Sends a sarcastic/mocking message to the general chat when someone
        gets unmuted, making fun of their time in prison.
        
        Args:
            member (discord.Member): The newly unmuted Discord member
        """
        try:
            logger.info(f"Handling prisoner release: {member.name} (ID: {member.id})")
            
            # Get the general channel
            general_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.general_channel_id)
            
            if not general_channel:
                logger.error(f"General channel not found: {self.bot.general_channel_id}")
                return
            
            # Get their mute reason if we have it
            # Try both user ID and username for maximum reliability
            mute_reason: Optional[str] = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            # Get prisoner's history
            prisoner_stats: Dict[str, Any] = await self.bot.db.get_prisoner_stats(member.id)
            
            # Generate a release message
            # Create different prompts based on whether we have the original offense
            release_prompt: str
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
            response: str = await self.ai.generate_response(
                release_prompt,
                member.display_name,
                False,  # They're NOT muted anymore
                mute_reason
            )
            
            # Send release message to general channel
            # Format: Header + mention + AI-generated sarcastic response
            release_msg: str = f"🔓 **PRISONER RELEASED** 🔓\n\n{member.mention} {response}"
            await general_channel.send(release_msg)
            
            # Update presence to show prisoner release
            asyncio.create_task(self.bot.presence_handler.show_prisoner_released())
            
            # Record unmute in database
            await self.bot.db.record_unmute(
                user_id=member.id,
                unmuted_by=None  # We could track who unmuted later
            )
            
            # Clear their mute reason since they're free now
            # Clean up both user ID and username mappings
            if member.id in self.mute_reasons:
                del self.mute_reasons[member.id]
            if member.name.lower() in self.mute_reasons:
                del self.mute_reasons[member.name.lower()]
            
            # Log the release event
            logger.tree("PRISONER RELEASED", [
                ("Ex-Prisoner", str(member)),
                ("Previous Offense", mute_reason[:50] if mute_reason else "Unknown"),
                ("Total Times Muted", str(prisoner_stats['total_mutes'])),
                ("Release Message", response[:50])
            ], "🔓")
            
        except Exception as e:
            logger.error(f"Failed to handle prisoner release: {e}")