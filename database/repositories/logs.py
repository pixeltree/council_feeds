"""Logging repository for database operations."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import CALGARY_TZ
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def log_stream_status(stream_url: str, status: str, meeting_id: Optional[int] = None,
                     details: Optional[str] = None) -> None:
    """Log stream status change.

    Args:
        stream_url: URL of the stream
        status: Status ('live', 'offline', 'error')
        meeting_id: Optional associated meeting ID
        details: Optional status details
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO stream_status_log (stream_url, status, meeting_id, timestamp, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            stream_url,
            status,
            meeting_id,
            datetime.now(CALGARY_TZ).isoformat(),
            details
        ))


def add_recording_log(recording_id: int, message: str, level: str = 'info') -> None:
    """Add a log message to the recording logs.

    Args:
        recording_id: Recording ID
        message: Log message
        level: Log level ('info', 'warning', 'error')
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        now = datetime.now(CALGARY_TZ).isoformat()
        cursor.execute("""
            INSERT INTO recording_logs (recording_id, timestamp, level, message)
            VALUES (?, ?, ?, ?)
        """, (recording_id, now, level, message))


def get_recording_logs(recording_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Get log messages for a recording in reverse chronological order.

    Args:
        recording_id: Recording ID
        limit: Maximum number of logs to return

    Returns:
        List of log dictionaries with timestamp, level, and message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, timestamp, level, message
            FROM recording_logs
            WHERE recording_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (recording_id, limit))

        logs = []
        for row in cursor.fetchall():
            logs.append({
                'id': row['id'],
                'timestamp': row['timestamp'],
                'level': row['level'],
                'message': row['message']
            })

        return logs
