"""
Base repository pattern for database operations.
Reduces code duplication across services.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from src.utils.time_utils import now_est_naive
from src.utils.error_handler import (
    handle_error, ErrorCategory, ErrorSeverity, AzabBotError
)
from src.core.logger import get_logger

logger = get_logger()


class BaseRepository:
    """Base repository with common database operations."""
    
    def __init__(self, db_service):
        """
        Initialize repository with database service.
        
        Args:
            db_service: DatabaseService instance
        """
        self.db_service = db_service
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.HIGH,
        max_retries=2,
        retry_delay=1.0
    )
    async def fetch_one(
        self,
        query: str,
        params: Optional[Tuple] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a single row from database with error handling.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            Dict or None if not found
        """
        if not self.db_service:
            raise AzabBotError(
                "Database service not available",
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH
            )
        
        result = await self.db_service.fetch_one(query, params)
        return dict(result) if result else None
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.HIGH,
        max_retries=2,
        default_return=[]
    )
    async def fetch_all(
        self,
        query: str,
        params: Optional[Tuple] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch multiple rows from database with error handling.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            List of dicts
        """
        if not self.db_service:
            raise AzabBotError(
                "Database service not available",
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH
            )
        
        results = await self.db_service.fetch_all(query, params)
        return [dict(row) for row in results]
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.HIGH,
        max_retries=2,
        default_return=False
    )
    async def execute(
        self,
        query: str,
        params: Optional[Tuple] = None
    ) -> bool:
        """
        Execute a database query with error handling.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            True if successful, False otherwise
        """
        if not self.db_service:
            raise AzabBotError(
                "Database service not available",
                category=ErrorCategory.DATABASE,
                severity=ErrorSeverity.HIGH
            )
        
        await self.db_service.execute(query, params)
        return True
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=None
    )
    async def get_or_create(
        self,
        table: str,
        lookup_fields: Dict[str, Any],
        create_fields: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get existing record or create new one.
        
        Args:
            table: Table name
            lookup_fields: Fields to search by
            create_fields: Additional fields for creation
            
        Returns:
            Record dict or None
        """
        # Build lookup query
        where_clause = " AND ".join([f"{k} = ?" for k in lookup_fields.keys()])
        query = f"SELECT * FROM {table} WHERE {where_clause}"
        
        # Try to fetch existing
        existing = await self.fetch_one(query, tuple(lookup_fields.values()))
        if existing:
            return existing
        
        # Create new record
        all_fields = {**lookup_fields, **(create_fields or {})}
        
        # Add timestamps if not present
        if "created_at" not in all_fields:
            all_fields["created_at"] = now_est_naive()
        
        columns = ", ".join(all_fields.keys())
        placeholders = ", ".join(["?" for _ in all_fields])
        insert_query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        success = await self.execute(insert_query, tuple(all_fields.values()))
        
        if success:
            # Fetch the created record
            return await self.fetch_one(query, tuple(lookup_fields.values()))
        
        return None
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=False
    )
    async def update(
        self,
        table: str,
        update_fields: Dict[str, Any],
        where_fields: Dict[str, Any]
    ) -> bool:
        """
        Update records in database.
        
        Args:
            table: Table name
            update_fields: Fields to update
            where_fields: WHERE clause fields
            
        Returns:
            True if successful
        """
        # Add updated_at if table might have it
        if "updated_at" not in update_fields:
            update_fields["updated_at"] = now_est_naive()
        
        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        where_clause = " AND ".join([f"{k} = ?" for k in where_fields.keys()])
        
        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = tuple(list(update_fields.values()) + list(where_fields.values()))
        
        return await self.execute(query, params)
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=False
    )
    async def delete(
        self,
        table: str,
        where_fields: Dict[str, Any]
    ) -> bool:
        """
        Delete records from database.
        
        Args:
            table: Table name
            where_fields: WHERE clause fields
            
        Returns:
            True if successful
        """
        where_clause = " AND ".join([f"{k} = ?" for k in where_fields.keys()])
        query = f"DELETE FROM {table} WHERE {where_clause}"
        
        return await self.execute(query, tuple(where_fields.values()))
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=0
    )
    async def count(
        self,
        table: str,
        where_fields: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Count records in table.
        
        Args:
            table: Table name
            where_fields: Optional WHERE clause fields
            
        Returns:
            Count of records
        """
        if where_fields:
            where_clause = " AND ".join([f"{k} = ?" for k in where_fields.keys()])
            query = f"SELECT COUNT(*) as count FROM {table} WHERE {where_clause}"
            params = tuple(where_fields.values())
        else:
            query = f"SELECT COUNT(*) as count FROM {table}"
            params = None
        
        result = await self.fetch_one(query, params)
        return result["count"] if result else 0
    
    async def transaction(self, operations: List[Tuple[str, Optional[Tuple]]]) -> bool:
        """
        Execute multiple operations in a transaction.
        
        Args:
            operations: List of (query, params) tuples
            
        Returns:
            True if all successful, rolls back on any failure
        """
        try:
            # Start transaction
            await self.db_service.execute("BEGIN TRANSACTION")
            
            # Execute all operations
            for query, params in operations:
                await self.db_service.execute(query, params)
            
            # Commit if all successful
            await self.db_service.execute("COMMIT")
            return True
            
        except Exception as e:
            # Rollback on any error
            try:
                await self.db_service.execute("ROLLBACK")
            except:
                pass
            
            logger.log_error(
                "Transaction failed, rolled back",
                exception=e,
                context={"operations_count": len(operations)}
            )
            return False