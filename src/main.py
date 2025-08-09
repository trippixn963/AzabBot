# =============================================================================
# SaydnayaBot - Main Application Entry Point
# =============================================================================
# Professional bot launcher with comprehensive service initialization,
# configuration management, and error handling. This is the main entry
# point for the SaydnayaBot application.
#
# Features:
# - Service-oriented architecture initialization
# - Dependency injection container setup
# - Configuration management and validation
# - Health monitoring and metrics
# - Graceful shutdown handling
# - Comprehensive error handling and logging
# =============================================================================

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any, Dict

from src.bot.bot import SaydnayaBot
from src.config.config import get_config, load_configuration
from src.core.di_container import (
    ServiceLifetime,
    get_container,
    initialize_all_services,
    register_service,
)
from src.core.exceptions import (
    ConfigurationError,
    SaydnayaBotException,
    ServiceInitializationError,
)
from src.core.instance_manager import get_instance_manager
from src.core.log_optimizer import initialize_log_management, shutdown_log_management
from src.core.logger import log_error, log_info, log_startup
from src.monitoring.health_monitor import HealthMonitor
from src.services.ai_service import AIService
from src.services.database_service import PrisonerDatabaseService
from src.services.report_service import ReportService

# Global references for cleanup
bot_instance = None
container = None
instance_manager = None


async def setup_services(config: Dict[str, Any]) -> None:
    """
    Set up all services in the dependency injection container.

    Args:
        config: Application configuration
    """
    global container
    container = get_container()

    # Set global container configuration
    container.set_container_config(config)

    log_info("Setting up services", "🔧")

    # Register core services
    register_service(
        "PrisonerDatabaseService",
        PrisonerDatabaseService,
        lifetime=ServiceLifetime.SINGLETON,
        config={"DATABASE_DIR": config.get("DATABASE_DIR", "data")},
    )

    register_service(
        "AIService",
        AIService,
        lifetime=ServiceLifetime.SINGLETON,
        dependencies=["PrisonerDatabaseService"],
        config={
            "OPENAI_API_KEY": config.get("OPENAI_API_KEY"),
            "AI_MODEL": config.get("AI_MODEL", "gpt-3.5-turbo"),
            "MAX_RESPONSE_LENGTH": config.get("MAX_RESPONSE_LENGTH", 200),
            "RESPONSE_PROBABILITY": config.get("RESPONSE_PROBABILITY", 0.3),
            "PRISON_MODE": config.get("PRISON_MODE", False),
            "TARGET_CHANNEL_IDS": config.get("TARGET_CHANNEL_IDS", []),
            "PRISON_CHANNEL_IDS": config.get("PRISON_CHANNEL_IDS", []),
            "PRISON_USER_COOLDOWN_MINUTES": config.get(
                "PRISON_USER_COOLDOWN_MINUTES", 1.0
            ),
            "PRISON_CHANNEL_COOLDOWN_MINUTES": config.get(
                "PRISON_CHANNEL_COOLDOWN_MINUTES", 0.5
            ),
            "AZAB_MODE_ENABLED": config.get("AZAB_MODE_ENABLED", True),
            "AZAB_PROBABILITY": config.get("AZAB_PROBABILITY", 0.7),
        },
    )

    register_service(
        "ReportService",
        ReportService,
        lifetime=ServiceLifetime.SINGLETON,
        dependencies=["PrisonerDatabaseService"],
        config={},
    )

    register_service(
        "HealthMonitor",
        HealthMonitor,
        lifetime=ServiceLifetime.SINGLETON,
        dependencies=[],
        config={"health_check_interval": 30.0, "metrics_interval": 60.0},
    )

    # Initialize all services
    await initialize_all_services()

    log_info("All services initialized successfully", "✅")


async def create_bot(config: Dict[str, Any]) -> SaydnayaBot:
    """
    Create and configure the Discord bot.

    Args:
        config: Application configuration

    Returns:
        Configured SaydnayaBot instance
    """
    log_info("Creating bot instance", "🤖")

    # Extract bot-specific configuration
    bot_config = {
        "developer_id": config.get("DEVELOPER_ID"),
        "response_probability": config.get("RESPONSE_PROBABILITY", 0.3),
        "prison_mode": config.get("PRISON_MODE", False),
        "enable_rage_gifs": config.get("ENABLE_RAGE_GIFS", True),
        "enable_identity_theft": config.get("ENABLE_IDENTITY_THEFT", True),
        "enable_nickname_changes": config.get("ENABLE_NICKNAME_CHANGES", True),
        "enable_micro_timeouts": config.get("ENABLE_MICRO_TIMEOUTS", False),
        "target_channel_ids": config.get("TARGET_CHANNEL_IDS", []),
        "prison_channel_ids": config.get("PRISON_CHANNEL_IDS", []),
        "ignore_user_ids": config.get("IGNORE_USER_IDS", []),
        "admin_user_ids": config.get(
            "IGNORE_USER_IDS", []
        ),  # Admins are in ignore list
        "required_role_id": config.get("REQUIRED_ROLE_ID"),
        "user_cooldown_minutes": config.get("USER_COOLDOWN_MINUTES", 5),
        "channel_cooldown_minutes": config.get("CHANNEL_COOLDOWN_MINUTES", 2),
        "prison_user_cooldown_minutes": config.get("PRISON_USER_COOLDOWN_MINUTES", 1.0),
        "prison_channel_cooldown_minutes": config.get(
            "PRISON_CHANNEL_COOLDOWN_MINUTES", 0.5
        ),
        "max_daily_responses": config.get("MAX_DAILY_RESPONSES", 100),
    }

    return SaydnayaBot(bot_config)


def setup_signal_handlers():
    """Set up graceful shutdown signal handlers."""

    def signal_handler(signum, frame):
        log_info(f"Received signal {signum}, initiating graceful shutdown", "🛑")
        asyncio.create_task(shutdown_gracefully())

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def shutdown_gracefully():
    """Perform graceful shutdown of all services."""

    try:
        log_info("Starting graceful shutdown", "🛑")

        # Close bot connection
        if bot_instance:
            log_info("Closing bot connection")
            await bot_instance.close()

        # Shutdown all services
        if container:
            log_info("Shutting down services")
            await container.shutdown_all_services()

        # Shutdown log management
        log_info("Shutting down log management")
        await shutdown_log_management()

        # Clean up instance manager
        if instance_manager:
            instance_manager.cleanup_pid_file()

        log_info("Graceful shutdown completed", "✅")

    except Exception as e:
        log_error("Error during graceful shutdown", exception=e)

    finally:
        # Force exit after cleanup attempt
        loop = asyncio.get_running_loop()
        loop.stop()


async def main():
    """Main application entry point."""
    global bot_instance, instance_manager

    try:
        # Check for and terminate existing instances
        instance_manager = get_instance_manager()
        log_info("Checking for existing bot instances", "🔍")

        if not instance_manager.check_and_terminate_existing():
            log_error("Failed to resolve instance conflicts")
            sys.exit(1)

        # Create PID file
        if not instance_manager.create_pid_file():
            log_info("Could not create PID file, continuing anyway", "⚠️")

        # Load and validate configuration
        log_info("Loading configuration", "⚙️")
        config = load_configuration()

        # Validate critical configuration
        config_manager = get_config()
        validation_errors = config_manager.validate_all()

        if validation_errors:
            log_error("Configuration validation failed:")
            for error in validation_errors:
                log_error(f"  - {error}")
            sys.exit(1)

        # Log startup with configuration summary
        config_summary = config_manager.get_configuration_summary(
            include_sensitive=False
        )
        log_startup("1.0.0", config_summary)

        # Set up signal handlers for graceful shutdown
        setup_signal_handlers()

        # Initialize log management system
        log_dir = Path(config.get("LOG_DIR", "logs"))
        await initialize_log_management(
            log_dir=log_dir,
            retention_days=config.get("LOG_RETENTION_DAYS", 7),
            compress_after_days=config.get("LOG_COMPRESS_AFTER_DAYS", 1),
            error_retention_days=config.get("ERROR_LOG_RETENTION_DAYS", 30),
            max_file_size_mb=config.get("MAX_LOG_FILE_SIZE_MB", 10),
        )
        log_info("Log management system initialized", "📁")

        # Initialize services
        await setup_services(config)

        # Create bot instance
        bot_instance = await create_bot(config)

        # Get Discord token
        discord_token = config.get("DISCORD_TOKEN")
        if not discord_token or discord_token == "your_discord_bot_token_here":
            log_error(
                "Discord token not configured. Please set DISCORD_TOKEN in config/.env"
            )
            sys.exit(1)

        # Start the bot
        log_info("Starting Discord bot", "🚀")

        try:
            await bot_instance.start(discord_token)
        except KeyboardInterrupt:
            log_info("Bot stopped by user interrupt")
        except Exception as e:
            log_error("Bot crashed", exception=e)
            raise

    except ConfigurationError as e:
        log_error(f"Configuration error: {e}")
        sys.exit(1)

    except ServiceInitializationError as e:
        log_error(f"Service initialization failed: {e}")
        sys.exit(1)

    except SaydnayaBotException as e:
        log_error(f"Bot error: {e}")
        if e.context:
            log_error(f"Error context: {e.context}")
        sys.exit(1)

    except Exception as e:
        log_error("Unexpected error", exception=e)
        sys.exit(1)

    finally:
        # Ensure cleanup happens
        await shutdown_gracefully()


def run_bot():
    """
    Entry point for running the bot.

    This function handles the event loop setup and cleanup.
    """
    try:
        # Create and configure event loop
        if sys.platform == "win32":
            # Use ProactorEventLoop on Windows for better async performance
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        # Run the main application
        asyncio.run(main())

    except KeyboardInterrupt:
        log_info("Bot stopped by user")

    except Exception as e:
        log_error("Fatal error in bot execution", exception=e)
        sys.exit(1)


if __name__ == "__main__":
    run_bot()
