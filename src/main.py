# =============================================================================
# SaydnayaBot - Main Entry Point
# =============================================================================
# Main application entry point that initializes and runs the bot with proper
# error handling, logging, and graceful shutdown support.
# =============================================================================

import asyncio
import signal
import sys
from pathlib import Path

from src.bot.bot import SaydnayaBot
from src.config.config import get_config
from src.core.instance_manager import get_instance_manager
from src.core.logger import BotLogger
from src.core.di_container import register_service, ServiceLifetime
from src.services.ai_service import AIService
from src.services.database_service import DatabaseService
from src.services.report_service import ReportService
from src.services.memory_service import MemoryService
from src.services.personality_service import PersonalityService
from src.monitoring.health_monitor import HealthMonitor

# Global references for signal handlers
bot_instance = None
logger = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    if logger:
        logger.log_warning(f"Received signal {signum}, initiating graceful shutdown...")
    if bot_instance and asyncio.get_event_loop().is_running():
        asyncio.create_task(shutdown_bot())
    else:
        sys.exit(0)


async def shutdown_bot():
    """Gracefully shutdown the bot."""
    global bot_instance
    if bot_instance:
        try:
            await bot_instance.close()
        except Exception as e:
            if logger:
                logger.log_error("Error during bot shutdown", exception=e)
        finally:
            bot_instance = None


async def run_bot():
    """
    Main bot execution function.

    This function:
    1. Sets up logging and configuration
    2. Creates and starts the bot
    3. Handles graceful shutdown
    """
    global bot_instance, logger

    # Initialize logger
    bot_logger = BotLogger()
    logger = bot_logger
    
    # Initialize instance manager
    instance_manager = get_instance_manager()

    # Log startup
    bot_logger.log_startup("1.0.0")

    try:
        # Load configuration
        bot_logger.log_initialization_step(
            "Configuration", "loading", "Loading environment configuration"
        )
        config = get_config()
        config.load_configuration()
        bot_logger.log_initialization_step(
            "Configuration", "success", "Configuration loaded successfully", "✅"
        )

        # Check instance lock
        bot_logger.log_initialization_step(
            "Instance Manager", "checking", "Checking for existing instances"
        )

        # Check and terminate existing instances
        can_proceed = instance_manager.check_and_terminate_existing()
        if not can_proceed:
            bot_logger.log_error("Failed to acquire instance lock")
            return
            
        # Create PID file
        instance_manager.create_pid_file()

        bot_logger.log_initialization_step(
            "Instance Manager", "success", "Instance lock acquired", "✅"
        )

        # Register services in DI container
        bot_logger.log_initialization_step(
            "DI Container", "registering", "Registering services"
        )
        
        # Register core services
        from src.core.di_container import register_factory
        register_factory("Config", lambda: config, lifetime=ServiceLifetime.SINGLETON)
        register_service("Logger", type(bot_logger), lifetime=ServiceLifetime.SINGLETON)
        register_service("DatabaseService", DatabaseService, lifetime=ServiceLifetime.SINGLETON)
        register_service("MemoryService", MemoryService, lifetime=ServiceLifetime.SINGLETON)
        register_service("PersonalityService", PersonalityService, lifetime=ServiceLifetime.SINGLETON)
        register_service("AIService", AIService, lifetime=ServiceLifetime.SINGLETON, dependencies=["Config", "PersonalityService", "MemoryService"])
        register_service("ReportService", ReportService, lifetime=ServiceLifetime.SINGLETON, dependencies=["DatabaseService"])
        register_service("HealthMonitor", HealthMonitor, lifetime=ServiceLifetime.SINGLETON)
        
        bot_logger.log_initialization_step(
            "DI Container", "success", "Services registered", "✅"
        )

        # Create bot instance
        bot_logger.log_initialization_step("Bot", "creating", "Creating bot instance")
        bot_instance = SaydnayaBot(config)
        bot_logger.log_initialization_step(
            "Bot", "success", "Bot instance created", "✅"
        )

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start the bot
        bot_logger.log_initialization_step(
            "Bot", "starting", "Starting bot connection to Discord"
        )

        bot_logger.log_system_event(
            "bot_ready",
            "SaydnayaBot is starting...",
            {"mode": "production", "version": "1.0.0"},
        )

        # Get Discord token
        discord_token = config.get("DISCORD_TOKEN")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN not found in configuration")

        # Run the bot
        await bot_instance.start(discord_token)

    except KeyboardInterrupt:
        bot_logger.log_warning("Received keyboard interrupt")
    except Exception as e:
        bot_logger.log_error("Fatal error in main", exception=e)
        raise
    finally:
        # Cleanup
        bot_logger.log_shutdown("Bot shutdown initiated")

        # Cleanup PID file
        instance_manager.cleanup_pid_file()

        # Close bot if still connected
        if bot_instance:
            await shutdown_bot()

        bot_logger.log_shutdown("Shutdown complete")


def main():
    """Entry point for the application."""
    # Create logs directory if it doesn't exist
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Set up asyncio for Windows
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Run the bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()