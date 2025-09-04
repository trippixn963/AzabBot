"""
Azab Discord Bot - Database Module
=================================

SQLite database wrapper for storing user messages and analytics.
Provides async database operations for logging Discord interactions
and maintaining user statistics.

Features:
- User message logging and counting
- Message content storage with timestamps
- User imprisonment status tracking
- Async database operations

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular
"""

import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta


class Database:
    """
    SQLite database wrapper for Azab Discord bot.
    
    Handles all database operations including:
    - User information storage and updates
    - Message logging with timestamps
    - User statistics tracking
    - Async database operations for performance
    
    Database Schema:
    - users: User information and message counts
    - messages: Individual message logs with metadata
    """
    
    def __init__(self):
        """
        Initialize the database connection and create tables.
        
        Creates the database file in data/ directory and initializes
        required tables for user and message storage.
        """
        self.db_path = Path('data/azab.db')
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """
        Initialize database tables.
        
        Creates the users and messages tables if they don't exist.
        Sets up proper indexes and constraints for optimal performance.
        """
        conn = sqlite3.connect(self.db_path)
        
        # Users table: Store user information and statistics
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            messages_count INTEGER DEFAULT 0,
            is_imprisoned BOOLEAN DEFAULT 0
        )''')
        
        # Messages table: Store individual message logs
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            channel_id INTEGER,
            guild_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()
        conn.close()
    
    async def log_message(self, user_id: int, username: str, content: str, channel_id: int, guild_id: int):
        """
        Log a Discord message to the database.
        
        Stores the message content, user information, and metadata.
        Updates user statistics including message count.
        
        Args:
            user_id (int): Discord user ID
            username (str): Discord username
            content (str): Message content (truncated to 500 chars)
            channel_id (int): Discord channel ID
            guild_id (int): Discord guild/server ID
        """
        def _log():
            conn = sqlite3.connect(self.db_path)
            
            # Update or insert user information
            conn.execute('INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)',
                        (user_id, username))
            
            # Insert message log with EST timestamp
            est = timezone(timedelta(hours=-5))
            est_timestamp = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute('INSERT INTO messages (user_id, content, channel_id, guild_id, timestamp) VALUES (?, ?, ?, ?, ?)',
                        (user_id, content[:500], channel_id, guild_id, est_timestamp))
            
            # Increment user's message count
            conn.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?',
                        (user_id,))
            
            conn.commit()
            conn.close()
        
        # Run database operations in thread pool to avoid blocking
        await asyncio.to_thread(_log)