"""Meeting repository for database operations."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import CALGARY_TZ
from database.connection import get_db_connection, parse_datetime_from_db

logger = logging.getLogger(__name__)


def save_meetings(meetings: List[Dict]) -> int:
    """Save meetings to database (insert or update).

    Args:
        meetings: List of meeting dictionaries with datetime, title, etc.

    Returns:
        Number of meetings saved
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now(CALGARY_TZ).isoformat()
        saved_count = 0

        for meeting in meetings:
            # Ensure datetime has timezone info before storing
            meeting_dt = meeting['datetime']
            if meeting_dt.tzinfo is None:
                meeting_dt = CALGARY_TZ.localize(meeting_dt)

            cursor.execute("""
                INSERT INTO meetings (title, meeting_datetime, raw_date, link, room, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_datetime, title)
                DO UPDATE SET
                    raw_date = excluded.raw_date,
                    link = excluded.link,
                    room = excluded.room,
                    updated_at = excluded.updated_at
            """, (
                meeting['title'],
                meeting_dt.isoformat(),
                meeting['raw_date'],
                meeting.get('link', ''),
                meeting.get('room', ''),
                now,
                now
            ))
            saved_count += 1

        return saved_count


def get_upcoming_meetings(limit: int = 50) -> List[Dict]:
    """Get upcoming meetings from database.

    Args:
        limit: Maximum number of meetings to return

    Returns:
        List of meeting dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now(CALGARY_TZ).isoformat()

        cursor.execute("""
            SELECT id, title, meeting_datetime, raw_date, link, room
            FROM meetings
            WHERE meeting_datetime >= ?
            ORDER BY meeting_datetime ASC
            LIMIT ?
        """, (now, limit))

        meetings = []
        for row in cursor.fetchall():
            meetings.append({
                'id': row['id'],
                'title': row['title'],
                'datetime': parse_datetime_from_db(row['meeting_datetime']),
                'raw_date': row['raw_date'],
                'link': row['link'],
                'room': row['room']
            })

        return meetings


def find_meeting_by_datetime(meeting_datetime: datetime, tolerance_minutes: int = 30) -> Optional[Dict]:
    """Find a meeting by datetime with tolerance window.

    Args:
        meeting_datetime: Datetime to search for
        tolerance_minutes: Tolerance window in minutes

    Returns:
        Meeting dictionary if found, None otherwise
    """
    # Ensure the search datetime is timezone-aware
    if meeting_datetime.tzinfo is None:
        meeting_datetime = CALGARY_TZ.localize(meeting_datetime)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        start_range = (meeting_datetime - timedelta(minutes=tolerance_minutes)).isoformat()
        end_range = (meeting_datetime + timedelta(minutes=tolerance_minutes)).isoformat()

        cursor.execute("""
            SELECT id, title, meeting_datetime, raw_date, link, room
            FROM meetings
            WHERE meeting_datetime BETWEEN ? AND ?
            ORDER BY ABS(CAST((julianday(meeting_datetime) - julianday(?)) * 1440 AS INTEGER))
            LIMIT 1
        """, (start_range, end_range, meeting_datetime.isoformat()))

        row = cursor.fetchone()
        if row:
            return {
                'id': row['id'],
                'title': row['title'],
                'datetime': parse_datetime_from_db(row['meeting_datetime']),
                'raw_date': row['raw_date'],
                'link': row['link'],
                'room': row['room']
            }
        return None
