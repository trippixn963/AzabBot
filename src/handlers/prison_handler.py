"""
Azab Discord Bot - Prison Handler
=================================

Handles prisoner welcome and release functionality for muted users.
Manages the prison channel interactions and general channel release messages.

Features:
- Welcome messages for newly muted users with reason context
- Release messages when users are unmuted
- Mute reason extraction from logs channel
- AI-powered contextual responses
- Prisoner statistics and history tracking
- Repeat offender detection and roasting
- Rich embeds with prisoner records
- Automatic database logging

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

import discord
import asyncio
import os
from typing import Optional, Dict, Any

from src.core.logger import logger
from src.services.ai_service import AIService
from src.utils import format_duration
from src.utils.error_handler import ErrorHandler


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
        self.last_messages: Dict[int, str] = {}  # Store last message from each user {user_id: message}
    
    async def handle_new_prisoner(self, member: discord.Member) -> None:
        """
        Welcome a newly muted user to prison with savage ragebait.
        
        This is the main prisoner onboarding function. It executes a multi-step process:
        1. Extract mute reason from logs channel embeds
        2. Gather prisoner statistics (repeat offender data)
        3. Generate contextual AI roast based on their offense
        4. Create rich embed with prisoner info
        5. Send welcome message to prison channel
        6. Update presence to show new prisoner
        7. Log mute to database
        
        FIRST scans the logs channel for mute embeds to extract the mute reason,
        THEN generates a contextual AI response to mock the user about
        their specific offense.
        
        Args:
            member (discord.Member): The newly muted Discord member
        """
        try:
            logger.info(f"Handling new prisoner: {member.name} (ID: {member.id})")
            
            # === STEP 0: Get Required Discord Channels ===
            # Retrieve logs channel (where mod bot posts mute embeds)
            # Retrieve prison channel (where we send welcome messages)
            logs_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.logs_channel_id)
            prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.prison_channel_id)
            
            logger.info(f"Channels - Logs: {logs_channel}, Prison: {prison_channel}")
            
            # Validate both channels exist before proceeding
            # If either is None, bot doesn't have access or IDs are wrong
            if not logs_channel or not prison_channel:
                logger.error(f"Channels not found - logs: {self.bot.logs_channel_id}, prison: {self.bot.prison_channel_id}")
                return  # Can't proceed without channels
            
            # === STEP 1: Extract Mute Reason from Logs Channel ===
            # Wait briefly for moderation bot to post the mute embed
            # Mod bots typically post embeds 1-3 seconds after role assignment
            # Configurable delay via MUTE_EMBED_WAIT_TIME (default 5 seconds)
            logger.info(f"Waiting for mute embed to appear in logs for {member.name}")
            await asyncio.sleep(int(os.getenv('MUTE_EMBED_WAIT_TIME', '5')))
            
            # === Check In-Memory Cache First ===
            # Mute reasons are cached in memory when we process embeds
            # Try both user_id and username.lower() for maximum reliability
            # (Some mod bots use mentions, others use raw usernames)
            mute_reason: Optional[str] = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            # === Fetch Prisoner History from Database ===
            # Get complete stats: total mutes, time served, reasons, etc.
            # Used for repeat offender detection and enhanced roasting
            prisoner_stats: Dict[str, Any] = await self.bot.db.get_prisoner_stats(member.id)
            
            # === Check if Reason Was Found in Cache ===
            if mute_reason:
                logger.info(f"Found stored mute reason for {member.name}: {mute_reason}")
            else:
                # === Reason Not Cached: Scan Logs Channel ===
                # If not in cache, scan recent messages in logs channel
                # This happens if:
                # 1. Mute embed posted after our cache was processed
                # 2. Bot restarted recently and cache was cleared
                # 3. Mod bot posted embed before Discord.py saw the role change
                logger.info(f"Scanning logs channel for {member.name}'s mute reason...")
                
                messages_checked: int = 0
                # Iterate through recent logs channel messages
                # Configurable limit via LOG_CHANNEL_SCAN_LIMIT (default 50)
                async for message in logs_channel.history(limit=int(os.getenv('LOG_CHANNEL_SCAN_LIMIT', '50'))):
                    messages_checked += 1
                    # Check if message contains embeds (mod bots use embeds for mute logs)
                    if message.embeds:
                        # Process embed and extract any mute reasons
                        # This updates self.mute_reasons cache for all users found
                        await self.bot.mute_handler.process_mute_embed(message)
                        
                        # Check if we now have reason for THIS specific user
                        # Re-check both ID and username after processing
                        mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
                        if mute_reason:
                            logger.success(f"Found mute reason for {member.name}: {mute_reason}")
                            break  # Found it! Stop scanning
                
                logger.info(f"Scanned {messages_checked} messages in logs channel")
            
            # Log warning if reason still not found (will use generic welcome)
            if not mute_reason:
                logger.warning(f"Could not find mute reason for {member.name} - will use generic welcome")
            
            # === STEP 2: Generate Contextual Welcome Message ===
            # Build AI prompt based on available context and generate savage welcome roast
            logger.info(f"Generating welcome message for {member.name} with reason: {mute_reason or 'None'}")
            
            # === Build AI Prompt with Available Context ===
            welcome_prompt: str
            if mute_reason:
                # === CONTEXTUAL PROMPT: We Have Mute Reason ===
                # Build detailed prompt referencing their specific offense
                # This creates much more savage and relevant roasts
                welcome_prompt = (
                    f"Welcome a prisoner who just got thrown in jail for: '{mute_reason}'. "
                    f"Mock them brutally and specifically about why they got jailed. "
                )
                
                # === Add Repeat Offender Roasting ===
                # If they've been muted before, add extra context for AI
                # Allows AI to mock them for being a repeat offender
                if prisoner_stats['total_mutes'] > 0:
                    # Format their total prison time in human-readable format
                    total_time = format_duration(prisoner_stats['total_minutes'] or 0)
                    # Add repeat offender context to prompt
                    welcome_prompt += (
                        f"This is their {prisoner_stats['total_mutes'] + 1}th time in prison! "
                        f"They've spent {total_time} locked up before. "
                        f"Mock them for being a repeat offender who never learns. "
                    )
                
                # === Add Prompt Instructions ===
                welcome_prompt += (
                    f"Be savage and reference their specific offense. "
                    f"Tell them they're stuck in prison now with you, the prison bot. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                # === GENERIC PROMPT: No Mute Reason Available ===
                # Fall back to generic welcome roast when reason is unknown
                # Still savage but less specific
                welcome_prompt = (
                    f"Welcome a prisoner to jail. "
                    f"Mock them for getting locked up. Be savage about being stuck in prison. "
                    f"Make jokes about them being trapped here with you. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            
            # === Generate AI Welcome Response ===
            # Call AI service with built prompt to generate savage welcome message
            # AI will use mute_reason, prisoner history, and context to create personalized roast
            response: str = await self.ai.generate_response(
                welcome_prompt,
                member.display_name,
                True,  # is_muted = True (they just got muted)
                mute_reason  # Pass reason for additional context
            )
            
            # === STEP 3: Create Rich Embed for Welcome Message ===
            # Build visually appealing Discord embed to display prisoner information
            # Embed structure: Title, Description (mention), Fields (reason/stats), Thumbnail, Footer
            embed = discord.Embed(
                title="🔒 NEW PRISONER ARRIVAL",  # Clear title with emoji
                description=f"{member.mention}\n",  # Ping user so they know they're being roasted
                color=int(os.getenv('EMBED_COLOR_ERROR', '0xFF0000'), 16)  # Red color (hex FF0000 = danger/prison)
            )
            
            # === Add Mute Reason Field (If Available) ===
            # Display why they were imprisoned (extracted from logs channel)
            # Truncate to avoid breaking Discord's embed field limits
            if mute_reason:
                embed.add_field(
                    name="Reason",  # Field title
                    value=f"{mute_reason[:int(os.getenv('MUTE_REASON_MAX_LENGTH', '100'))]}",  # Truncate if too long
                    inline=False  # Full width field (reason is important, give it space)
                )
            
            # Note: AI response is sent as separate message text, not in embed
            # This allows Discord to render it properly with markdown
            
            # === Add Prison Record for Repeat Offenders ===
            # Only show stats if they've been muted before (total_mutes > 0)
            # Displays visit number and total time served across all mutes
            if prisoner_stats['total_mutes'] > 0:
                # Field 1: Visit number (inline for compact display)
                embed.add_field(
                    name="Prison Record",
                    value=f"Visit #{prisoner_stats['total_mutes'] + 1}",  # +1 because this is their NEW visit
                    inline=True  # Allow side-by-side with next field
                )
                # Field 2: Total time served (formatted as "Xd Yh Zm")
                total_time = format_duration(prisoner_stats['total_minutes'] or 0)
                embed.add_field(
                    name="Total Time Served",
                    value=total_time,  # Human-readable duration
                    inline=True  # Displays next to Prison Record field
                )
            
            # === Set Embed Visual Elements ===
            # Thumbnail: Show prisoner's Discord avatar (or default if none)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            
            # Footer: Developer credit with their profile picture
            # Consistent branding across all bot embeds
            developer = await self.bot.fetch_user(self.bot.developer_id)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(
                text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}",  # Arabic name for authenticity
                icon_url=developer_avatar  # Small avatar icon in footer
            )
            
            # === STEP 4: Send Welcome Message to Prison Channel ===
            # Send both AI response and rich embed together
            # Format: "@user [AI roast]" + [Rich Embed with details]
            await prison_channel.send(f"{member.mention} {response}", embed=embed)
            
            # === STEP 5: Update Bot Rich Presence ===
            # Temporarily change bot's Discord status to show new prisoner arrival
            # Displays on bot's profile: "🔒 username: reason" or special messages for repeat offenders
            total_mutes = prisoner_stats.get('total_mutes', 1) if prisoner_stats else 1
            # Create async task so presence update doesn't block (runs in parallel)
            asyncio.create_task(self.bot.presence_handler.show_prisoner_arrived(
                username=member.name,    # Who got muted
                reason=mute_reason,      # Why they got muted
                mute_count=total_mutes   # How many times (for repeat offender detection)
            ))
            
            # === STEP 6: Get Trigger Message for Database ===
            # Retrieve the last message this user sent before getting muted
            # This is cached in memory by on_message handler
            # Used for contextual roasting: "You said X and got muted for it"
            trigger_message = self.last_messages.get(member.id, None)

            # === STEP 7: Record Mute in Database ===
            # Log this mute event to prisoner_history table for analytics and history
            # This creates a permanent record with all mute details
            await self.bot.db.record_mute(
                user_id=member.id,                   # Discord ID (indexed for fast lookups)
                username=member.name,                 # Username at time of mute (preserved)
                reason=mute_reason or "Unknown",      # Mute reason from logs (or "Unknown" fallback)
                muted_by=None,                        # Who muted them (could extract from embeds later)
                trigger_message=trigger_message       # Message that got them muted (for AI context)
            )
            
            # === STEP 8: Log Welcome Event to Console ===
            # Create structured log entry for monitoring and debugging
            # Tree format makes it easy to read in logs
            logger.tree("NEW PRISONER WELCOMED", [
                ("Prisoner", str(member)),  # Full Discord username#discriminator
                # Truncate reason to configurable length (default 50 chars)
                ("Reason", mute_reason[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))] if mute_reason else "Unknown"),
                ("Times Muted", str(prisoner_stats['total_mutes'] + 1)),  # Total count including this one
                # Truncate AI response for log readability
                ("Welcome", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            ], "⛓️")  # Prison chain emoji for visual identification
            
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler.handle_new_prisoner",
                critical=False,
                member=member.name,
                member_id=member.id
            )
    
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

            # Get the duration of this specific mute session
            current_session_duration: int = await self.bot.db.get_current_mute_duration(member.id)
            
            # Generate a release message
            # Create different prompts based on whether we have the original offense
            release_prompt: str
            if mute_reason:
                # Contextual release prompt with specific offense reference
                release_prompt = (
                    f"Someone just got released from prison where they were locked up for: '{mute_reason}'. "
                    f"Mock them sarcastically about being freed. Make jokes about their time in jail. "
                    f"Act like they probably didn't learn their lesson. "
                    f"Be sarcastic about them being 'reformed'. Keep it under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                # Generic release prompt when offense is unknown
                release_prompt = (
                    f"Someone just got released from prison. "
                    f"Mock them about finally being free. Be sarcastic about their jail time. "
                    f"Make jokes about them probably going back soon. Keep it under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words. "
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
            
            # Send release message to general channel as embed
            # Create embed with black code box for response
            embed = discord.Embed(
                title="🔓 PRISONER RELEASED",
                description=f"{member.mention}\n",
                color=int(os.getenv('EMBED_COLOR_RELEASE', '0x00FF00'), 16)  # Green color for freedom
            )
            
            # Add original crime if available
            if mute_reason:
                embed.add_field(
                    name="Released From",
                    value=f"{mute_reason[:int(os.getenv('MUTE_REASON_MAX_LENGTH', '100'))]}",
                    inline=False
                )
            
            # Remove the AI response from embed - it will be sent as a separate message
            
            # Add prison stats with spacing
            if prisoner_stats['total_mutes'] > 0:
                embed.add_field(
                    name="Total Visits",
                    value=str(prisoner_stats['total_mutes']),
                    inline=True
                )
                # Show the duration of THIS mute session
                if current_session_duration > 0:
                    session_time = format_duration(current_session_duration)
                    embed.add_field(
                        name="Time Served",
                        value=session_time,
                        inline=True
                    )
                else:
                    # Fallback to total time if current session is 0
                    # (shouldn't happen but just in case)
                    embed.add_field(
                        name="Time Served",
                        value="< 1 minute",
                        inline=True
                    )
            
            # Set thumbnail to prisoner's avatar
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            
            # Set footer with developer credit and avatar
            developer = await self.bot.fetch_user(self.bot.developer_id)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}", icon_url=developer_avatar)
            
            # Send both the AI response text and the embed
            await general_channel.send(f"{member.mention} {response}", embed=embed)
            
            # Update presence to show prisoner release with name and duration
            asyncio.create_task(self.bot.presence_handler.show_prisoner_released(
                username=member.name,
                duration_minutes=current_session_duration
            ))
            
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
                ("Previous Offense", mute_reason[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))] if mute_reason else "Unknown"),
                ("Total Times Muted", str(prisoner_stats['total_mutes'])),
                ("Release Message", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            ], "🔓")
            
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler.handle_prisoner_release",
                critical=False,
                member=member.name,
                member_id=member.id
            )