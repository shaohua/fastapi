"""
Database connection and query utilities for VS Code Extension Stats.
"""

import os
import asyncio
from contextlib import asynccontextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost/vscode_stats')

# Global connection pool
pool = None

async def init_db():
    """Initialize database connection pool."""
    global pool
    pool = AsyncConnectionPool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row}
    )
    await pool.wait()

async def close_db():
    """Close database connection pool."""
    global pool
    if pool:
        await pool.close()

@asynccontextmanager
async def get_db():
    """Get database connection from pool."""
    async with pool.connection() as conn:
        yield conn

async def fetch_all(query: str, *args):
    """Execute query and return all results."""
    async with get_db() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchall()

async def fetch_one(query: str, *args):
    """Execute query and return first result."""
    async with get_db() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchone()

async def execute_query(query: str, *args):
    """Execute a query (INSERT, UPDATE, DELETE) and return affected rows."""
    async with get_db() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            await conn.commit()
            return cur.rowcount

async def check_timestamp_exists(captured_at):
    """Check if any records exist with the given captured_at timestamp."""
    # PostgreSQL TIMESTAMPTZ handles timezone-aware comparisons automatically
    # It will convert both sides to UTC for comparison
    query = "SELECT COUNT(*) as count FROM extension_stats WHERE captured_at = %s"
    result = await fetch_one(query, captured_at)
    return result['count'] > 0 if result else False
