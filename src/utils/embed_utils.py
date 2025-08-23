"""
Embed Utilities for AzabBot
===========================

Common utilities for creating Discord embeds with consistent styling.
"""

import discord
from typing import Optional, List, Tuple
from datetime import datetime
import pytz

def get_est_time() -> datetime:
    """Get current time in EST timezone."""
    est = pytz.timezone('US/Eastern')
    return datetime.now(est)

def create_error_embed(
    title: str = "❌ Error",
    description: str = "An error occurred",
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    thumbnail_url: Optional[str] = None
) -> discord.Embed:
    """Create a standardized error embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0xFF0000,
        timestamp=get_est_time()
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    embed.set_footer(text="Developed by حَـــــنَّـــــا")
    return embed

def create_success_embed(
    title: str = "✅ Success",
    description: str = "Operation completed successfully",
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    thumbnail_url: Optional[str] = None
) -> discord.Embed:
    """Create a standardized success embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0x00FF00,
        timestamp=get_est_time()
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    embed.set_footer(text="Developed by حَـــــنَّـــــا")
    return embed

def create_warning_embed(
    title: str = "⚠️ Warning",
    description: str = "Warning",
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    thumbnail_url: Optional[str] = None
) -> discord.Embed:
    """Create a standardized warning embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0xFFFF00,
        timestamp=get_est_time()
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    embed.set_footer(text="Developed by حَـــــنَّـــــا")
    return embed

def create_info_embed(
    title: str,
    description: str,
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    thumbnail_url: Optional[str] = None,
    color: int = 0x3498DB
) -> discord.Embed:
    """Create a standardized info embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=get_est_time()
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    embed.set_footer(text="Developed by حَـــــنَّـــــا")
    return embed