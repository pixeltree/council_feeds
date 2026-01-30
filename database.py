#!/usr/bin/env python3
"""
DEPRECATED: This module is deprecated and kept for backward compatibility only.

Please import from the new modular structure instead:
    from database import <function_name>  # Still works
    from database.repositories.meetings import <function_name>  # Preferred

The database module has been split into:
    - database.connection (connection management)
    - database.migrations (schema migrations)
    - database.repositories.meetings (meeting operations)
    - database.repositories.recordings (recording operations)
    - database.repositories.segments (segment operations)
    - database.repositories.metadata (metadata operations)
    - database.repositories.logs (logging operations)

This file will be removed in a future release.
"""

import warnings

# Issue deprecation warning when this module is imported directly
warnings.warn(
    "The database.py module is deprecated. "
    "Please import from 'database' package instead: from database import <function_name>. "
    "This file will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything from the new modular structure for backward compatibility
from database import *  # noqa: F401, F403

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
