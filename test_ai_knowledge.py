#!/usr/bin/env python3
"""
Test script for Azab's AI technical knowledge capabilities.

This script tests the AI's ability to answer technical questions
about its own codebase, architecture, and features.

Author: حَـــــنَّـــــا
Version: v2.4.0
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.services.ai_service import AIService
from src.core.database import Database
from src.core.logger import logger

# Load environment variables
load_dotenv()

async def test_ai_knowledge():
    """Test the AI's technical knowledge capabilities."""

    # Initialize services
    db = Database()  # Database initializes in __init__
    ai_service = AIService(db)

    # Test questions about the bot's architecture and features
    test_questions = [
        ("How do you work?", "general architecture"),
        ("What are your features?", "feature list"),
        ("Explain your prison system", "prison system details"),
        ("What's your architecture?", "technical architecture"),
        ("Tell me about your family system", "family system details"),
        ("What database queries can you do?", "database capabilities"),
        ("What version are you?", "version information"),
        ("How many lines of code do you have?", "codebase stats"),
        ("What AI model do you use?", "AI model details"),
        ("Explain how your rate limiting works", "rate limiting details")
    ]

    print("=" * 80)
    print("TESTING AZAB'S TECHNICAL KNOWLEDGE")
    print("=" * 80)
    print()

    # Test as developer (dad)
    print("Testing Developer Responses:")
    print("-" * 40)

    for question, description in test_questions:
        print(f"\n📝 Test: {description}")
        print(f"❓ Question: {question}")

        try:
            response = await ai_service.generate_developer_response(question, "Dad")
            print(f"✅ Response: {response[:200]}..." if len(response) > 200 else f"✅ Response: {response}")
        except Exception as e:
            print(f"❌ Error: {e}")

        print("-" * 40)

        # Small delay to avoid rate limiting
        await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("Testing Uncle Responses:")
    print("-" * 40)

    # Test a few questions as uncle
    uncle_questions = test_questions[:3]  # Test first 3 questions

    for question, description in uncle_questions:
        print(f"\n📝 Test: {description}")
        print(f"❓ Question: {question}")

        try:
            response = await ai_service.generate_uncle_response(question, "Uncle Zaid")
            print(f"✅ Response: {response[:200]}..." if len(response) > 200 else f"✅ Response: {response}")
        except Exception as e:
            print(f"❌ Error: {e}")

        print("-" * 40)
        await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("Testing Brother Responses:")
    print("-" * 40)

    # Test a few questions as brother
    brother_questions = test_questions[:3]  # Test first 3 questions

    for question, description in brother_questions:
        print(f"\n📝 Test: {description}")
        print(f"❓ Question: {question}")

        try:
            response = await ai_service.generate_brother_response(question, "Ward")
            print(f"✅ Response: {response[:200]}..." if len(response) > 200 else f"✅ Response: {response}")
        except Exception as e:
            print(f"❌ Error: {e}")

        print("-" * 40)
        await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("TECHNICAL KNOWLEDGE TESTING COMPLETE")
    print("=" * 80)

    # Close database
    # Database doesn't have a close method, it's handled automatically

if __name__ == "__main__":
    asyncio.run(test_ai_knowledge())