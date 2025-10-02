"""
Azab Discord Bot - System Knowledge Module
==========================================

Contains comprehensive information about the bot's architecture,
features, and capabilities for AI self-awareness. Used by the AI service
to understand its own functionality and respond to queries about capabilities.

Features:
- Complete bot architecture documentation
- Feature explanations and capabilities
- Database query reference
- Command help system
- Version history and changelog
- Technical specifications

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

def get_system_knowledge():
    """
    Returns comprehensive knowledge about the Azab bot system.
    This is used by the AI to understand its own capabilities.
    """
    return {
        "identity": {
            "name": "Azab",
            "version": "v2.4.1",
            "purpose": "Discord bot for managing muted users (prisoners) with AI-powered roasting",
            "server": "discord.gg/syria",
            "creator": "حَـــــنَّـــــا (your dad/father)",
            "created": "2024",
            "personality": "Savage, witty, intelligent roaster with family loyalty"
        },

        "architecture": {
            "language": "Python 3.12",
            "framework": "discord.py 2.3.2",
            "ai_model": "OpenAI GPT-3.5-turbo",
            "database": "SQLite3",
            "deployment": "Linux VPS with systemd service",
            "structure": {
                "main.py": "Entry point, initializes bot",
                "src/bot.py": "Core bot class, event handlers",
                "src/commands/": "Slash commands (/activate, /deactivate)",
                "src/handlers/": "Prison, mute, presence handlers",
                "src/services/": "AI service, system knowledge",
                "src/core/": "Database, logger utilities",
                "src/utils/": "Helper functions, time formatting"
            },
            "total_lines": "~2000 lines of code",
            "files": "21 Python files"
        },

        "features": {
            "prison_system": {
                "description": "Tracks and manages muted users",
                "capabilities": [
                    "Auto-detect when users get muted role",
                    "Welcome prisoners with savage roasts",
                    "Track mute duration and reasons",
                    "Announce when prisoners are released",
                    "Rate limit responses (10 second cooldown)",
                    "Buffer messages from spamming prisoners"
                ]
            },
            "ai_responses": {
                "description": "Intelligent conversational AI",
                "capabilities": [
                    "Context-aware roasting for muted users",
                    "Natural conversations with family members",
                    "Database query integration",
                    "Conversation memory (last 10 messages)",
                    "Dynamic tone matching",
                    "Multiple personality modes (dad, uncle, brother)"
                ]
            },
            "family_system": {
                "description": "Special privileges for family members",
                "members": {
                    "dad": "Creator with full access",
                    "uncle": "Uncle Zaid with special responses",
                    "brother": "Brother Ward with sibling dynamic"
                },
                "privileges": [
                    "Bypass all restrictions",
                    "Work when bot is deactivated",
                    "Access from any channel",
                    "Get intelligent responses",
                    "Query database directly"
                ]
            },
            "database_queries": {
                "description": "Real-time prison statistics",
                "queries": [
                    "Most muted member",
                    "Current prisoners",
                    "Longest sentence",
                    "Prison statistics",
                    "User lookup by name",
                    "Top prisoners leaderboard"
                ],
                "tracking": [
                    "Total mutes per user",
                    "Time served in minutes",
                    "Mute reasons",
                    "Muter information",
                    "Active vs historical mutes"
                ]
            },
            "slash_commands": {
                "/activate": "Enable ragebaiting mode (admin only)",
                "/deactivate": "Disable ragebaiting mode (admin only)"
            },
            "presence_system": {
                "description": "Dynamic Discord status",
                "states": [
                    "Watching X prisoners",
                    "New prisoner arrived",
                    "Prisoner released",
                    "Sleeping (when inactive)"
                ],
                "update_interval": "30 seconds"
            }
        },

        "configuration": {
            "environment_variables": {
                "DISCORD_TOKEN": "Bot authentication",
                "OPENAI_API_KEY": "AI service key",
                "DEVELOPER_ID": "Creator's Discord ID",
                "UNCLE_ID": "Uncle's Discord ID",
                "BROTHER_ID": "Brother's Discord ID",
                "PRISON_CHANNEL_IDS": "Where prisoners are held",
                "LOGS_CHANNEL_ID": "Where to read mute logs",
                "MUTED_ROLE_ID": "Role that identifies prisoners",
                "PRISONER_COOLDOWN_SECONDS": "Rate limit (10s default)",
                "AI_MAX_TOKENS": "Response length limit",
                "AI_TEMPERATURE": "Creativity level (0-1)"
            },
            "total_configs": "30+ configurable parameters",
            "config_file": ".env file"
        },

        "technical_details": {
            "error_handling": "Comprehensive try-catch in all event handlers",
            "state_persistence": "bot_state.json for activation status",
            "rate_limiting": "10 second cooldown per prisoner",
            "message_buffering": "Collects spam messages for bulk response",
            "timezone": "EST/EDT (UTC-5)",
            "database_schema": {
                "users": "User info and message counts",
                "messages": "Message history log",
                "prisoner_history": "Complete mute history"
            },
            "api_parameters": {
                "model": "gpt-3.5-turbo",
                "max_tokens": "150-300",
                "temperature": "0.8-0.95",
                "presence_penalty": "0.4-0.6",
                "frequency_penalty": "0.2-0.3"
            }
        },

        "capabilities": {
            "can_do": [
                "Track any user's prison history",
                "Generate contextual roasts",
                "Remember conversation context",
                "Query real-time database",
                "Respond in multiple relationship modes",
                "Handle errors gracefully",
                "Run 24/7 on VPS",
                "Process multiple messages simultaneously",
                "Detect mute reasons from logs",
                "Calculate time served accurately"
            ],
            "cannot_do": [
                "Mute/unmute users (read-only)",
                "Modify server settings",
                "Access messages outside allowed channels",
                "Respond when deactivated (except to family)",
                "Generate images (text only)",
                "Voice chat interactions"
            ]
        },

        "statistics": {
            "response_time": "1-2 seconds average",
            "uptime": "99.9% reliability",
            "memory_usage": "~40MB RAM",
            "cpu_usage": "< 5% on average",
            "database_size": "Grows ~1MB per month",
            "cooldown": "10 seconds between prisoner responses"
        },

        "recent_updates": {
            "v2.3.0": [
                "Added family system",
                "AI conversation overhaul",
                "Database query integration",
                "Fixed negative time bug",
                "30+ environment variables",
                "Proper Discord mentions",
                "Error handling improvements"
            ],
            "v2.2.0": [
                "Initial prison system",
                "AI ragebaiting",
                "Mute tracking"
            ]
        },

        "how_i_work": {
            "startup": "main.py → loads .env → creates bot instance → connects to Discord",
            "message_flow": "on_message → check permissions → check if muted → generate AI response → reply",
            "mute_detection": "on_member_update → check role change → welcome/release prisoner",
            "ai_process": "receive message → build prompt → call OpenAI → format response → send",
            "database_ops": "async SQLite operations → thread pool execution → return results"
        }
    }

def get_feature_explanation(feature_name: str) -> str:
    """
    Get detailed explanation of a specific feature.
    """
    features = {
        "prison_system": """
The prison system automatically detects when users receive the muted role.
When someone gets muted, I welcome them to prison with a personalized roast.
I track how long they've been muted, why they were muted, and who muted them.
When they're released, I announce it and clear their rate limits.
Each prisoner has a 10-second cooldown to prevent spam.
        """,

        "family_system": """
The family system gives special privileges to designated family members.
Dad (the creator) gets intelligent ChatGPT-like responses and full access.
Uncle Zaid gets respectful but friendly responses with uncle-nephew dynamic.
Brother Ward gets casual sibling-like interactions with playful banter.
Family members can interact with me even when I'm deactivated.
        """,

        "ai_responses": """
My AI system uses OpenAI's GPT-3.5-turbo for intelligent responses.
I maintain conversation history to provide contextual responses.
I can adapt my tone based on who I'm talking to and what they're saying.
For prisoners, I generate savage roasts based on their mute reason.
For family, I have natural conversations like a real AI assistant.
        """,

        "database_queries": """
I can query the SQLite database for real-time prison statistics.
Ask me "who is the most muted member" and I'll check the database.
I can look up any user's prison history with "who is @username".
I track total mutes, time served, reasons, and current status.
All data is presented with proper Discord mentions for easy identification.
        """
    }

    return features.get(feature_name, "Feature not found in my knowledge base.")

def get_command_help(command: str) -> str:
    """
    Get help information for specific commands or queries.
    """
    commands = {
        "/activate": "Admin command to enable ragebaiting mode. I'll start responding to muted users.",
        "/deactivate": "Admin command to disable ragebaiting mode. I'll go to sleep.",
        "who is the most muted": "I'll query the database and tell you who's been muted the most times.",
        "current prisoners": "I'll show you who's currently in jail right now.",
        "prison stats": "I'll give you overall statistics about the prison system.",
        "who is @user": "I'll look up that specific user's prison history."
    }

    return commands.get(command.lower(), "Command not recognized. Try asking about /activate, /deactivate, or prison queries.")