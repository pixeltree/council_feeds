"""Database connection management."""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import config
from exceptions import DatabaseConnectionError, DatabaseQueryError

logger = logging.getLogger(__name__)

# Module-level references that can be overridden for testing
CALGARY_TZ = config.CALGARY_TZ
DB_DIR = config.DB_DIR
DB_PATH = config.DB_PATH


def parse_datetime_from_db(dt_str: str) -> datetime:
    """Parse a datetime string from database and ensure it's timezone-aware.

    Args:
        dt_str: ISO format datetime string from database

    Returns:
        Timezone-aware datetime object
    """
    dt = datetime.fromisoformat(dt_str)
    # If naive, assume Calgary timezone
    if dt.tzinfo is None:
        dt = CALGARY_TZ.localize(dt)
    return dt


class Database:
    """Database wrapper class for improved testability."""

    def __init__(self, db_path: str = DB_PATH, db_dir: str = DB_DIR):
        """Initialize database connection manager.

        Args:
            db_path: Path to SQLite database file
            db_dir: Directory containing the database
        """
        self.db_path = db_path
        self.db_dir = db_dir

    def ensure_db_directory(self):
        """Ensure the database directory exists."""
        os.makedirs(self.db_dir, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Yields:
            Database connection with row factory enabled

        Raises:
            DatabaseConnectionError: If connection fails
            DatabaseQueryError: If query execution fails
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Enable column access by name
        except sqlite3.Error as e:
            raise DatabaseConnectionError(self.db_path, str(e))

        try:
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise DatabaseQueryError(error=str(e))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def ensure_db_directory():
    """Ensure the database directory exists."""
    # Import here to get the potentially-monkeypatched value
    import database
    os.makedirs(database.DB_DIR, exist_ok=True)


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections.

    Yields:
        Database connection with row factory enabled

    Raises:
        DatabaseConnectionError: If connection fails
        DatabaseQueryError: If query execution fails
    """
    # Import here to get the potentially-monkeypatched value
    import database
    ensure_db_directory()
    try:
        conn = sqlite3.connect(database.DB_PATH)
        conn.row_factory = sqlite3.Row  # Enable column access by name
    except sqlite3.Error as e:
        raise DatabaseConnectionError(database.DB_PATH, str(e))

    try:
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise DatabaseQueryError(error=str(e))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
