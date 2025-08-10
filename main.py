#!/usr/bin/env python3
# =============================================================================
# SaydnayaBot - Application Entry Point
# =============================================================================
# This is the main entry point for the SaydnayaBot application.
# It imports and runs the main application from the app module.
# =============================================================================

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import and run the main application
from src.main import run_bot

if __name__ == "__main__":
    asyncio.run(run_bot())
