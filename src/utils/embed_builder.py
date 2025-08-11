"""
AzabBot - Embed Builder Utility
===================================

This module provides utilities for creating consistent, professional Discord embeds
with AzabBot branding and styling. It ensures visual consistency across all
bot responses and maintains the bot's thematic appearance.

The EmbedBuilder class provides methods for creating various types of embeds:
- Base embeds with consistent formatting
- Azab response embeds (prison-themed responses)
- Status and information embeds
- Error and warning embeds
- Prisoner report embeds
- Help and command embeds

All embeds follow a consistent design pattern with:
- Branded color scheme matching the prison theme
- Developer footer with author name
- Consistent formatting and styling
- Thematic elements appropriate for the bot's purpose
"""

from typing import List, Optional, Tuple, Union

from discord import Embed
from src import __version__


class EmbedBuilder:
    """
    Utility class for creating consistent embeds with AzabBot branding.
    
    This class provides a centralized way to create Discord embeds that maintain
    visual consistency and brand identity across all bot interactions. It includes
    predefined color schemes, formatting standards, and thematic elements.
    
    Features:
    - Consistent color scheme with prison/azab theme
    - Bot profile picture integration in author field
    - Developer footer with author name and timestamp
    - Multiple embed types for different purposes
    - Thematic styling appropriate for prison channel management
    
    The class uses class methods for easy access without instantiation,
    making it convenient to use throughout the application.
    """

    # Brand colors for consistent theming
    COLORS = {
        "primary": 0x8B0000,  # Dark red - main brand color
        "success": 0x00FF00,  # Green - successful operations
        "warning": 0xFFA500,  # Orange - warnings
        "error": 0xFF0000,  # Red - errors
        "info": 0x0000FF,  # Blue - information
        "prison": 0x4B0082,  # Indigo - prison theme
        "azab": 0x800080,  # Purple - Azab responses
    }

    # Developer information for footer
    DEVELOPER_NAME = "حَـــــنَّـــــا"
    DEVELOPER_ICON = "https://cdn.discordapp.com/embed/avatars/0.png"  # Default avatar

    @classmethod
    def create_base_embed(
        cls,
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: Union[int, str] = "primary",
        url: Optional[str] = None,
        timestamp: bool = False,  # Changed default to False - no timestamps
    ) -> Embed:
        """
        Create a base embed with consistent formatting and branding.
        
        This method creates the foundation for all other embed types,
        ensuring consistent styling, colors, and footer information.
        
        Args:
            title: Embed title text
            description: Embed description text
            color: Color name from COLORS dict or hex value
            url: URL for the title (makes title clickable)
            timestamp: Whether to add current timestamp (default: False)
            
        Returns:
            Configured Discord embed with consistent formatting
        """
        # Resolve color value from name or use direct hex value
        if isinstance(color, str):
            color_value = cls.COLORS.get(color, cls.COLORS["primary"])
        else:
            color_value = color

        # Create embed with specified parameters
        embed = Embed(title=title, description=description, color=color_value, url=url)

        # Add developer footer for branding
        embed.set_footer(
            text=f"Developed by {cls.DEVELOPER_NAME}", icon_url=cls.DEVELOPER_ICON
        )

        return embed

    @classmethod
    def create_azab_response_embed(
        cls,
        prisoner_name: str,
        response: str,
        confusion_level: Optional[int] = None,
        bot_avatar_url: Optional[str] = None,
    ) -> Embed:
        """
        Create an embed for Azab's thematic responses.
        
        This method creates specialized embeds for Azab's responses to prisoners,
        using the azab color theme and appropriate formatting for the prison context.
        
        Args:
            prisoner_name: Name of the prisoner receiving the response
            response: Azab's response text
            confusion_level: Level of confusion (1-10) for context
            bot_avatar_url: Bot's avatar URL for author field
            
        Returns:
            Configured embed for Azab response with prison theming
        """
        embed = cls.create_base_embed(
            title="🔥 Azab's Response", description=response, color="azab"
        )

        # Add author with bot avatar
        if bot_avatar_url:
            embed.set_author(name="Azab the Torturer", icon_url=bot_avatar_url)

        # Add prisoner field
        embed.add_field(name="Prisoner", value=prisoner_name, inline=True)

        # Add confusion level if provided
        if confusion_level:
            confusion_bar = "🟥" * confusion_level + "⬜" * (10 - confusion_level)
            embed.add_field(name="Confusion Level", value=confusion_bar, inline=True)

        return embed

    @classmethod
    def create_status_embed(
        cls,
        status: str,
        stats: Optional[dict] = None,
        bot_avatar_url: Optional[str] = None,
    ) -> Embed:
        """
        Create a status embed for bot activation/deactivation.

        Args:
            status: Current bot status
            stats: Optional statistics dictionary
            bot_avatar_url: Bot's avatar URL

        Returns:
            Status embed
        """
        is_active = status.lower() == "active"

        embed = cls.create_base_embed(
            title=f"{'🟢' if is_active else '🔴'} Bot Status",
            description=f"Azab is **{status}**",
            color="success" if is_active else "error",
        )

        # Add bot avatar
        if bot_avatar_url:
            embed.set_thumbnail(url=bot_avatar_url)

        # Status message removed - Mode field is no longer added

        # Add statistics if provided
        if stats:
            embed.add_field(
                name="Session Statistics",
                value=(
                    f"Prisoners Tortured: {stats.get('prisoners', 0)}\n"
                    f"Messages Processed: {stats.get('messages', 0)}\n"
                    f"Confusion Generated: {stats.get('confusion', 0)}%"
                ),
                inline=False,
            )

        return embed

    @classmethod
    def create_error_embed(
        cls,
        error_message: str,
        error_type: Optional[str] = None,
        additional_info: Optional[str] = None,
    ) -> Embed:
        """
        Create an error embed.

        Args:
            error_message: Main error message
            error_type: Type of error
            additional_info: Additional information

        Returns:
            Error embed
        """
        embed = cls.create_base_embed(
            title=f"❌ {error_type or 'Error'}",
            description=error_message,
            color="error",
        )

        if additional_info:
            embed.add_field(
                name="Additional Information", value=additional_info, inline=False
            )

        embed.add_field(
            name="Need Help?",
            value="Contact the developer or check the logs.",
            inline=False,
        )

        return embed

    @classmethod
    def create_prisoner_report_embed(
        cls, prisoner_data: dict, bot_avatar_url: Optional[str] = None
    ) -> Embed:
        """
        Create an embed for prisoner reports.

        Args:
            prisoner_data: Dictionary with prisoner information
            bot_avatar_url: Bot's avatar URL

        Returns:
            Prisoner report embed
        """
        embed = cls.create_base_embed(
            title="📋 Prisoner Report",
            description=f"Profile for **{prisoner_data.get('username', 'Unknown')}**",
            color="prison",
        )

        # Add bot avatar
        if bot_avatar_url:
            embed.set_author(name="Sednaya Prison Database", icon_url=bot_avatar_url)

        # Add prisoner information
        embed.add_field(
            name="Basic Information",
            value=(
                f"Discord ID: `{prisoner_data.get('discord_id', 'Unknown')}`\n"
                f"Status: {prisoner_data.get('status', 'Active')}\n"
                f"First Seen: {prisoner_data.get('first_seen', 'Unknown')}"
            ),
            inline=False,
        )

        # Add statistics
        embed.add_field(
            name="Session Statistics",
            value=(
                f"Total Sessions: {prisoner_data.get('total_sessions', 0)}\n"
                f"Total Messages: {prisoner_data.get('total_messages', 0)}\n"
                f"Effectiveness Score: {prisoner_data.get('effectiveness_score', 0)}%"
            ),
            inline=True,
        )

        # Add psychological profile if available
        if prisoner_data.get("psychological_profile"):
            embed.add_field(
                name="Psychological Profile",
                value=prisoner_data["psychological_profile"][:1024],
                inline=False,
            )

        # Add mute reason if available
        if prisoner_data.get("mute_reason"):
            embed.add_field(
                name="Mute Reason", value=prisoner_data["mute_reason"], inline=False
            )

        return embed

    @classmethod
    def create_help_embed(
        cls, commands: List[Tuple[str, str]], bot_avatar_url: Optional[str] = None
    ) -> Embed:
        """
        Create a help embed.

        Args:
            commands: List of (command, description) tuples
            bot_avatar_url: Bot's avatar URL

        Returns:
            Help embed
        """
        embed = cls.create_base_embed(
            title="📖 AzabBot Commands",
            description="Only the developer can use these commands.",
            color="info",
        )

        # Add bot avatar
        if bot_avatar_url:
            embed.set_thumbnail(url=bot_avatar_url)

        # Add commands
        for command, description in commands:
            embed.add_field(name=command, value=description, inline=False)

        # Add additional information
        embed.add_field(
            name="How It Works",
            value=(
                "The bot automatically responds to all messages in prison channels. "
                "No configuration needed - it detects prison channels by keywords."
            ),
            inline=False,
        )

        return embed

    @classmethod
    def create_simple_embed(
        cls, message: str, emoji: str = "📢", color: str = "primary"
    ) -> Embed:
        """
        Create a simple embed for quick messages.

        Args:
            message: Message to display
            emoji: Emoji to prepend
            color: Color name

        Returns:
            Simple embed
        """
        return cls.create_base_embed(
            description=f"{emoji} {message}", color=color, timestamp=False
        )
