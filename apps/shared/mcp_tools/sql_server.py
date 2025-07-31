import logging
import re
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urlparse, urlunparse

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from typing_extensions import LiteralString

logger = logging.getLogger(__name__)

def obfuscate_passowrd(text: str | None) -> str | None:
    """
    Obfuscate password in any text containing connection information.
    Works on connection URLs, error messages, and other strings.
    """
    if text is None:
        return None
    
    if not text:
        return text
    
    try:
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc and parsed.password:
            # Replace password with asterisks in proper URL
            netloc = parsed.netloc.replace(parsed.password, "****")
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    # Handle strings that contain connection strings but aren't proper URLs
    # Match postgres://user:password@host:port/dbname pattern
    url_pattern = re.compile(r"(postgres(?:ql)?:\/\/[^:]+:)([^@]+)(@[^\/\s]+)")
    text = re.sub(url_pattern, r"\1****\3", text)

    # Match connection string parameters (password=xxx)
    # This simpler pattern captures password without quotes
    param_pattern = re.compile(r'(password=)([^\s&;"\']+)', re.IGNORECASE)
    text = re.sub(param_pattern, r"\1****", text)

    # Match password in DSN format with single quotes
    dsn_single_quote = re.compile(r"(password\s*=\s*')([^']+)(')", re.IGNORECASE)
    text = re.sub(dsn_single_quote, r"\1****\3", text)

    # Match password in DSN format with double quotes
    dsn_double_quote = re.compile(r'(password\s*=\s*")([^"]+)(")', re.IGNORECASE)
    text = re.sub(dsn_double_quote, r"\1****\3", text)

    return text


class DbConnectionPool:
    """Database connection pool"""
    def __init__(self, connection_url:Optional[str]=None):
        self.connection_url = connection_url
        self.pool: AsyncConnectionPool | None = None
        self._is_valid = False
        self._last_error = None
    async def pool_connect(self, connection_url: Optional[str]=None) -> AsyncConnectionPool:
        """Initialize the connection pool with retry logic"""
        if self.pool and self._is_valid:
            return self.pool
        
        url = connection_url or self.connection_url
        self.connection_url = url
        if not url:
            self._is_valid = False
            self._last_error = "No connection URL provided"
            return ValueError(self._last_error)
        #close any existing pool before creating a new one
        try:
            self.pool = AsyncConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=5,
                open=False, #Don't open the pool until we need it
            )

            await self.pool.open()

            async with self.pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            self._is_valid = True
            self._last_error = None
            return self.pool
        except Exception as e:
            self._is_valid=False
            self._last_error = str(e)

            #clean up the pool
            await self.close()

            return ValueError(f"Failed to connect to database: {obfuscate_passowrd(self._last_error)}")
        
    async def close(self):
        """Close the pool"""
        if self.pool:
            try:
                await self.pool.close()
            except Exception as e:
                logging.error(f"Error closing pool: {e}")
            finally:
                self.pool = None
                self._is_valid = False

    @property
    def is_valid(self) -> bool:
        """Checking if the connection pool is valid"""
        return self._is_valid
    
    @property
    def last_error(self) -> str | None:
        """Last error message"""
        return self._last_error
        

class SqlDriver:
    """SQL driver for the database"""
    @dataclass
    class RowResult:
        """Simple class to match the Griptape RowResult interface."""

        cells: Dict[str, Any]
    def __init__(self, 
                 conn: Any=None,
                 engine_url: str=None,
    ):
        """
        Initialize with a PostgreSQL connection or pool.

        Args:
            conn: PostgreSQL connection object or pool
            engine_url: Connection URL string as an alternative to providing a connection
        """
        if conn:
            self.conn = conn
            self.is_pool = isinstance(conn, DbConnectionPool)
        elif engine_url:
            # Don't connect here since we need async connection
            self.engnie_url = engine_url
            self.conn = None
            self.is_pool = False
        else:
            raise ValueError("Either conn or engine_url must be provided")
        
    def connect(self):
        """Connect to the database"""
        if self.conn is not None:
            return self.conn
        if self.engnie_url:
            self.conn = DbConnectionPool(self.engnie_url)
            self.is_pool = True
            return self.conn
        else:
            raise ValueError("Connection not established. Either conn or engine_url must be provided")
           
    async def execute_query(self,
                      query: LiteralString,
                      params: List[Any]=None,
                      force_readonly:bool=False,
                      ) -> Optional[List[RowResult]]:
        """
        Execute a query and return results.

        Args:
            query: SQL query to execute
            params: Query parameters
            force_readonly: Whether to enforce read-only mode

        Returns:
            List of RowResult objects or None on error
        """
        try:
            if self.conn is None:
                self.connect()
                if self.conn is None:
                    raise ValueError("Failed to connect to the database")
                
            # Handle connection pool vs direct connection
            if self.is_pool:
                pool = await self.conn.pool_connect()
                async with pool.connection() as connection:
                    return await self._execute_with_connection(connection, query,force_readonly=force_readonly)
                
            else:
                return await self._execute_with_connection(self.conn, query, force_readonly=force_readonly)
        except Exception as e:
            # Mark pool as invalid if there was a connection issue
            if self.conn and self.is_pool:
                self.conn._is_valid = False  # type: ignore
                self.conn._last_error = str(e)  # type: ignore
            elif self.conn and not self.is_pool:
                self.conn = None

            raise e
        
    async def _execute_with_connection(self,
                                      connection: Any,
                                      query: LiteralString,
                                      params: List[Any]=None,
                                      force_readonly:bool=False,
                                      ) -> Optional[List[RowResult]]:
        """
        Execute a query with a given connection.
        """
        transaction_started = False
        try:
            async with connection.cursor(row_factory=dict_row) as cursor:
                if force_readonly:
                    await cursor.execute("BEGIN TRANSACTION READ ONLY")
                    transaction_started = True

                if params:
                    await cursor.execute(query, params)
                else:
                    await cursor.execute(query)

                while cursor.nextset():
                    pass
                
                if cursor.description is None:
                    if not force_readonly:
                            await cursor.execute("COMMIT")
                    elif transaction_started:
                            await cursor.execute("ROLLBACK")
                            transaction_started = False
                    return None
                
                # Get results from the last statement only
                rows = await cursor.fetchall()

                if not force_readonly:
                        await cursor.execute("COMMIT")
                elif transaction_started:
                        await cursor.execute("ROLLBACK")
                        transaction_started = False

                return [SqlDriver.RowResult(cells=dict(row)) for row in rows]
        except Exception as e:
            if transaction_started:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    logger.error(f"Error rolling back transaction: {rollback_error}")

            logger.error(f"Error executing query ({query}): {e}")
            raise e


                    
                    