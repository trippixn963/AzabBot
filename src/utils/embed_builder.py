"""
Professional Discord Embed Builder for AzabBot
==============================================

This module provides a comprehensive, production-grade Discord embed creation system
with consistent branding, thematic styling, and professional presentation for all
bot interactions. It implements the Builder pattern for fluent embed construction
and ensures visual consistency across the entire application.

DESIGN PATTERNS IMPLEMENTED:
1. Builder Pattern: Fluent interface for embed construction
2. Factory Pattern: Pre-configured embed templates for different use cases
3. Strategy Pattern: Different embed types with specialized formatting
4. Template Pattern: Consistent styling and branding across all embeds
5. Singleton Pattern: Global color scheme and branding configuration

EMBED TYPES AND USE CASES:
1. Base Embeds: Foundation for all other embed types
2. Azab Response Embeds: Thematic responses with prison context
3. Status Embeds: Bot status and operational information
4. Error Embeds: Error reporting with helpful context
5. Prisoner Report Embeds: Detailed user information displays
6. Help Embeds: Command documentation and usage guides
7. Simple Embeds: Quick messages with minimal formatting

BRANDING AND THEMING:
- Consistent color scheme matching prison/azab theme
- Developer footer with author attribution
- Professional formatting and styling
- Thematic elements appropriate for bot's purpose
- Visual hierarchy for information organization

COLOR SCHEME:
- Primary: Dark red (#8B0000) - Main brand color
- Success: Green (#00FF00) - Successful operations
- Warning: Orange (#FFA500) - Warnings and alerts
- Error: Red (#FF0000) - Errors and failures
- Info: Blue (#0000FF) - Information and help
- Prison: Indigo (#4B0082) - Prison theme elements
- Azab: Purple (#800080) - Azab-specific responses and interactions

USAGE EXAMPLES:

1. Basic Embed Creation:
   ```python
   embed = EmbedBuilder.create_base_embed(
       title="Welcome to AzabBot",
       description="Your prison experience begins now.",
       color="primary"
   )
   ```

2. Azab Response Embed:
   ```python
   embed = EmbedBuilder.create_azab_response_embed(
       prisoner_name="John Doe",
       response="You have been sentenced to eternal confusion.",
       confusion_level=8,
       bot_avatar_url="https://example.com/avatar.png"
   )
   ```

3. Status Embed:
   ```python
   embed = EmbedBuilder.create_status_embed(
       status="Active",
       stats={"prisoners": 150, "messages": 1200},
       bot_avatar_url="https://example.com/avatar.png"
   )
   ```

4. Error Embed:
   ```python
   embed = EmbedBuilder.create_error_embed(
       error_message="Failed to process request",
       error_type="ValidationError",
       additional_info="Please check your input format"
   )
   ```

5. Prisoner Report Embed:
   ```python
   prisoner_data = {
       "username": "John Doe",
       "discord_id": "123456789",
       "status": "Active",
       "total_sessions": 5,
       "effectiveness_score": 85
   }
   embed = EmbedBuilder.create_prisoner_report_embed(
       prisoner_data,
       bot_avatar_url="https://example.com/avatar.png"
   )
   ```

PERFORMANCE CHARACTERISTICS:
- O(1) embed creation for all types
- Minimal memory overhead
- Efficient color resolution
- Fast field addition and formatting

VISUAL CONSISTENCY:
- Uniform spacing and formatting
- Consistent color usage
- Professional typography
- Thematic emoji integration
- Proper field organization

ACCESSIBILITY FEATURES:
- High contrast color combinations
- Clear visual hierarchy
- Descriptive field names
- Consistent formatting patterns
- Readable text sizing

This implementation follows Discord embed best practices and is designed for
professional, production-ready bot applications requiring consistent branding
and user experience.
"""

from typing import List, Optional, Tuple, Union

from discord import Embed
from src import __version__


class EmbedBuilder:
    """
    Professional Discord embed builder with comprehensive theming and branding.
    
    This class provides a centralized, factory-based approach to creating
    Discord embeds that maintain visual consistency and brand identity across
    all bot interactions. It implements the Builder pattern for fluent
    embed construction and ensures professional presentation.
    
    Key Features:
        - Consistent color scheme with prison/azab theme
        - Professional formatting and styling
        - Multiple embed types for different use cases
        - Thematic elements appropriate for prison channel management
        - Developer attribution and branding
        - Visual hierarchy for information organization
    
    Design Principles:
        - Consistency: All embeds follow the same design patterns
        - Clarity: Information is organized for easy reading
        - Branding: Consistent visual identity across all interactions
        - Accessibility: High contrast and clear typography
        - Performance: Efficient embed creation with minimal overhead
    
    The class uses class methods for easy access without instantiation,
    making it convenient to use throughout the application while maintaining
    a clean, professional API.
    """

    # Brand colors for consistent theming across all embeds
    COLORS = {
        "primary": 0x8B0000,  # Dark red - main brand color for general use
        "success": 0x00FF00,  # Green - successful operations and positive feedback
        "warning": 0xFFA500,  # Orange - warnings and cautionary messages
        "error": 0xFF0000,  # Red - errors and failure states
        "info": 0x0000FF,  # Blue - information and help content
        "prison": 0x4B0082,  # Indigo - prison theme elements and context
        "azab": 0x800080,  # Purple - Azab-specific responses and interactions
    }

    # Developer information for consistent footer branding
    DEVELOPER_NAME = "حَـــــنَّـــــا"  # Arabic developer name for authenticity
    DEVELOPER_ICON = "https://cdn.discordapp.com/embed/avatars/0.png"  # Default avatar fallback

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
        Create a base embed with consistent formatting and branding foundation.
        
        This method serves as the foundation for all other embed types,
        ensuring consistent styling, colors, footer information, and
        professional presentation across the entire application.
        
        Args:
            title: Embed title text. Should be concise and descriptive.
                   Will be displayed prominently at the top of the embed.
            
            description: Embed description text. Supports Discord markdown
                        formatting. Should provide context or main content.
            
            color: Color for the embed border. Can be a color name from
                   COLORS dict or a direct hex value. Defaults to primary
                   brand color for consistency.
            
            url: URL for the title (makes title clickable). Useful for
                 linking to external resources or documentation.
            
            timestamp: Whether to add current timestamp. Defaults to False
                       for cleaner appearance without temporal context.
            
        Returns:
            Embed: Configured Discord embed with consistent formatting,
                   branding, and professional styling.
            
        Example:
            ```python
            # Basic embed with title and description
            embed = EmbedBuilder.create_base_embed(
                title="Welcome to AzabBot",
                description="Your prison experience begins now.",
                color="primary"
            )
            
            # Embed with clickable title
            embed = EmbedBuilder.create_base_embed(
                title="Documentation",
                description="Click the title to view docs",
                url="https://docs.example.com",
                color="info"
            )
            ```
        
        Design Features:
            - Consistent color resolution from name or hex value
            - Professional footer with developer attribution
            - Clean, readable formatting
            - Brand-consistent styling
        """
        # Resolve color value from name or use direct hex value
        if isinstance(color, str):
            color_value = cls.COLORS.get(color, cls.COLORS["primary"])
        else:
            color_value = color

        # Create embed with specified parameters
        embed = Embed(title=title, description=description, color=color_value, url=url)

        # Add developer footer for consistent branding
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
        Create a specialized embed for Azab's thematic responses to prisoners.
        
        This method creates embeds specifically designed for Azab's responses,
        using the azab color theme and appropriate formatting for the prison
        context. It includes prisoner information and optional confusion metrics.
        
        Args:
            prisoner_name: Name of the prisoner receiving the response.
                          Should be the Discord username or display name.
            
            response: Azab's response text. Supports Discord markdown formatting
                     and should be thematic to the prison context.
            
            confusion_level: Level of confusion (1-10) for visual representation.
                            Creates a visual bar showing confusion intensity.
                            None for no confusion display.
            
            bot_avatar_url: Bot's avatar URL for author field. Adds visual
                           identity and professionalism to the embed.
            
        Returns:
            Embed: Configured embed for Azab response with prison theming,
                   prisoner information, and optional confusion visualization.
            
        Example:
            ```python
            embed = EmbedBuilder.create_azab_response_embed(
                prisoner_name="John Doe",
                response="You have been sentenced to eternal confusion.",
                confusion_level=8,
                bot_avatar_url="https://example.com/avatar.png"
            )
            ```
        
        Visual Features:
            - Azab color theme (purple) for thematic consistency
            - Prisoner name field for context
            - Visual confusion bar using emoji indicators
            - Bot avatar in author field for identity
            - Professional formatting and spacing
        """
        embed = cls.create_base_embed(
            title="🔥 Azab's Response", description=response, color="azab"
        )

        # Add author with bot avatar for visual identity
        if bot_avatar_url:
            embed.set_author(name="Azab the Torturer", icon_url=bot_avatar_url)

        # Add prisoner field for context
        embed.add_field(name="Prisoner", value=prisoner_name, inline=True)

        # Add confusion level visualization if provided
        if confusion_level:
            # Create visual bar using emoji indicators
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
        Create a status embed for bot activation/deactivation and operational information.
        
        This method creates embeds for displaying bot status, including operational
        state, statistics, and performance metrics. It uses color coding to indicate
        status and provides comprehensive operational information.
        
        Args:
            status: Current bot status. Should be descriptive (e.g., "Active", "Inactive").
                    Used for color coding and status indication.
            
            stats: Optional statistics dictionary containing operational metrics.
                   Should include keys like 'prisoners', 'messages', 'confusion'.
                   None for no statistics display.
            
            bot_avatar_url: Bot's avatar URL for thumbnail. Adds visual identity
                           and professionalism to the status display.
            
        Returns:
            Embed: Configured status embed with color-coded status indication,
                   optional statistics, and professional formatting.
            
        Example:
            ```python
            embed = EmbedBuilder.create_status_embed(
                status="Active",
                stats={
                    "prisoners": 150,
                    "messages": 1200,
                    "confusion": 75
                },
                bot_avatar_url="https://example.com/avatar.png"
            )
            ```
        
        Status Features:
            - Color-coded status indication (green for active, red for inactive)
            - Status emoji for visual clarity
            - Optional statistics display
            - Bot avatar thumbnail
            - Professional formatting and organization
        """
        is_active = status.lower() == "active"

        embed = cls.create_base_embed(
            title=f"{'🟢' if is_active else '🔴'} Bot Status",
            description=f"Azab is **{status}**",
            color="success" if is_active else "error",
        )

        # Add bot avatar as thumbnail for visual identity
        if bot_avatar_url:
            embed.set_thumbnail(url=bot_avatar_url)

        # Add statistics if provided for operational transparency
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
        Create a professional error embed for error reporting and debugging.
        
        This method creates embeds specifically designed for error reporting,
        providing clear error information, context, and helpful guidance for
        resolution. It uses error color coding and structured information display.
        
        Args:
            error_message: Main error message. Should be clear and descriptive
                          of what went wrong. Supports Discord markdown formatting.
            
            error_type: Type of error for categorization. Used in title and
                       for error classification. None for generic error display.
            
            additional_info: Additional information or context for the error.
                            Useful for debugging or providing resolution steps.
                            None for no additional information.
            
        Returns:
            Embed: Configured error embed with clear error presentation,
                   helpful context, and professional error reporting format.
            
        Example:
            ```python
            embed = EmbedBuilder.create_error_embed(
                error_message="Failed to process user request",
                error_type="ValidationError",
                additional_info="Please check your input format and try again."
            )
            ```
        
        Error Features:
            - Error color coding (red) for immediate recognition
            - Clear error type categorization
            - Structured error information display
            - Helpful guidance for resolution
            - Professional error reporting format
        """
        embed = cls.create_base_embed(
            title=f"❌ {error_type or 'Error'}",
            description=error_message,
            color="error",
        )

        # Add additional information if provided
        if additional_info:
            embed.add_field(
                name="Additional Information", value=additional_info, inline=False
            )

        # Add help guidance for user support
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
        Create a comprehensive embed for detailed prisoner reports and user information.
        
        This method creates embeds for displaying detailed prisoner information,
        including basic data, statistics, psychological profiles, and operational
        metrics. It provides a complete view of prisoner status and history.
        
        Args:
            prisoner_data: Dictionary containing comprehensive prisoner information.
                          Should include keys like 'username', 'discord_id', 'status',
                          'total_sessions', 'total_messages', 'effectiveness_score',
                          'psychological_profile', 'mute_reason'.
            
            bot_avatar_url: Bot's avatar URL for author field. Adds visual identity
                           and professionalism to the report display.
            
        Returns:
            Embed: Configured prisoner report embed with comprehensive information
                   display, organized fields, and professional presentation.
            
        Example:
            ```python
            prisoner_data = {
                "username": "John Doe",
                "discord_id": "123456789",
                "status": "Active",
                "first_seen": "2024-01-15",
                "total_sessions": 5,
                "total_messages": 150,
                "effectiveness_score": 85,
                "psychological_profile": "Shows signs of confusion...",
                "mute_reason": "Excessive complaining"
            }
            embed = EmbedBuilder.create_prisoner_report_embed(
                prisoner_data,
                bot_avatar_url="https://example.com/avatar.png"
            )
            ```
        
        Report Features:
            - Comprehensive prisoner information display
            - Organized field structure for readability
            - Statistics and metrics presentation
            - Optional psychological profile
            - Professional report formatting
            - Visual hierarchy for information organization
        """
        embed = cls.create_base_embed(
            title="📋 Prisoner Report",
            description=f"Profile for **{prisoner_data.get('username', 'Unknown')}**",
            color="prison",
        )

        # Add bot avatar for visual identity
        if bot_avatar_url:
            embed.set_author(name="Sednaya Prison Database", icon_url=bot_avatar_url)

        # Add basic prisoner information
        embed.add_field(
            name="Basic Information",
            value=(
                f"Discord ID: `{prisoner_data.get('discord_id', 'Unknown')}`\n"
                f"Status: {prisoner_data.get('status', 'Active')}\n"
                f"First Seen: {prisoner_data.get('first_seen', 'Unknown')}"
            ),
            inline=False,
        )

        # Add operational statistics
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
                value=prisoner_data["psychological_profile"][:1024],  # Discord field limit
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
        Create a help embed for command documentation and usage guides.
        
        This method creates embeds for displaying command help information,
        including command names, descriptions, and usage guidance. It provides
        clear documentation for bot functionality and user interaction.
        
        Args:
            commands: List of (command, description) tuples containing command
                     information. Each tuple should have command name and
                     clear description of functionality.
            
            bot_avatar_url: Bot's avatar URL for thumbnail. Adds visual identity
                           and professionalism to the help display.
            
        Returns:
            Embed: Configured help embed with command documentation,
                   usage guidance, and professional formatting.
            
        Example:
            ```python
            commands = [
                ("!status", "Check bot status and statistics"),
                ("!report <user>", "Generate prisoner report for user"),
                ("!help", "Show this help message")
            ]
            embed = EmbedBuilder.create_help_embed(
                commands,
                bot_avatar_url="https://example.com/avatar.png"
            )
            ```
        
        Help Features:
            - Clear command documentation
            - Organized command listing
            - Usage guidance and context
            - Professional formatting
            - Visual hierarchy for readability
        """
        embed = cls.create_base_embed(
            title="📖 AzabBot Commands",
            description="Only the developer can use these commands.",
            color="info",
        )

        # Add bot avatar for visual identity
        if bot_avatar_url:
            embed.set_thumbnail(url=bot_avatar_url)

        # Add command documentation
        for command, description in commands:
            embed.add_field(name=command, value=description, inline=False)

        # Add usage guidance
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
        Create a simple embed for quick messages with minimal formatting.
        
        This method creates streamlined embeds for simple messages that don't
        require complex formatting or multiple fields. It provides a clean,
        efficient way to display basic information with consistent styling.
        
        Args:
            message: Message text to display. Supports Discord markdown formatting
                    and should be concise and clear.
            
            emoji: Emoji to prepend to the message for visual context.
                   Should be relevant to the message content.
            
            color: Color name from COLORS dict for embed theming.
                   Defaults to primary brand color for consistency.
            
        Returns:
            Embed: Configured simple embed with message, emoji, and consistent
                   styling for quick, clean information display.
            
        Example:
            ```python
            embed = EmbedBuilder.create_simple_embed(
                message="System maintenance completed successfully.",
                emoji="✅",
                color="success"
            )
            ```
        
        Simple Features:
            - Clean, minimal formatting
            - Emoji for visual context
            - Consistent color theming
            - Professional presentation
            - Efficient for quick messages
        """
        return cls.create_base_embed(
            description=f"{emoji} {message}", color=color, timestamp=False
        )
