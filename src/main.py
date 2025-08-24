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
# DI container removed - using direct service instantiation
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
    
    # Import tree logging functions
    from src.utils.tree_log import log_enhanced_tree_section

    # Initialize core components
    bot_logger = BotLogger()
    logger = bot_logger
    instance_manager = get_instance_manager()
    
    # Initialize optimization systems
    cache_manager = get_cache_manager()
    cooldown_manager = get_cooldown_manager()
    shutdown_handler = get_shutdown_handler()
    memory_optimizer = get_memory_optimizer()
    
    # Initialize variables for cleanup
    db_pool = None
    backup_manager = None
    message_queue = None
    database_service = None
    memory_service = None
    personality_service = None
    ai_service = None
    report_service = None
    health_monitor = None
    prison_service = None
    psychological_service = None

    # Log startup with version information
    bot_logger.log_startup(__version__)

    try:
        # Step 1: Load and validate configuration
        log_enhanced_tree_section(
            "Configuration Loading",
            [
                ("status", "Loading environment configuration"),
                ("method", "Environment variables")
            ],
            performance_metrics={
                "loading_method": "env_vars"
            },
            context_data={
                "loading_type": "configuration",
                "method": "environment_variables"
            },
            emoji="⚙️"
        )
        
        config = get_config()
        config.load_configuration()
        
        log_enhanced_tree_section(
            "Configuration Loaded",
            [
                ("status", "Configuration loaded successfully"),
                ("config_keys", str(len(config.get_all()))),
                ("method", "Environment variables")
            ],
            performance_metrics={
                "config_keys_count": len(config.get_all()),
                "loading_success": True
            },
            context_data={
                "loading_type": "configuration_complete",
                "config_keys": list(config.get_all().keys())
            },
            emoji="✅"
        )

        # Step 2: Instance management - ensure only one bot instance runs
        log_enhanced_tree_section(
            "Instance Management",
            [
                ("status", "Checking for existing instances"),
                ("method", "PID file check")
            ],
            performance_metrics={
                "check_method": "pid_file"
            },
            context_data={
                "management_type": "instance_check",
                "method": "pid_file_validation"
            },
            emoji="🔒"
        )

        # Check and terminate any existing bot instances
        can_proceed = instance_manager.check_and_terminate_existing()
        if not can_proceed:
            bot_logger.log_error("Failed to acquire instance lock")
            return

        # Create PID file to track this instance
        instance_manager.create_pid_file()

        log_enhanced_tree_section(
            "Instance Lock Acquired",
            [
                ("status", "Instance lock acquired successfully"),
                ("pid_file", "Created"),
                ("method", "PID file management")
            ],
            performance_metrics={
                "lock_acquired": True,
                "pid_file_created": True
            },
            context_data={
                "management_type": "instance_lock",
                "method": "pid_file_management"
            },
            emoji="✅"
        )

        # Step 3: Initialize services directly
        log_enhanced_tree_section(
            "Service Initialization",
            [
                ("status", "Initializing services directly"),
                ("approach", "Direct instantiation"),
                ("no_di", "DI container removed")
            ],
            performance_metrics={
                "initialization_method": "direct"
            },
            context_data={
                "initialization_type": "service_setup",
                "method": "direct_instantiation"
            },
            emoji="🔧"
        )

        # Initialize database pool and backup manager
        db_path = Path("data/prisoners.db")
        db_pool = DatabasePool(db_path, max_connections=5)
        backup_manager = BackupManager(db_path, Path("backups"))
        
        # Initialize message queue
        message_queue = MessageQueue(batch_size=10, batch_interval=1.0)
        
        # Register shutdown handler
        shutdown_handler.register_signal_handlers()
        
        # Initialize services directly
        database_service = DatabaseService()
        memory_service = MemoryService()
        personality_service = PersonalityService()
        ai_service = AIService()
        report_service = ReportService()
        health_monitor = HealthMonitor()
        prison_service = PrisonService()
        psychological_service = PsychologicalService()
        
        # Initialize services with dependencies
        await database_service.initialize_base(config.get_all())
        await memory_service.initialize_base(config.get_all())
        await personality_service.initialize_base(config.get_all())
        await ai_service.initialize_base(config.get_all(), 
                                       PersonalityService=personality_service,
                                       MemoryService=memory_service,
                                       PrisonerDatabaseService=database_service)
        await report_service.initialize_base(config.get_all(), 
                                           PrisonerDatabaseService=database_service)
        await health_monitor.initialize_base(config.get_all())
        await prison_service.initialize_base(config.get_all(),
                                           DatabaseService=database_service,
                                           AIService=ai_service)
        await psychological_service.initialize_base(config.get_all(),
                                                  DatabaseService=database_service,
                                                  AIService=ai_service)
        
        # Start services
        await database_service.start_base()
        await memory_service.start_base()
        await personality_service.start_base()
        await ai_service.start_base()
        await report_service.start_base()
        await health_monitor.start_base()
        await prison_service.start_base()
        await psychological_service.start_base()
        
        log_enhanced_tree_section(
            "Service Initialization Complete",
            [
                ("status", "All services initialized and started"),
                ("total_services", "8"),
                ("method", "Direct instantiation")
            ],
            performance_metrics={
                "services_initialized": 8,
                "initialization_success_rate": 100.0
            },
            context_data={
                "initialization_type": "service_setup_complete",
                "services_list": ["DatabaseService", "MemoryService", "PersonalityService", 
                                "AIService", "ReportService", "HealthMonitor", 
                                "PrisonService", "PsychologicalService"]
            },
            emoji="✅"
        )

        # Step 4: Create and configure the Discord bot instance
        log_enhanced_tree_section(
            "Bot Instance Creation",
            [
                ("status", "Creating bot instance"),
                ("method", "Direct instantiation")
            ],
            performance_metrics={
                "creation_method": "direct"
            },
            context_data={
                "creation_type": "bot_instance",
                "method": "direct_instantiation"
            },
            emoji="🤖"
        )
        
        bot_instance = AzabBot(config.get_all())
        
        # Pass services to the bot
        bot_instance.ai_service = ai_service
        bot_instance.health_monitor = health_monitor
        bot_instance.prison_service = prison_service
        bot_instance.psychological_service = psychological_service
        bot_instance.memory_service = memory_service
        bot_instance.personality_service = personality_service
        
        log_enhanced_tree_section(
            "Bot Instance Created",
            [
                ("status", "Bot instance created successfully"),
                ("services_attached", "6 services"),
                ("method", "Direct service injection")
            ],
            performance_metrics={
                "services_attached": 6,
                "injection_method": "direct"
            },
            context_data={
                "creation_type": "bot_instance_complete",
                "services_attached": ["ai_service", "health_monitor", "prison_service", 
                                    "psychological_service", "memory_service", "personality_service"]
            },
            emoji="✅"
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
        log_enhanced_tree_section(
            "Bot Connection",
            [
                ("status", "Starting bot connection to Discord"),
                ("method", "Discord.py connection")
            ],
            performance_metrics={
                "connection_method": "discord_py"
            },
            context_data={
                "connection_type": "discord_connection",
                "method": "discord_py_start"
            },
            emoji="🚀"
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
        if cache_manager:
            await cache_manager.stop()
        if backup_manager:
            await backup_manager.stop()
        if memory_optimizer:
            await memory_optimizer.stop()
        if message_queue:
            await message_queue.stop()
        if db_pool:
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
