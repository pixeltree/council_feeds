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
    ensure_db_directory()
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
                room TEXT,
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

        # Recording logs table - stores all log messages for recordings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recording_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,  -- 'info', 'warning', 'error'
                message TEXT NOT NULL,
                FOREIGN KEY (recording_id) REFERENCES recordings(id)
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

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recording_logs_recording_id
            ON recording_logs(recording_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recording_logs_timestamp
            ON recording_logs(timestamp)
        """)

        # Migration: Add room column to meetings table if it doesn't exist
        cursor.execute("PRAGMA table_info(meetings)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'room' not in columns:
            cursor.execute("ALTER TABLE meetings ADD COLUMN room TEXT")

        # Migration: Add post-processing tracking columns to recordings table
        cursor.execute("PRAGMA table_info(recordings)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'post_process_status' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_status TEXT DEFAULT 'pending'")  # 'pending', 'processing', 'completed', 'failed', 'skipped'
        if 'post_process_attempted_at' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_attempted_at TEXT")
        if 'post_process_error' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_error TEXT")

        # Migration: Add transcription tracking columns to recordings table
        if 'transcription_status' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_status TEXT DEFAULT 'pending'")  # 'pending', 'processing', 'completed', 'failed', 'skipped'
        if 'transcription_attempted_at' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_attempted_at TEXT")
        if 'transcription_error' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_error TEXT")
        if 'transcription_progress' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_progress TEXT")  # JSON string with progress details
        if 'transcription_logs' not in columns:
            cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_logs TEXT")  # JSON array of log messages


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
    """Get upcoming meetings from database."""
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
                r.post_process_status,
                r.post_process_attempted_at,
                r.post_process_error,
                r.transcription_status,
                r.transcription_attempted_at,
                r.transcription_error,
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
                'post_process_status': row['post_process_status'],
                'post_process_attempted_at': row['post_process_attempted_at'],
                'post_process_error': row['post_process_error'],
                'transcription_status': row['transcription_status'],
                'transcription_attempted_at': row['transcription_attempted_at'],
                'transcription_error': row['transcription_error'],
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
                r.post_process_status,
                r.post_process_attempted_at,
                r.post_process_error,
                r.transcription_status,
                r.transcription_attempted_at,
                r.transcription_error,
                r.transcription_progress,
                r.transcription_logs,
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
                'post_process_status': row['post_process_status'],
                'post_process_attempted_at': row['post_process_attempted_at'],
                'post_process_error': row['post_process_error'],
                'transcription_status': row['transcription_status'],
                'transcription_attempted_at': row['transcription_attempted_at'],
                'transcription_error': row['transcription_error'],
                'transcription_progress': row['transcription_progress'],
                'transcription_logs': row['transcription_logs'],
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


def update_post_process_status(recording_id: int, status: str, error: Optional[str] = None):
    """Update post-processing status for a recording.

    Args:
        recording_id: Recording ID
        status: Status ('pending', 'processing', 'completed', 'failed', 'skipped')
        error: Optional error message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        now = datetime.now(CALGARY_TZ).isoformat()

        cursor.execute("""
            UPDATE recordings
            SET post_process_status = ?,
                post_process_attempted_at = ?,
                post_process_error = ?
            WHERE id = ?
        """, (status, now, error, recording_id))


def get_unprocessed_recordings(limit: int = 50) -> List[Dict]:
    """Get completed recordings that haven't been post-processed yet.

    Args:
        limit: Maximum number of recordings to return

    Returns:
        List of recording dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.id,
                r.meeting_id,
                r.file_path,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                r.file_size_bytes,
                r.status,
                r.is_segmented,
                r.post_process_status,
                r.post_process_attempted_at,
                r.post_process_error,
                m.title as meeting_title
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            WHERE r.status = 'completed'
            AND (r.post_process_status IS NULL OR r.post_process_status IN ('pending', 'failed'))
            ORDER BY r.start_time DESC
            LIMIT ?
        """, (limit,))

        recordings = []
        for row in cursor.fetchall():
            recordings.append({
                'id': row['id'],
                'meeting_id': row['meeting_id'],
                'file_path': row['file_path'],
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration_seconds': row['duration_seconds'],
                'file_size_bytes': row['file_size_bytes'],
                'status': row['status'],
                'is_segmented': row['is_segmented'],
                'post_process_status': row['post_process_status'],
                'post_process_attempted_at': row['post_process_attempted_at'],
                'post_process_error': row['post_process_error'],
                'meeting_title': row['meeting_title']
            })

        return recordings


def get_stale_recordings() -> List[Dict]:
    """Get recordings that are stale (status='recording' but file doesn't exist or has no content).

    Returns:
        List of stale recording dictionaries with file existence check
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.id,
                r.meeting_id,
                r.file_path,
                r.start_time,
                r.duration_seconds,
                r.file_size_bytes,
                r.status,
                m.title as meeting_title
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            WHERE r.status = 'recording'
            OR (r.status = 'completed' AND (r.duration_seconds IS NULL OR r.duration_seconds = 0 OR r.file_size_bytes IS NULL OR r.file_size_bytes < 1000))
            ORDER BY r.start_time DESC
        """)

        stale_recordings = []
        for row in cursor.fetchall():
            file_exists = os.path.exists(row['file_path'])
            file_size = os.path.getsize(row['file_path']) if file_exists else 0

            # Consider stale if file doesn't exist, or exists but is tiny (< 1KB)
            is_stale = not file_exists or file_size < 1000

            if is_stale:
                stale_recordings.append({
                    'id': row['id'],
                    'meeting_id': row['meeting_id'],
                    'file_path': row['file_path'],
                    'start_time': row['start_time'],
                    'duration_seconds': row['duration_seconds'],
                    'file_size_bytes': row['file_size_bytes'],
                    'status': row['status'],
                    'meeting_title': row['meeting_title'],
                    'file_exists': file_exists,
                    'actual_file_size': file_size
                })

        return stale_recordings


def get_orphaned_files(recordings_dir: str = None) -> List[Dict]:
    """Get files in recordings directory that have no database entry.

    Args:
        recordings_dir: Directory to scan (defaults to OUTPUT_DIR from config)

    Returns:
        List of orphaned file dictionaries with file info
    """
    from config import OUTPUT_DIR
    if recordings_dir is None:
        recordings_dir = OUTPUT_DIR

    if not os.path.exists(recordings_dir):
        return []

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get all file paths from database
        cursor.execute("SELECT file_path FROM recordings")
        db_files = {row['file_path'] for row in cursor.fetchall()}

        # Also get segment file paths
        cursor.execute("SELECT file_path FROM segments")
        db_files.update(row['file_path'] for row in cursor.fetchall())

    orphaned_files = []

    # Scan recordings directory
    for root, dirs, files in os.walk(recordings_dir):
        for filename in files:
            # Skip non-audio files and temp files
            if not (filename.endswith(('.mp3', '.wav', '.m4a', '.flac', '.ogg')) or
                    filename.endswith('.txt')):  # Include transcript files
                continue

            file_path = os.path.join(root, filename)

            # Check if file is in database
            if file_path not in db_files:
                try:
                    file_size = os.path.getsize(file_path)
                    file_mtime = os.path.getmtime(file_path)
                    orphaned_files.append({
                        'file_path': file_path,
                        'file_name': filename,
                        'file_size': file_size,
                        'modified_time': datetime.fromtimestamp(file_mtime).isoformat()
                    })
                except OSError:
                    pass

    return sorted(orphaned_files, key=lambda x: x['modified_time'], reverse=True)


def update_transcription_status(recording_id: int, status: str, error: Optional[str] = None):
    """Update transcription status for a recording.

    Args:
        recording_id: Recording ID
        status: Status ('pending', 'processing', 'completed', 'failed', 'skipped')
        error: Optional error message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        now = datetime.now(CALGARY_TZ).isoformat()

        cursor.execute("""
            UPDATE recordings
            SET transcription_status = ?,
                transcription_attempted_at = ?,
                transcription_error = ?
            WHERE id = ?
        """, (status, now, error, recording_id))


def update_transcription_progress(recording_id: int, progress: Dict):
    """Update transcription progress details.

    Args:
        recording_id: Recording ID
        progress: Dictionary with progress info (e.g., {'stage': 'transcribing', 'percent': 50})
    """
    import json
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE recordings
            SET transcription_progress = ?
            WHERE id = ?
        """, (json.dumps(progress), recording_id))


def add_transcription_log(recording_id: int, message: str, level: str = 'info'):
    """Add a log message to the transcription logs.

    Args:
        recording_id: Recording ID
        message: Log message
        level: Log level ('info', 'warning', 'error')
    """
    import json
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get existing logs
        cursor.execute("SELECT transcription_logs FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        logs = []
        if row and row['transcription_logs']:
            try:
                logs = json.loads(row['transcription_logs'])
            except:
                logs = []

        # Add new log entry
        now = datetime.now(CALGARY_TZ).isoformat()
        logs.append({
            'timestamp': now,
            'level': level,
            'message': message
        })

        # Keep only last 100 log entries
        logs = logs[-100:]

        cursor.execute("""
            UPDATE recordings
            SET transcription_logs = ?
            WHERE id = ?
        """, (json.dumps(logs), recording_id))


def get_recordings_needing_transcription(limit: int = 50) -> List[Dict]:
    """Get recordings that need transcription (completed but not yet transcribed).

    Args:
        limit: Maximum number of recordings to return

    Returns:
        List of recording dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.id,
                r.meeting_id,
                r.file_path,
                r.start_time,
                r.end_time,
                r.duration_seconds,
                r.file_size_bytes,
                r.status,
                r.is_segmented,
                r.transcript_path,
                r.transcription_status,
                r.transcription_attempted_at,
                r.transcription_error,
                m.title as meeting_title
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            WHERE r.status = 'completed'
            AND (r.transcription_status IS NULL OR r.transcription_status = 'pending' OR r.transcription_status = 'failed')
            ORDER BY r.start_time DESC
            LIMIT ?
        """, (limit,))

        recordings = []
        for row in cursor.fetchall():
            recordings.append({
                'id': row['id'],
                'meeting_id': row['meeting_id'],
                'file_path': row['file_path'],
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration_seconds': row['duration_seconds'],
                'file_size_bytes': row['file_size_bytes'],
                'status': row['status'],
                'is_segmented': row['is_segmented'],
                'transcript_path': row['transcript_path'],
                'transcription_status': row['transcription_status'],
                'transcription_attempted_at': row['transcription_attempted_at'],
                'transcription_error': row['transcription_error'],
                'meeting_title': row['meeting_title']
            })

        return recordings


def add_recording_log(recording_id: int, message: str, level: str = 'info'):
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


def get_recording_logs(recording_id: int, limit: int = 100) -> List[Dict]:
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


def delete_recording(recording_id: int) -> bool:
    """Delete a recording from the database and optionally its files.

    Args:
        recording_id: Recording ID to delete

    Returns:
        True if deletion was successful, False otherwise
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get recording details first
        cursor.execute("SELECT file_path FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        if not row:
            return False

        file_path = row['file_path']

        # Delete segments first (foreign key constraint)
        cursor.execute("DELETE FROM segments WHERE recording_id = ?", (recording_id,))

        # Delete recording logs
        cursor.execute("DELETE FROM recording_logs WHERE recording_id = ?", (recording_id,))

        # Delete the recording
        cursor.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))

        # Delete the file if it exists
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Warning: Could not delete file {file_path}: {e}")

        return True


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
