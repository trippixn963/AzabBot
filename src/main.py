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
from src.core.di_container import setup_dependencies
from src.core.instance_manager import instance_manager
from src.core.log_optimizer import LogOptimizer
from src.core.logger import BotLogger
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
    2. Initializes dependency injection
    3. Creates and starts the bot
    4. Handles graceful shutdown
    """
    global bot_instance, logger

    # Initialize logger
    bot_logger = BotLogger()
    logger = bot_logger

    # Log startup
    bot_logger.log_startup("SaydnayaBot", "1.0.0")

    try:
        # Load configuration
        bot_logger.log_initialization_step(
            "Configuration", "loading", "Loading environment configuration"
        )
        config = get_config()
        bot_logger.log_initialization_step(
            "Configuration", "success", "Configuration loaded successfully", "✅"
        )

        # Setup dependency injection
        bot_logger.log_initialization_step(
            "Dependencies", "loading", "Setting up dependency injection"
        )
        await setup_dependencies()
        bot_logger.log_initialization_step(
            "Dependencies", "success", "Dependencies initialized", "✅"
        )

        # Check instance lock
        bot_logger.log_initialization_step(
            "Instance Manager", "checking", "Checking for existing instances"
        )

        # Get instance lock
        lock_acquired = instance_manager.acquire_lock()
        if not lock_acquired:
            bot_logger.log_error(
                "Another instance is already running",
                context={
                    "pid": instance_manager.get_running_pid(),
                    "lock_file": str(instance_manager.lock_file),
                },
            )
            return

        bot_logger.log_initialization_step(
            "Instance Manager", "success", "Instance lock acquired", "✅"
        )

        # Initialize health monitor
        bot_logger.log_initialization_step(
            "Health Monitor", "starting", "Starting health monitoring"
        )
        health_monitor = HealthMonitor()
        asyncio.create_task(health_monitor.start_monitoring())
        bot_logger.log_initialization_step(
            "Health Monitor", "success", "Health monitoring started", "✅"
        )

        # Initialize log optimizer
        bot_logger.log_initialization_step(
            "Log Optimizer", "starting", "Starting log optimization service"
        )
        log_optimizer = LogOptimizer()
        asyncio.create_task(log_optimizer.start())
        bot_logger.log_initialization_step(
            "Log Optimizer", "success", "Log optimization started", "✅"
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

        bot_logger.log_event(
            "bot_ready",
            "SaydnayaBot is starting...",
            {"mode": "production", "version": "1.0.0"},
        )

        # Run the bot
        await bot_instance.start(config.get("discord_token"))

    except KeyboardInterrupt:
        bot_logger.log_warning("Received keyboard interrupt")
    except Exception as e:
        bot_logger.log_error("Fatal error in main", exception=e)
        raise
    finally:
        # Cleanup
        bot_logger.log_shutdown("Bot shutdown initiated")

        # Release instance lock
        instance_manager.release_lock()

        # Stop services
        if "log_optimizer" in locals():
            await log_optimizer.stop()
        if "health_monitor" in locals():
            await health_monitor.stop()

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
