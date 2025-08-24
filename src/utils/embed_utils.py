"""
Embed Utilities for AzabBot
===========================

Common utilities for creating Discord embeds with consistent styling.
"""

import discord
from typing import Optional, List, Tuple
from datetime import datetime

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
        color=0xFF0000
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    # Add developer footer with profile picture
    embed.set_footer(
        text="Developed by حَـــــنَّـــــا",
        icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
    )
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
        color=0x00FF00
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    # Add developer footer with profile picture
    embed.set_footer(
        text="Developed by حَـــــنَّـــــا",
        icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
    )
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
        color=0xFFFF00
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    # Add developer footer with profile picture
    embed.set_footer(
        text="Developed by حَـــــنَّـــــا",
        icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
    )
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
        color=color
    )
    
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    # Add developer footer with profile picture
    embed.set_footer(
        text="Developed by حَـــــنَّـــــا",
        icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
    )
    return embed