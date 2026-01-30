"""Metadata repository for database operations."""

import logging
from datetime import datetime
from typing import Optional

from config import CALGARY_TZ
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def set_metadata(key: str, value: str) -> None:
    """Set a metadata value.

    Args:
        key: Metadata key
        value: Metadata value
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, value, datetime.now(CALGARY_TZ).isoformat()))


def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a metadata value.

    Args:
        key: Metadata key
        default: Default value if key not found

    Returns:
        Metadata value if found, default otherwise
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()

        return row['value'] if row else default
