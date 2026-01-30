"""Database schema migrations."""

import logging
import sqlite3

from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def init_database() -> None:
    """Initialize the database schema and run all migrations."""
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

        # Run all migrations
        _migrate_add_room_column(cursor)
        _migrate_add_post_processing_columns(cursor)
        _migrate_add_transcription_columns(cursor)
        _migrate_add_diarization_columns(cursor)
        _migrate_add_speakers_column(cursor)
        _migrate_add_transcription_steps_columns(cursor)


def _migrate_add_room_column(cursor: sqlite3.Cursor) -> None:
    """Migration: Add room column to meetings table if it doesn't exist."""
    cursor.execute("PRAGMA table_info(meetings)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'room' not in columns:
        logger.info("Running migration: Adding room column to meetings table")
        cursor.execute("ALTER TABLE meetings ADD COLUMN room TEXT")


def _migrate_add_post_processing_columns(cursor: sqlite3.Cursor) -> None:
    """Migration: Add post-processing tracking columns to recordings table."""
    cursor.execute("PRAGMA table_info(recordings)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'post_process_status' not in columns:
        logger.info("Running migration: Adding post-processing columns to recordings table")
        cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_status TEXT DEFAULT 'pending'")
    if 'post_process_attempted_at' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_attempted_at TEXT")
    if 'post_process_error' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN post_process_error TEXT")


def _migrate_add_transcription_columns(cursor: sqlite3.Cursor) -> None:
    """Migration: Add transcription tracking columns to recordings table."""
    cursor.execute("PRAGMA table_info(recordings)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'transcription_status' not in columns:
        logger.info("Running migration: Adding transcription columns to recordings table")
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_status TEXT DEFAULT 'pending'")
    if 'transcription_attempted_at' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_attempted_at TEXT")
    if 'transcription_error' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_error TEXT")
    if 'transcription_progress' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_progress TEXT")
    if 'transcription_logs' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_logs TEXT")


def _migrate_add_diarization_columns(cursor: sqlite3.Cursor) -> None:
    """Migration: Add diarization file path columns to recordings table."""
    cursor.execute("PRAGMA table_info(recordings)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'diarization_pyannote_path' not in columns:
        logger.info("Running migration: Adding diarization columns to recordings table")
        cursor.execute("ALTER TABLE recordings ADD COLUMN diarization_pyannote_path TEXT")
    if 'diarization_gemini_path' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN diarization_gemini_path TEXT")


def _migrate_add_speakers_column(cursor: sqlite3.Cursor) -> None:
    """Migration: Add speaker list column to recordings table."""
    cursor.execute("PRAGMA table_info(recordings)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'speakers' not in columns:
        logger.info("Running migration: Adding speakers column to recordings table")
        cursor.execute("ALTER TABLE recordings ADD COLUMN speakers TEXT")


def _migrate_add_transcription_steps_columns(cursor: sqlite3.Cursor) -> None:
    """Migration: Add step-level transcription tracking columns."""
    cursor.execute("PRAGMA table_info(recordings)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'transcription_steps' not in columns:
        logger.info("Running migration: Adding transcription_steps column to recordings table")
        cursor.execute("ALTER TABLE recordings ADD COLUMN transcription_steps TEXT")
    if 'wav_path' not in columns:
        cursor.execute("ALTER TABLE recordings ADD COLUMN wav_path TEXT")
