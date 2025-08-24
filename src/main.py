"""
AzabBot - Main Application Entry Point
=========================================

This module contains the main application logic for the AzabBot Discord application.
It handles the complete lifecycle of the bot including initialization, startup,
runtime execution, and graceful shutdown.

The module implements:
- Dependency injection container setup
- Service registration and initialization
- Signal handling for graceful shutdown
- Instance management (preventing multiple bot instances)
- Comprehensive logging throughout the startup process
- Error handling and cleanup procedures

Key Functions:
- run_bot(): Main async function that orchestrates the bot lifecycle
- main(): Entry point that sets up the environment and runs the bot
- signal_handler(): Handles shutdown signals (SIGINT, SIGTERM)
- shutdown_bot(): Gracefully closes bot connections and cleans up resources
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

from src import __version__
from src.bot.bot import AzabBot
from src.config.config import get_config
from src.core.di_container import ServiceLifetime, register_service
from src.core.instance_manager import get_instance_manager
from src.core.logger import BotLogger
from src.monitoring.health_monitor import HealthMonitor
from src.services.ai_service import AIService
from src.services.database_service import DatabaseService
from src.services.memory_service import MemoryService
from src.services.personality_service import PersonalityService
from src.services.report_service import ReportService
from src.services.prison_service import PrisonService
from src.services.psychological_service import PsychologicalService
from src.services.dashboard_service import DashboardService
from src.utils.db_pool import DatabasePool
from src.utils.cache import get_cache_manager
from src.utils.message_queue import MessageQueue
from src.utils.cooldowns import get_cooldown_manager
from src.utils.shutdown import get_shutdown_handler
from src.utils.backup import BackupManager
from src.utils.memory_optimizer import get_memory_optimizer

# Global references for signal handlers
# These are needed because signal handlers can't be async functions
bot_instance: Optional[AzabBot] = None
logger: Optional[BotLogger] = None


def signal_handler(signum: int, frame: Optional[object]) -> None:
    """
    Handle shutdown signals gracefully.
    
    This function is called when the bot receives SIGINT (Ctrl+C) or SIGTERM.
    It initiates a graceful shutdown by creating an async task to close the bot.
    
    Args:
        signum: The signal number received
        frame: The current stack frame (unused)
    """
    if logger:
        logger.log_warning(f"Received signal {signum}, initiating graceful shutdown...")
    if bot_instance and asyncio.get_event_loop().is_running():
        asyncio.create_task(shutdown_bot())
    else:
        sys.exit(0)


async def shutdown_bot() -> None:
    """
    Gracefully shutdown the bot.
    
    This function ensures that the bot disconnects from Discord properly
    and cleans up any resources before termination.
    """
    global bot_instance
    if bot_instance:
        try:
            await bot_instance.close()
        except Exception as e:
            if logger:
                logger.log_error("Error during bot shutdown", exception=e)
        finally:
            bot_instance = None


async def process_message_batch(batch):
    """
    Process a batch of messages from the queue.
    
    Args:
        batch: List of QueuedMessage objects
        
    Returns:
        List of success/failure booleans
    """
    results = []
    for message in batch:
        try:
            # Process message through Discord bot
            if logger:
                logger.log_debug(f"Processing queued message for user {message.user_id}")
            # Message processing is handled by the bot's message handling system
            results.append(True)
        except Exception as e:
            if logger:
                logger.log_error(f"Failed to process message for user {message.user_id}", exception=e)
            results.append(False)
    return results


async def run_bot() -> None:
    """
    Main bot execution function that orchestrates the complete bot lifecycle.
    
    This function performs the following steps in order:
    1. Initialize logging and configuration
    2. Set up instance management (prevent multiple bot instances)
    3. Register all services in the dependency injection container
    4. Create and configure the Discord bot instance
    5. Set up signal handlers for graceful shutdown
    6. Start the bot and connect to Discord
    7. Handle any errors and perform cleanup on exit
    
    The function includes comprehensive error handling and logging
    at each step of the initialization process.
    """
    global bot_instance, logger

    # Initialize core components
    bot_logger = BotLogger()
    logger = bot_logger
    instance_manager = get_instance_manager()
    
    # Initialize optimization systems
    cache_manager = get_cache_manager()
    cooldown_manager = get_cooldown_manager()
    shutdown_handler = get_shutdown_handler()
    memory_optimizer = get_memory_optimizer()

    # Log startup with version information
    bot_logger.log_startup(__version__)

    try:
        # Step 1: Load and validate configuration
        bot_logger.log_initialization_step(
            "Configuration", "loading", "Loading environment configuration"
        )
        config = get_config()
        config.load_configuration()
        bot_logger.log_initialization_step(
            "Configuration", "success", "Configuration loaded successfully", "✅"
        )

        # Step 2: Instance management - ensure only one bot instance runs
        bot_logger.log_initialization_step(
            "Instance Manager", "checking", "Checking for existing instances"
        )

        # Check and terminate any existing bot instances
        can_proceed = instance_manager.check_and_terminate_existing()
        if not can_proceed:
            bot_logger.log_error("Failed to acquire instance lock")
            return

        # Create PID file to track this instance
        instance_manager.create_pid_file()

        bot_logger.log_initialization_step(
            "Instance Manager", "success", "Instance lock acquired", "✅"
        )

        # Step 3: Register all services in dependency injection container
        bot_logger.log_initialization_step(
            "DI Container", "registering", "Registering services"
        )

        # Import here to avoid circular imports
        from src.core.di_container import register_factory, get_container

        # Set container-wide configuration
        container = get_container()
        container.set_container_config(config.get_all())

        # Initialize database pool and backup manager
        db_path = Path("data/azab.db")
        db_pool = DatabasePool(db_path, max_connections=5)
        backup_manager = BackupManager(db_path, Path("backups"))
        
        # Initialize message queue
        message_queue = MessageQueue(batch_size=10, batch_interval=1.0)
        
        # Register shutdown handler
        shutdown_handler.register_signal_handlers()
        
        # Register core services with appropriate lifetimes
        register_factory("Config", lambda: config, lifetime=ServiceLifetime.SINGLETON)
        register_service("Logger", type(bot_logger), lifetime=ServiceLifetime.SINGLETON)
        register_factory("DatabasePool", lambda: db_pool, lifetime=ServiceLifetime.SINGLETON)
        register_factory("BackupManager", lambda: backup_manager, lifetime=ServiceLifetime.SINGLETON)
        register_factory("MessageQueue", lambda: message_queue, lifetime=ServiceLifetime.SINGLETON)
        register_factory("CacheManager", lambda: cache_manager, lifetime=ServiceLifetime.SINGLETON)
        register_factory("CooldownManager", lambda: cooldown_manager, lifetime=ServiceLifetime.SINGLETON)
        register_factory("MemoryOptimizer", lambda: memory_optimizer, lifetime=ServiceLifetime.SINGLETON)
        register_service(
            "DatabaseService", DatabaseService, lifetime=ServiceLifetime.SINGLETON
        )
        register_service(
            "MemoryService", MemoryService, lifetime=ServiceLifetime.SINGLETON
        )
        register_service(
            "PersonalityService", PersonalityService, lifetime=ServiceLifetime.SINGLETON
        )
        
        # Register services with dependencies
        register_service(
            "AIService",
            AIService,
            lifetime=ServiceLifetime.SINGLETON,
            dependencies=["Config", "PersonalityService", "MemoryService"],
        )
        register_service(
            "ReportService",
            ReportService,
            lifetime=ServiceLifetime.SINGLETON,
            dependencies=["DatabaseService"],
        )
        register_service(
            "HealthMonitor", HealthMonitor, lifetime=ServiceLifetime.SINGLETON
        )
        register_service(
            "PrisonService",
            PrisonService,
            lifetime=ServiceLifetime.SINGLETON,
            dependencies=["Config", "DatabaseService", "AIService"]
        )
        register_service(
            "PsychologicalService",
            PsychologicalService,
            lifetime=ServiceLifetime.SINGLETON,
            dependencies=["Config", "DatabaseService", "AIService"]
        )
        
        # Register Dashboard Service if enabled
        if config.get("DASHBOARD_ENABLED", "false").lower() == "true":
            register_service(
                "DashboardService",
                DashboardService,
                lifetime=ServiceLifetime.SINGLETON
            )
            bot_logger.log_info("Dashboard service registered")

        bot_logger.log_initialization_step(
            "DI Container", "success", "Services registered", "✅"
        )

        # Step 4: Create and configure the Discord bot instance
        bot_logger.log_initialization_step("Bot", "creating", "Creating bot instance")
        bot_instance = AzabBot(config.get_all())
        bot_logger.log_initialization_step(
            "Bot", "success", "Bot instance created", "✅"
        )

        # Step 5: Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

        # Start optimization services
        await cache_manager.start()
        await backup_manager.start(interval=3600)  # Hourly backups
        await memory_optimizer.start(check_interval=60)  # Check every minute
        await message_queue.start(lambda batch: process_message_batch(batch))
        
        # Register cleanup callbacks
        shutdown_handler.register_callback(cache_manager.stop)
        shutdown_handler.register_callback(backup_manager.stop)
        shutdown_handler.register_callback(memory_optimizer.stop)
        shutdown_handler.register_callback(message_queue.stop)
        shutdown_handler.register_callback(db_pool.close)
        
        # Step 6: Start the bot and connect to Discord
        bot_logger.log_initialization_step(
            "Bot", "starting", "Starting bot connection to Discord"
        )

        bot_logger.log_system_event(
            "bot_ready",
            "AzabBot is starting...",
            {"mode": "production", "version": __version__},
        )

        # Validate Discord token before attempting connection
        discord_token = config.get("DISCORD_TOKEN")
        if not discord_token:
            raise ValueError("DISCORD_TOKEN not found in configuration")

        # Connect to Discord and start the bot
        await bot_instance.start(discord_token)

    except KeyboardInterrupt:
        bot_logger.log_warning("Received keyboard interrupt")
    except Exception as e:
        bot_logger.log_error("Fatal error in main", exception=e)
        raise
    finally:
        # Step 7: Cleanup and shutdown procedures
        bot_logger.log_shutdown("Bot shutdown initiated")

        # Stop optimization services
        await cache_manager.stop()
        await backup_manager.stop()
        await memory_optimizer.stop()
        await message_queue.stop()
        await db_pool.close()
        
        # Clean up instance management resources
        instance_manager.cleanup_pid_file()

        # Ensure bot is properly closed if still connected
        if bot_instance:
            await shutdown_bot()

        bot_logger.log_shutdown("Shutdown complete")


def main() -> None:
    """
    Entry point for the application.
    
    This function sets up the environment and runs the bot. It handles:
    - Creating necessary directories (logs, data)
    - Setting up asyncio event loop policy for Windows compatibility
    - Running the main bot function with proper error handling
    - Providing user-friendly error messages for common issues
    """
    # Ensure required directories exist
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Windows-specific asyncio setup for compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Run the bot with comprehensive error handling
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
