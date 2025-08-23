"""
Database Connection Pool for AzabBot
=====================================

Provides connection pooling for SQLite with async support.
"""

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import time
from collections import deque
from src.core.logger import get_logger

class DatabasePool:
    """Async SQLite connection pool."""
    
    def __init__(self, db_path: Path, max_connections: int = 5):
        """Initialize connection pool."""
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = deque(maxlen=max_connections)
        self.semaphore = asyncio.Semaphore(max_connections)
        self.connections_created = 0
        self.logger = get_logger()
        self._closed = False
        
    async def _create_connection(self):
        """Create a new database connection."""
        loop = asyncio.get_event_loop()
        conn = await loop.run_in_executor(
            None,
            lambda: sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None
            )
        )
        conn.row_factory = sqlite3.Row
        self.connections_created += 1
        self.logger.log_debug(
            f"Created connection #{self.connections_created} to database",
            context={"total_connections": self.connections_created}
        )
        return conn
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool."""
        if self._closed:
            raise RuntimeError("Connection pool is closed")
            
        start_time = time.perf_counter()
        async with self.semaphore:
            conn = None
            try:
                # Try to get existing connection
                if self.pool:
                    conn = self.pool.popleft()
                    # Test if connection is still valid
                    try:
                        conn.execute("SELECT 1")
                    except sqlite3.Error:
                        conn.close()
                        conn = None
                
                # Create new connection if needed
                if conn is None:
                    conn = await self._create_connection()
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                if elapsed_ms > 100:
                    self.logger.log_debug(
                        f"Connection acquired in {elapsed_ms:.1f}ms",
                        context={"pool_size": len(self.pool)}
                    )
                
                yield conn
                
            finally:
                # Return connection to pool
                if conn and not self._closed:
                    try:
                        # Reset connection state
                        conn.rollback()
                        self.pool.append(conn)
                    except sqlite3.Error:
                        conn.close()
    
    async def close(self):
        """Close all connections in the pool."""
        self._closed = True
        while self.pool:
            conn = self.pool.popleft()
            conn.close()
        self.logger.log_info(f"Closed connection pool with {self.connections_created} total connections created")