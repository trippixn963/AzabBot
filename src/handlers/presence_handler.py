"""
Azab Discord Bot - Presence Handler
===================================

Manages dynamic Discord rich presence updates based on bot state and events.

Features:
- Active/Inactive status display
- Real-time prisoner count when active
- Special notifications for mute/unmute events
- Automatic presence updates

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
from typing import Optional, Any

from src.core.logger import logger


class PresenceHandler:
    """
    Manages Discord rich presence for the bot.
    
    Updates the bot's status based on:
    - Bot activation state (active/sleeping)
    - Current prisoner count
    - Mute/unmute events
    """
    
    def __init__(self, bot: Any) -> None:
        """
        Initialize the presence handler.
        
        Args:
            bot: The Discord bot instance
        """
        self.bot: Any = bot
        self.update_task: Optional[asyncio.Task] = None
        
    async def start_presence_loop(self) -> None:
        """Start the presence update loop."""
        # Cancel any existing task
        if self.update_task:
            self.update_task.cancel()
        
        # Start new update loop
        self.update_task = asyncio.create_task(self._presence_loop())
        logger.info("Started presence update loop")
    
    async def _presence_loop(self) -> None:
        """Main presence update loop that runs continuously."""
        while True:
            try:
                await self.update_presence()
                # Update every 30 seconds
                await asyncio.sleep(30)
            except Exception as e:
                logger.error("Presence Update", str(e)[:50])
                await asyncio.sleep(30)
    
    async def update_presence(self) -> None:
        """Update presence based on current bot state."""
        try:
            if self.bot.is_active:
                # Count prisoners
                prisoner_count: int = self._count_prisoners()
                
                # Active status - show prisoner count
                await self.bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f"{prisoner_count} prisoners"
                    )
                )
            else:
                # Inactive status - sleeping
                await self.bot.change_presence(
                    status=discord.Status.idle,
                    activity=discord.Activity(
                        type=discord.ActivityType.playing,
                        name="💤 Sleeping | /activate to wake"
                    )
                )
        except Exception as e:
            logger.error("Presence Update", str(e)[:50])
    
    async def show_prisoner_arrived(self) -> None:
        """
        Temporarily show when a new prisoner arrives.
        Shows for 5 seconds then returns to normal presence.
        """
        try:
            # Show arrival message
            await self.bot.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name="🔒 New prisoner arrived!"
                )
            )
            
            # Wait 5 seconds
            await asyncio.sleep(5)
            
            # Return to normal presence
            await self.update_presence()
            
        except Exception as e:
            logger.error("Prisoner Arrival Presence", str(e)[:50])
    
    async def show_prisoner_released(self) -> None:
        """
        Temporarily show when a prisoner is released.
        Shows for 5 seconds then returns to normal presence.
        """
        try:
            # Show release message
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.playing,
                    name="🔓 Prisoner released!"
                )
            )
            
            # Wait 5 seconds
            await asyncio.sleep(5)
            
            # Return to normal presence
            await self.update_presence()
            
        except Exception as e:
            logger.error("Prisoner Release Presence", str(e)[:50])
    
    def _count_prisoners(self) -> int:
        """
        Count the current number of prisoners (muted users).
        
        Returns:
            int: Number of users with the muted role
        """
        count: int = 0
        for guild in self.bot.guilds:
            muted_role: Optional[discord.Role] = guild.get_role(self.bot.muted_role_id)
            if muted_role:
                count += len(muted_role.members)
        return count