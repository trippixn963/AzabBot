"""
AzabBot - Slash Commands Module
==================================

This module defines all slash commands for the AzabBot as standalone functions
that can be dynamically added to the Discord command tree.

The commands in this module are primarily developer/admin commands that provide
status information and control over the bot's operation. All commands include
proper permission checks to ensure only authorized users can execute them.

Available Commands:
- /activate: Developer command to check bot status
- /deactivate: Developer command that demonstrates bot permanence
- /ignore: Manage ignored users (add/remove from ignore list)
"""

import discord
from discord import app_commands
from datetime import timezone
import pytz

from src import __version__
from src.utils.embed_builder import EmbedBuilder



def create_activate_command(bot):
    """
    Create an activate command that activates the bot.
    
    This command is restricted to authorized users (developer and specific moderators)
    and activates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The activate command function that can be added to the command tree
    """

    @app_commands.command(
        name="activate", description="Enable bot responses (Authorized users only)"
    )
    async def activate(interaction: discord.Interaction):
        """
        Handle the activate command interaction.
        
        This command activates the bot's monitoring and response system.
        Only authorized users (developer and specific moderators) can use this command.
        """
        try:
            # List of authorized user IDs (developer + moderators from config)
            authorized_users = [bot.developer_id]
            # Add moderator IDs from config if available
            moderator_ids = bot.config.get("MODERATOR_IDS", [])
            if moderator_ids:
                authorized_users.extend(moderator_ids)
            
            # Verify the user is authorized
            if interaction.user.id not in authorized_users:
                embed = discord.Embed(
                    title="❌ Permission Denied",
                    description="Only authorized users can use this command.",
                    color=0xFF0000,
                    
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Respond to interaction immediately to avoid timeout
            embed = discord.Embed(
                title="✅ Bot Activated",
                description="AzabBot is now active and will respond to prisoners!",
                color=0x00FF00,
                
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            embed.add_field(name="Status", value="🟢 Active", inline=True)
            embed.add_field(name="Responses", value="💬 Enabled", inline=True)
            embed.add_field(name="Prisoners", value=f"{len(bot.current_prisoners)}", inline=True)
            embed.set_footer(
                text="Developed by حَـــــنَّـــــا",
                icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Now activate the bot and do background tasks
            bot.is_active = True
            
            # Use enhanced tree logging for activation
            from src.utils.tree_log import log_enhanced_tree_section_global as log_enhanced_tree_section, log_status
            import time
            
            start_time = time.perf_counter()
            log_status("Bot activated by developer command", emoji="✅")
            
            # Update bot presence to show active status
            activity = discord.Activity(
                type=discord.ActivityType.watching, name="⛓ Sednaya"
            )
            await bot.change_presence(activity=activity, status=discord.Status.online)
            
            # Start background tasks asynchronously
            import asyncio
            async def activate_tasks():
                activation_start = time.perf_counter()
                
                # Scan for current prisoners if not already done
                await bot._scan_for_prisoners()
                
                # Process only the MOST RECENT prisoner message
                await bot._process_recent_prisoner_messages()
                
                # Start presence rotation task if not already running
                if bot.presence_rotation_task:
                    bot.presence_rotation_task.cancel()
                bot.presence_rotation_task = bot.loop.create_task(bot._rotate_presence())
                
                # Calculate performance metrics
                activation_time = (time.perf_counter() - activation_start) * 1000
                
                # Create enhanced tree log for activation sequence
                activation_items = [
                    ("status", "Starting activation sequence"),
                    ("presence", "Updated to watching ⛓ Sednaya"),
                    ("background_tasks", "Initializing...")
                ]
                
                performance_metrics = {
                    "activation_time_ms": round(activation_time, 2),
                    "prisoners_found": len(bot.current_prisoners),
                    "services_initialized": 3
                }
                
                context_data = {
                    "user_id": str(interaction.user.id),
                    "user_name": interaction.user.display_name,
                    "user_username": interaction.user.name,
                    "guild_id": str(interaction.guild_id) if interaction.guild_id else "None",
                    "channel_id": str(interaction.channel_id) if interaction.channel_id else "None",
                    "guild_count": len(bot.guilds),
                    "channel_count": sum(len(guild.channels) for guild in bot.guilds),
                    "command_used": "activate",
                    "authorized": "yes"
                }
                
                log_enhanced_tree_section(
                    "Bot Activation",
                    activation_items,
                    performance_metrics=performance_metrics,
                    context_data=context_data,
                    emoji="🚀"
                )
                
                # Log completion
                log_status("Activation sequence completed", emoji="✅")
            
            # Run activation tasks in background
            bot.loop.create_task(activate_tasks())
        
        except Exception as e:
            bot.logger.log_error("Error in activate command", exception=e)
            embed = discord.Embed(
                title="❌ Activation Failed",
                description=f"An error occurred: {str(e)}",
                color=0xFF0000
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

    return activate


def create_deactivate_command(bot):
    """
    Create a deactivate command that deactivates the bot.
    
    This command is restricted to authorized users (developer and specific moderators)
    and deactivates the bot's monitoring.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The deactivate command function that can be added to the command tree
    """

    @app_commands.command(
        name="deactivate", description="Disable bot responses (Authorized users only)"
    )
    async def deactivate(interaction: discord.Interaction):
        """
        Handle the deactivate command interaction.
        
        This command deactivates the bot's monitoring and response system.
        Only authorized users (developer and specific moderators) can use this command.
        """
        try:
            # List of authorized user IDs (developer + moderators from config)
            authorized_users = [bot.developer_id]
            # Add moderator IDs from config if available
            moderator_ids = bot.config.get("MODERATOR_IDS", [])
            if moderator_ids:
                authorized_users.extend(moderator_ids)
            
            # Verify the user is authorized
            if interaction.user.id not in authorized_users:
                embed = discord.Embed(
                    title="❌ Permission Denied",
                    description="Only authorized users can use this command.",
                    color=0xFF0000,
                    
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Deactivate the bot
            bot.is_active = False
            
            # Use enhanced tree logging for deactivation
            from src.utils.tree_log import log_enhanced_tree_section_global as log_enhanced_tree_section, log_status
            import time
            
            deactivation_start = time.perf_counter()
            
            # Create enhanced tree log for deactivation
            deactivation_items = [
                ("status", "Bot deactivated"),
                ("presence", "Updated to watching 💤 Inactive"),
                ("background_tasks", "Stopping...")
            ]
            
            performance_metrics = {
                "deactivation_time_ms": 0,  # Will be calculated after operations
                "tasks_stopped": 1,
                "services_deactivated": 1
            }
            
            context_data = {
                "user_id": str(interaction.user.id),
                "user_name": interaction.user.display_name,
                "user_username": interaction.user.name,
                "guild_id": str(interaction.guild_id) if interaction.guild_id else "None",
                "channel_id": str(interaction.channel_id) if interaction.channel_id else "None",
                "command_used": "deactivate",
                "authorized": "yes"
            }
            
            log_enhanced_tree_section(
                "Bot Deactivation",
                deactivation_items,
                performance_metrics=performance_metrics,
                context_data=context_data,
                emoji="🔴"
            )
            
            log_status("Bot deactivated by developer command", emoji="🔴")
            
            # Update bot presence to show inactive status
            activity = discord.Activity(
                type=discord.ActivityType.watching, name="💤 Inactive"
            )
            await bot.change_presence(activity=activity, status=discord.Status.idle)
            
            # Stop presence rotation task
            if bot.presence_rotation_task:
                bot.presence_rotation_task.cancel()
                bot.presence_rotation_task = None
            
            # Create deactivation embed
            embed = discord.Embed(
                title="🔴 Bot Deactivated",
                description="AzabBot is now inactive. Still learning but not responding.",
                color=0xFF0000,
                
            )
            if bot.user and bot.user.avatar:
                embed.set_thumbnail(url=bot.user.avatar.url)
            embed.add_field(name="Status", value="⭕ Inactive", inline=True)
            embed.add_field(name="Responses", value="🔇 Disabled", inline=True)
            embed.add_field(name="Commands", value="✅ Still Available", inline=True)
            embed.set_footer(
                text="Developed by حَـــــنَّـــــا",
                icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            bot.logger.log_error("Error in deactivate command", exception=e)
            embed = discord.Embed(
                title="❌ Deactivation Failed",
                description=f"An error occurred: {str(e)}",
                color=0xFF0000
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

    return deactivate


def create_ignore_command(bot):
    """
    Create an ignore command that manages the bot's ignore list.
    
    This command allows authorized users to add or remove users from the ignore list,
    preventing the bot from responding to messages from ignored users.
    
    Args:
        bot: The AzabBot instance that contains the developer_id
        
    Returns:
        The ignore command function that can be added to the command tree
    """

    async def ignored_users_autocomplete(
        interaction: discord.Interaction, 
        current: str
    ) -> list[app_commands.Choice[str]]:
        """
        Autocomplete function for ignored users when removing from ignore list.
        
        Args:
            interaction: The Discord interaction
            current: The current input string
            
        Returns:
            List of choices for autocomplete
        """
        # Only show autocomplete if the action is "remove"
        # We need to check the current interaction data
        try:
            # Get the action from the current interaction
            action_data = interaction.data.get("options", [])
            action_value = None
            for option in action_data:
                if option.get("name") == "action":
                    action_value = option.get("value")
                    break
            
            # Only show autocomplete for "remove" action
            if action_value != "remove":
                return []
        except:
            # If we can't determine the action, don't show autocomplete
            return []
        
        # Initialize ignore list if it doesn't exist
        if not hasattr(bot, 'ignored_users'):
            bot.ignored_users = set()
        
        choices = []
        
        # Get all ignored users and their names
        for user_id in bot.ignored_users:
            try:
                user = await bot.fetch_user(user_id)
                username = user.display_name or user.name
                # Create choice with both username and ID
                choice_text = f"{username} ({user_id})"
                choice_value = str(user_id)
                
                # Filter by current input (case insensitive)
                if current.lower() in choice_text.lower():
                    choices.append(app_commands.Choice(name=choice_text, value=choice_value))
            except:
                # If we can't fetch user, just show the ID
                choice_text = f"Unknown User ({user_id})"
                choice_value = str(user_id)
                
                if current.lower() in choice_text.lower():
                    choices.append(app_commands.Choice(name=choice_text, value=choice_value))
        
        # Limit to 25 choices (Discord limit)
        return choices[:25]

    @app_commands.command(
        name="ignore", 
        description="Manage ignored users - add or remove users from ignore list"
    )
    @app_commands.describe(
        action="Whether to add or remove the user from ignore list",
        user_id="The Discord user ID to ignore/unignore (autocomplete available for remove)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add to ignore list", value="add"),
        app_commands.Choice(name="Remove from ignore list", value="remove"),
        app_commands.Choice(name="List ignored users", value="list")
    ])
    async def ignore(
        interaction: discord.Interaction, 
        action: app_commands.Choice[str], 
        user_id: str = None
    ):
        """
        Handle the ignore command interaction.
        
        This command manages the bot's ignore list, allowing authorized users to
        add or remove users from the ignore list to prevent bot responses.
        """
        try:
            # List of authorized user IDs (developer + moderators from config)
            authorized_users = [bot.developer_id]
            # Add moderator IDs from config if available
            moderator_ids = bot.config.get("MODERATOR_IDS", [])
            if moderator_ids:
                authorized_users.extend(moderator_ids)
            
            # Verify the user is authorized
            if interaction.user.id not in authorized_users:
                embed = discord.Embed(
                    title="❌ Permission Denied",
                    description="Only authorized users can manage the ignore list.",
                    color=0xFF0000,
                    
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Initialize ignore list if it doesn't exist
            if not hasattr(bot, 'ignored_users'):
                bot.ignored_users = set()
            
            # Handle different actions
            if action.value == "add":
                if not user_id:
                    embed = discord.Embed(
                        title="❌ Missing User ID",
                        description="Please provide a user ID to add to the ignore list.",
                        color=0xFF0000,
                        
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                try:
                    user_id_int = int(user_id)
                    bot.ignored_users.add(user_id_int)
                    
                    # Try to get user info for display
                    try:
                        user = await bot.fetch_user(user_id_int)
                        username = user.display_name or user.name
                    except:
                        username = f"User {user_id}"
                    
                    embed = discord.Embed(
                        title="✅ User Added to Ignore List",
                        description=f"**{username}** (`{user_id}`) has been added to the ignore list.\nThe bot will no longer respond to messages from this user.",
                        color=0x00FF00
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    embed.add_field(name="Total Ignored", value=f"{len(bot.ignored_users)}", inline=True)
                    embed.set_footer(
                        text="Developed by حَـــــنَّـــــا",
                        icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png"
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                    # Use enhanced tree logging for ignore command
                    from src.utils.tree_log import log_enhanced_tree_section_global as log_enhanced_tree_section, log_status
                    
                    ignore_items = [
                        ("action", "add user to ignore list"),
                        ("user_id", user_id),
                        ("username", username),
                        ("total_ignored", str(len(bot.ignored_users)))
                    ]
                    
                    context_data = {
                        "user_id": str(interaction.user.id),
                        "user_name": interaction.user.display_name,
                        "user_username": interaction.user.name,
                        "guild_id": str(interaction.guild_id) if interaction.guild_id else "None",
                        "channel_id": str(interaction.channel_id) if interaction.channel_id else "None",
                        "command_used": "ignore",
                        "subcommand": "add",
                        "target_user_id": user_id,
                        "target_username": username,
                        "authorized": "yes"
                    }
                    
                    log_enhanced_tree_section(
                        "Ignore List Management",
                        ignore_items,
                        context_data=context_data,
                        emoji="🚫"
                    )
                    
                    log_status(f"User {username} ({user_id}) added to ignore list", emoji="🚫")
                    
                except ValueError:
                    embed = discord.Embed(
                        title="❌ Invalid User ID",
                        description="Please provide a valid numeric user ID.",
                        color=0xFF0000,
                        
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                    
            elif action.value == "remove":
                if not user_id:
                    embed = discord.Embed(
                        title="❌ Missing User ID",
                        description="Please provide a user ID to remove from the ignore list.",
                        color=0xFF0000,
                        
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                try:
                    user_id_int = int(user_id)
                    if user_id_int in bot.ignored_users:
                        bot.ignored_users.remove(user_id_int)
                        
                        # Try to get user info for display
                        try:
                            user = await bot.fetch_user(user_id_int)
                            username = user.display_name or user.name
                        except:
                            username = f"User {user_id}"
                        
                        embed = discord.Embed(
                            title="✅ User Removed from Ignore List",
                            description=f"**{username}** (`{user_id}`) has been removed from the ignore list.\nThe bot will now respond to messages from this user.",
                            color=0x00FF00,
                            
                        )
                        if bot.user and bot.user.avatar:
                            embed.set_thumbnail(url=bot.user.avatar.url)
                        embed.add_field(name="Total Ignored", value=f"{len(bot.ignored_users)}", inline=True)
                        embed.set_footer(text="Developed by حَـــــنَّـــــا", icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png")
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        
                        # Use enhanced tree logging for ignore remove command
                        ignore_items = [
                            ("action", "remove user from ignore list"),
                            ("user_id", user_id),
                            ("username", username),
                            ("total_ignored", str(len(bot.ignored_users)))
                        ]
                        
                        context_data = {
                            "user_id": str(interaction.user.id),
                            "user_name": interaction.user.display_name,
                            "user_username": interaction.user.name,
                            "guild_id": str(interaction.guild_id) if interaction.guild_id else "None",
                            "channel_id": str(interaction.channel_id) if interaction.channel_id else "None",
                            "command_used": "ignore",
                            "subcommand": "remove",
                            "target_user_id": user_id,
                            "target_username": username,
                            "authorized": "yes"
                        }
                        
                        log_enhanced_tree_section(
                            "Ignore List Management",
                            ignore_items,
                            context_data=context_data,
                            emoji="✅"
                        )
                        
                        log_status(f"User {username} ({user_id}) removed from ignore list", emoji="✅")
                    else:
                        embed = discord.Embed(
                            title="ℹ️ User Not in Ignore List",
                            description=f"User ID `{user_id}` is not currently in the ignore list.",
                            color=0xFFA500,
                            
                        )
                        if bot.user and bot.user.avatar:
                            embed.set_thumbnail(url=bot.user.avatar.url)
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        
                except ValueError:
                    embed = discord.Embed(
                        title="❌ Invalid User ID",
                        description="Please provide a valid numeric user ID.",
                        color=0xFF0000,
                        
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                    
            elif action.value == "list":
                if not bot.ignored_users:
                    embed = discord.Embed(
                        title="📋 Ignore List",
                        description="No users are currently in the ignore list.",
                        color=0x00FF00,
                        
                    )
                    if bot.user and bot.user.avatar:
                        embed.set_thumbnail(url=bot.user.avatar.url)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Create list of ignored users with their names
                ignored_list = []
                for ignored_id in bot.ignored_users:
                    try:
                        user = await bot.fetch_user(ignored_id)
                        username = user.display_name or user.name
                        ignored_list.append(f"• **{username}** (`{ignored_id}`)")
                    except:
                        ignored_list.append(f"• Unknown User (`{ignored_id}`)")
                
                embed = discord.Embed(
                    title="📋 Ignore List",
                    description="Users currently in the ignore list:\n\n" + "\n".join(ignored_list),
                    color=0x00FF00,
                    
                )
                if bot.user and bot.user.avatar:
                    embed.set_thumbnail(url=bot.user.avatar.url)
                embed.add_field(name="Total Ignored", value=f"{len(bot.ignored_users)}", inline=True)
                embed.set_footer(text="Developed by حَـــــنَّـــــا", icon_url="https://cdn.discordapp.com/avatars/259725211664908288/default.png")
                await interaction.response.send_message(embed=embed, ephemeral=True)
        
        except Exception as e:
            bot.logger.log_error("Error in ignore command", exception=e)
            embed = discord.Embed(
                title="❌ Command Failed",
                description=f"An error occurred: {str(e)}",
                color=0xFF0000,
                
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

    # Add autocomplete to the user_id parameter
    ignore.autocomplete("user_id")(ignored_users_autocomplete)

    return ignore


