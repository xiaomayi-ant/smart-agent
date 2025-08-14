"""
Database connection and query utilities
"""
import asyncio
import mysql.connector
from typing import List, Dict, Any, Optional
from mysql.connector import pooling
from ..core.config import get_mysql_config


class DatabaseManager:
    """Database connection manager"""
    
    def __init__(self):
        self.config = get_mysql_config()
        self.pool = None
        self._init_pool()
    
    def _init_pool(self):
        """Initialize connection pool"""
        try:
            self.pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="financial_pool",
                pool_size=5,
                **self.config
            )
            print(f"[Database] Connection pool initialized successfully")
        except Exception as e:
            print(f"[Database] Failed to initialize connection pool: {e}")
            print(f"[Database] Database features will be disabled")
            self.pool = None
    
    def get_connection(self):
        """Get a connection from the pool"""
        if not self.pool:
            self._init_pool()
        return self.pool.get_connection()
    
    async def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a query and return results"""
        def _execute():
            conn = self.get_connection()
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, params or ())
                results = cursor.fetchall()
                cursor.close()
                return results
            finally:
                conn.close()
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _execute)
    
    async def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """Execute multiple queries"""
        def _execute():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.executemany(query, params_list)
                conn.commit()
                affected_rows = cursor.rowcount
                cursor.close()
                return affected_rows
            finally:
                conn.close()
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _execute)


# Global database manager instance
db_manager = DatabaseManager()


