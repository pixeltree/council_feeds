"""
Database module for Calgary Council Stream Recorder.

This module provides a backward-compatible facade that re-exports all database
functions from the modular repository structure. All existing imports will
continue to work exactly as before.

Example:
    from database import create_recording, get_upcoming_meetings
"""

# Import connection utilities (which include config constants)
from database.connection import (
    CALGARY_TZ,
    DB_DIR,
    DB_PATH,
    Database,
    ensure_db_directory,
    get_db_connection,
    parse_datetime_from_db,
)

# Import migrations
from database.migrations import init_database

# Import meeting repository functions
from database.repositories.meetings import (
    find_meeting_by_datetime,
    get_upcoming_meetings,
    save_meetings,
)

# Import recording repository functions
from database.repositories.recordings import (
    add_transcription_log,
    create_recording,
    delete_recording,
    get_orphaned_files,
    get_recording_by_id,
    get_recording_speakers,
    get_recording_stats,
    get_recordings_needing_transcription,
    get_recent_recordings,
    get_stale_recordings,
    get_transcription_steps,
    get_unprocessed_recordings,
    mark_recording_segmented,
    update_post_process_status,
    update_recording,
    update_recording_diarization_paths,
    update_recording_speakers,
    update_recording_transcript,
    update_transcription_progress,
    update_transcription_status,
    update_transcription_step,
    update_wav_path,
)

# Import segment repository functions
from database.repositories.segments import (
    create_segment,
    get_segments_by_recording,
    update_segment_transcript,
)

# Import metadata repository functions
from database.repositories.metadata import (
    get_metadata,
    set_metadata,
)

# Import logging repository functions
from database.repositories.logs import (
    add_recording_log,
    get_recording_logs,
    log_stream_status,
)

__all__ = [
    # Config constants
    "CALGARY_TZ",
    "DB_DIR",
    "DB_PATH",
    # Connection utilities
    "Database",
    "ensure_db_directory",
    "get_db_connection",
    "parse_datetime_from_db",
    # Migrations
    "init_database",
    # Meeting functions
    "find_meeting_by_datetime",
    "get_upcoming_meetings",
    "save_meetings",
    # Recording functions
    "add_transcription_log",
    "create_recording",
    "delete_recording",
    "get_orphaned_files",
    "get_recording_by_id",
    "get_recording_speakers",
    "get_recording_stats",
    "get_recordings_needing_transcription",
    "get_recent_recordings",
    "get_stale_recordings",
    "get_transcription_steps",
    "get_unprocessed_recordings",
    "mark_recording_segmented",
    "update_post_process_status",
    "update_recording",
    "update_recording_diarization_paths",
    "update_recording_speakers",
    "update_recording_transcript",
    "update_transcription_progress",
    "update_transcription_status",
    "update_transcription_step",
    "update_wav_path",
    # Segment functions
    "create_segment",
    "get_segments_by_recording",
    "update_segment_transcript",
    # Metadata functions
    "get_metadata",
    "set_metadata",
    # Logging functions
    "add_recording_log",
    "get_recording_logs",
    "log_stream_status",
]
