#!/usr/bin/env python3
"""
Database module for Calgary Council Stream Recorder.
Manages SQLite database for meetings, recordings, and stream status tracking.

All datetime values are stored in ISO format with timezone information.
When retrieving, they are parsed back to timezone-aware datetime objects.
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager

# Import configuration
from config import DB_DIR, DB_PATH, CALGARY_TZ


def parse_datetime_from_db(dt_str: str) -> datetime:
    """Parse a datetime string from database and ensure it's timezone-aware."""
    dt = datetime.fromisoformat(dt_str)
    # If naive, assume Calgary timezone
    if dt.tzinfo is None:
        dt = CALGARY_TZ.localize(dt)
    return dt


class Database:
    """Database wrapper class for improved testability."""

    def __init__(self, db_path: str = DB_PATH, db_dir: str = DB_DIR):
        """
        Initialize database connection manager.

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
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# Module-level functions for backward compatibility
def ensure_db_directory():
    """Ensure the database directory exists."""
    os.makedirs(DB_DIR, exist_ok=True)


@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize the database schema."""
    ensure_db_directory()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Meetings table - stores all council meetings from the API
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                meeting_datetime TEXT NOT NULL,
                raw_date TEXT NOT NULL,
                link TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(meeting_datetime, title)
            )
        """)

        # Recordings table - tracks all recording attempts and results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER,
                file_path TEXT NOT NULL,
                stream_url TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds INTEGER,
                file_size_bytes INTEGER,
                status TEXT NOT NULL,  -- 'recording', 'completed', 'failed'
                error_message TEXT,
                transcript_path TEXT,
                is_segmented INTEGER DEFAULT 0,  -- 0 = not segmented, 1 = segmented
                created_at TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id)
            )
        """)

        # Segments table - tracks segments created from post-processing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                segment_number INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                start_time_seconds REAL NOT NULL,
                end_time_seconds REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                file_size_bytes INTEGER,
                transcript_path TEXT,
                has_transcript INTEGER DEFAULT 0,  -- 0 = no transcript, 1 = has transcript
                created_at TEXT NOT NULL,
                FOREIGN KEY (recording_id) REFERENCES recordings(id)
            )
        """)

        # Stream status log - tracks when streams go live/offline
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stream_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_url TEXT NOT NULL,
                status TEXT NOT NULL,  -- 'live', 'offline', 'error'
                meeting_id INTEGER,
                timestamp TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id)
            )
        """)

        # Metadata table - stores app metadata like last calendar refresh
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_meetings_datetime
            ON meetings(meeting_datetime)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recordings_meeting_id
            ON recordings(meeting_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recordings_start_time
            ON recordings(start_time)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stream_log_timestamp
            ON stream_status_log(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_recording_id
            ON segments(recording_id)
        """)


def save_meetings(meetings: List[Dict]) -> int:
    """
    Save meetings to database (insert or update).
    Returns the number of meetings saved.
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
                INSERT INTO meetings (title, meeting_datetime, raw_date, link, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_datetime, title)
                DO UPDATE SET
                    raw_date = excluded.raw_date,
                    link = excluded.link,
                    updated_at = excluded.updated_at
            """, (
                meeting['title'],
                meeting_dt.isoformat(),
                meeting['raw_date'],
                meeting.get('link', ''),
                now,
                now
            ))
            saved_count += 1

        return saved_count


def get_upcoming_meetings(limit: int = 50) -> List[Dict]:
    """Get upcoming meetings from database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now(CALGARY_TZ).isoformat()

        cursor.execute("""
            SELECT id, title, meeting_datetime, raw_date, link
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
                'link': row['link']
            })

        return meetings


def find_meeting_by_datetime(meeting_datetime: datetime, tolerance_minutes: int = 30) -> Optional[Dict]:
    """Find a meeting by datetime with tolerance window."""
    from datetime import timedelta

    # Ensure the search datetime is timezone-aware
    if meeting_datetime.tzinfo is None:
        meeting_datetime = CALGARY_TZ.localize(meeting_datetime)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        start_range = (meeting_datetime - timedelta(minutes=tolerance_minutes)).isoformat()
        end_range = (meeting_datetime + timedelta(minutes=tolerance_minutes)).isoformat()

        cursor.execute("""
            SELECT id, title, meeting_datetime, raw_date, link
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
                'link': row['link']
            }
        return None


def create_recording(meeting_id: Optional[int], file_path: str, stream_url: str, start_time: datetime) -> int:
    """Create a new recording record and return its ID."""
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = CALGARY_TZ.localize(start_time)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO recordings (
                meeting_id, file_path, stream_url, start_time,
                status, created_at
            )
            VALUES (?, ?, ?, ?, 'recording', ?)
        """, (
            meeting_id,
            file_path,
            stream_url,
            start_time.isoformat(),
            datetime.now(CALGARY_TZ).isoformat()
        ))

        return cursor.lastrowid


def update_recording(recording_id: int, end_time: datetime, status: str,
                     error_message: Optional[str] = None):
    """Update recording with completion details."""
    # Ensure timezone-aware
    if end_time.tzinfo is None:
        end_time = CALGARY_TZ.localize(end_time)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Calculate duration
        cursor.execute("SELECT start_time FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        if row:
            start_time = parse_datetime_from_db(row['start_time'])
            duration = int((end_time - start_time).total_seconds())
        else:
            duration = None

        # Get file size if file exists
        cursor.execute("SELECT file_path FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()
        file_size = None
        if row and os.path.exists(row['file_path']):
            file_size = os.path.getsize(row['file_path'])

        cursor.execute("""
            UPDATE recordings
            SET end_time = ?,
                duration_seconds = ?,
                file_size_bytes = ?,
                status = ?,
                error_message = ?
            WHERE id = ?
        """, (
            end_time.isoformat(),
            duration,
            file_size,
            status,
            error_message,
            recording_id
        ))


def log_stream_status(stream_url: str, status: str, meeting_id: Optional[int] = None,
                     details: Optional[str] = None):
    """Log stream status change."""
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


def set_metadata(key: str, value: str):
    """Set a metadata value."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, value, datetime.now(CALGARY_TZ).isoformat()))


def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a metadata value."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()

        return row['value'] if row else default


def get_recording_stats() -> Dict:
    """Get recording statistics."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Total recordings
        cursor.execute("SELECT COUNT(*) as count FROM recordings")
        total = cursor.fetchone()['count']

        # Completed recordings
        cursor.execute("SELECT COUNT(*) as count FROM recordings WHERE status = 'completed'")
        completed = cursor.fetchone()['count']

        # Failed recordings
        cursor.execute("SELECT COUNT(*) as count FROM recordings WHERE status = 'failed'")
        failed = cursor.fetchone()['count']

        # Total duration
        cursor.execute("SELECT SUM(duration_seconds) as total FROM recordings WHERE status = 'completed'")
        total_duration = cursor.fetchone()['total'] or 0

        # Total file size
        cursor.execute("SELECT SUM(file_size_bytes) as total FROM recordings WHERE status = 'completed'")
        total_size = cursor.fetchone()['total'] or 0

        return {
            'total_recordings': total,
            'completed': completed,
            'failed': failed,
            'in_progress': total - completed - failed,
            'total_duration_seconds': total_duration,
            'total_size_bytes': total_size,
            'total_size_gb': round(total_size / (1024**3), 2)
        }


def update_recording_transcript(recording_id: int, transcript_path: str):
    """Update recording with transcript file path."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET transcript_path = ?
            WHERE id = ?
        """, (transcript_path, recording_id))


def get_recent_recordings(limit: int = 10) -> List[Dict]:
    """Get recent recordings with meeting details."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.id,
                r.file_path,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                r.file_size_bytes,
                r.status,
                r.transcript_path,
                r.is_segmented,
                m.title as meeting_title,
                m.meeting_datetime
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            ORDER BY r.start_time DESC
            LIMIT ?
        """, (limit,))

        recordings = []
        for row in cursor.fetchall():
            recordings.append({
                'id': row['id'],
                'file_path': row['file_path'],
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration_seconds': row['duration_seconds'],
                'file_size_bytes': row['file_size_bytes'],
                'status': row['status'],
                'transcript_path': row['transcript_path'],
                'is_segmented': row['is_segmented'],
                'meeting_title': row['meeting_title'],
                'meeting_datetime': row['meeting_datetime']
            })

        return recordings


def get_recording_by_id(recording_id: int) -> Optional[Dict]:
    """Get a recording by its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.id,
                r.file_path,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                r.file_size_bytes,
                r.status,
                r.transcript_path,
                r.is_segmented,
                m.id as meeting_id,
                m.title as meeting_title,
                m.meeting_datetime
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            WHERE r.id = ?
        """, (recording_id,))

        row = cursor.fetchone()
        if row:
            return {
                'id': row['id'],
                'file_path': row['file_path'],
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration_seconds': row['duration_seconds'],
                'file_size_bytes': row['file_size_bytes'],
                'status': row['status'],
                'transcript_path': row['transcript_path'],
                'is_segmented': row['is_segmented'],
                'meeting_id': row['meeting_id'],
                'meeting_title': row['meeting_title'],
                'meeting_datetime': row['meeting_datetime']
            }
        return None


def create_segment(recording_id: int, segment_number: int, file_path: str,
                  start_time: float, end_time: float, duration: float,
                  file_size_bytes: Optional[int] = None) -> int:
    """Create a new segment record and return its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO segments (
                recording_id, segment_number, file_path,
                start_time_seconds, end_time_seconds, duration_seconds,
                file_size_bytes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            recording_id,
            segment_number,
            file_path,
            start_time,
            end_time,
            duration,
            file_size_bytes,
            datetime.now(CALGARY_TZ).isoformat()
        ))

        return cursor.lastrowid


def get_segments_by_recording(recording_id: int) -> List[Dict]:
    """Get all segments for a recording."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                recording_id,
                segment_number,
                file_path,
                start_time_seconds,
                end_time_seconds,
                duration_seconds,
                file_size_bytes,
                transcript_path,
                has_transcript,
                created_at
            FROM segments
            WHERE recording_id = ?
            ORDER BY segment_number ASC
        """, (recording_id,))

        segments = []
        for row in cursor.fetchall():
            segments.append({
                'id': row['id'],
                'recording_id': row['recording_id'],
                'segment_number': row['segment_number'],
                'file_path': row['file_path'],
                'start_time_seconds': row['start_time_seconds'],
                'end_time_seconds': row['end_time_seconds'],
                'duration_seconds': row['duration_seconds'],
                'file_size_bytes': row['file_size_bytes'],
                'transcript_path': row['transcript_path'],
                'has_transcript': row['has_transcript'],
                'created_at': row['created_at']
            })

        return segments


def mark_recording_segmented(recording_id: int):
    """Mark a recording as having been segmented."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET is_segmented = 1
            WHERE id = ?
        """, (recording_id,))


def update_segment_transcript(segment_id: int, transcript_path: str):
    """Update segment with transcript file path."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE segments
            SET transcript_path = ?, has_transcript = 1
            WHERE id = ?
        """, (transcript_path, segment_id))


if __name__ == '__main__':
    # Initialize database when run directly
    print("Initializing database...")
    init_database()
    print(f"Database initialized at: {DB_PATH}")

    # Show stats
    stats = get_recording_stats()
    print("\nDatabase Statistics:")
    print(f"  Total recordings: {stats['total_recordings']}")
    print(f"  Completed: {stats['completed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  In progress: {stats['in_progress']}")
    print(f"  Total duration: {stats['total_duration_seconds']} seconds")
    print(f"  Total size: {stats['total_size_gb']} GB")
