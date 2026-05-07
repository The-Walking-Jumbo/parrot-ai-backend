import logging
import asyncio
from typing import Optional, List, Dict, Any
import libsql_experimental as libsql
from core.config import settings

logger = logging.getLogger(__name__)

class DatabaseClient:
    def __init__(self):
        self.url = settings.DATABASE_URL
        self.auth_token = settings.TURSO_AUTH_TOKEN
        self.client = None
    
    def connect(self):
        """Create connection to Turso database"""
        if not self.client:
            try:
                self.client = libsql.connect(
                    database=self.url,
                    auth_token=self.auth_token
                )
            except Exception as e:
                logger.error(f"Failed to connect to Turso database: {e}")
                raise e
        return self.client
    
    def close(self):
        """Close database connection"""
        if self.client:
            self.client = None
    
    def _execute_sync(self, query: str, params: Optional[list] = None):
        """Internal synchronous execute logic"""
        if not self.client:
            self.connect()
        
        try:
            if params:
                result = self.client.execute(query, params)
            else:
                result = self.client.execute(query)
            self.client.commit()
            return result
        except Exception as e:
            logger.error(f"Database query error: {e} | Query: {query} | Params: {params}")
            raise e

    async def execute(self, query: str, params: Optional[list] = None):
        """Execute a query asynchronously in a separate thread"""
        return await asyncio.to_thread(self._execute_sync, query, params)

    async def fetch_all(self, query: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
        """Execute query and return list of dictionaries"""
        result = await self.execute(query, params)
        return [dict(zip(result.columns, row)) for row in result.rows]

    async def fetch_one(self, query: str, params: Optional[list] = None) -> Optional[Dict[str, Any]]:
        """Execute query and return a single dictionary or None"""
        result = await self.execute(query, params)
        if not result.rows:
            return None
        return dict(zip(result.columns, result.rows[0]))

# Global instance
db_client = DatabaseClient()

def get_db():
    """Dependency for FastAPI routes"""
    try:
        db_client.connect()
        yield db_client
    except Exception as e:
        logger.error(f"Error in get_db dependency: {e}")
        raise