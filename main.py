#!/usr/bin/env python3
"""
SaydnayaBot - Application Entry Point
====================================

This module serves as the main entry point for the SaydnayaBot Discord application.
It handles the initialization of the Python path and launches the bot asynchronously.

The module ensures that the project root directory is in the Python path so that
relative imports from the src/ directory work correctly when running the script
directly from the project root.

Usage:
    python main.py
    python3 main.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is in Python path for relative imports
# This is necessary when running the script directly from the project root
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import the main bot runner function
from src.main import run_bot

if __name__ == "__main__":
    # Launch the Discord bot asynchronously
    asyncio.run(run_bot())
