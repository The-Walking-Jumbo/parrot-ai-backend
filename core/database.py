import os
import libsql
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ResultSet:
    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns

class DatabaseClient:
    def __init__(self):
        self.url = os.getenv("TURSO_DATABASE_URL")
        self.auth_token = os.getenv("TURSO_AUTH_TOKEN")
        self.conn = None

        # Validate configuration
        if not self.url:
            raise ValueError("TURSO_DATABASE_URL environment variable is not set")
        if not self.auth_token:
            raise ValueError("TURSO_AUTH_TOKEN environment variable is not set")

        logger.info(f"Database URL: {self.url}")

    def connect(self):
        """Create connection to Turso database"""
        if not self.conn:
            try:
                self.conn = libsql.connect(
                    database="local.db",
                    sync_url=self.url,
                    auth_token=self.auth_token,
                )
                self.conn.sync()
                logger.info("✅ Database connection established")
            except Exception as e:
                logger.error(f"❌ Database connection failed: {str(e)}")
                raise

        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    async def execute(self, query: str, params: Optional[list] = None):
        """Execute a query with parameters asynchronously"""
        if not self.conn:
            self.connect()

        try:
            def _exec():
                if params:
                    cursor = self.conn.execute(query, params)
                else:
                    cursor = self.conn.execute(query)
                rows = cursor.fetchall() if cursor.description else []
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                return ResultSet(rows, columns)
            return await asyncio.to_thread(_exec)
        except Exception as e:
            logger.error(
                f"Database query error: {str(e)} | Query: {query} | Params: {params}"
            )
            raise

    async def fetch_all(self, query: str, params: Optional[list] = None):
        """Fetch all rows as a list of dicts"""
        result = await self.execute(query, params)
        if result and result.rows:
            return [dict(zip(result.columns, row)) for row in result.rows]
        return []

    async def fetch_one(self, query: str, params: Optional[list] = None):
        """Fetch a single row as a dict"""
        result = await self.execute(query, params)
        if result and result.rows:
            return dict(zip(result.columns, result.rows[0]))
        return None

# Global instance
db_client = DatabaseClient()

def get_db():
    """FastAPI dependency"""
    try:
        conn = db_client.connect()
        yield conn
    except Exception as e:
        logger.error(f"Error in get_db dependency: {str(e)}")
        raise