"""Recording repository for database operations."""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import CALGARY_TZ, OUTPUT_DIR
from database.connection import get_db_connection, parse_datetime_from_db

logger = logging.getLogger(__name__)


def create_recording(meeting_id: Optional[int], file_path: str, stream_url: str, start_time: datetime) -> Optional[int]:
    """Create a new recording record and return its ID.

    Args:
        meeting_id: ID of associated meeting, or None
        file_path: Path to recording file
        stream_url: URL of stream being recorded
        start_time: Recording start time

    Returns:
        ID of created recording
    """
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
                     error_message: Optional[str] = None) -> None:
    """Update recording with completion details.

    Args:
        recording_id: Recording ID
        end_time: Recording end time
        status: Recording status
        error_message: Optional error message
    """
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


def get_recording_stats() -> Dict[str, Any]:
    """Get recording statistics.

    Returns:
        Dictionary with recording statistics
    """
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


def update_recording_transcript(recording_id: int, transcript_path: str) -> None:
    """Update recording with transcript file path.

    Args:
        recording_id: Recording ID
        transcript_path: Path to transcript file
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET transcript_path = ?
            WHERE id = ?
        """, (transcript_path, recording_id))


def update_recording_diarization_paths(
    recording_id: int,
    pyannote_path: Optional[str] = None,
    gemini_path: Optional[str] = None
) -> None:
    """Update recording with diarization file paths.

    Args:
        recording_id: Recording ID
        pyannote_path: Path to pyannote diarization file
        gemini_path: Path to gemini diarization file
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET diarization_pyannote_path = ?,
                diarization_gemini_path = ?
            WHERE id = ?
        """, (pyannote_path, gemini_path, recording_id))


def get_recent_recordings(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent recordings with meeting details.

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
    """Get a recording by its ID.

    Args:
        recording_id: Recording ID

    Returns:
        Recording dictionary if found, None otherwise
    """
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
                r.diarization_pyannote_path,
                r.diarization_gemini_path,
                r.speakers,
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
                'diarization_pyannote_path': row['diarization_pyannote_path'],
                'diarization_gemini_path': row['diarization_gemini_path'],
                'speakers': row['speakers'],
                'meeting_id': row['meeting_id'],
                'meeting_title': row['meeting_title'],
                'meeting_datetime': row['meeting_datetime']
            }
        return None


def mark_recording_segmented(recording_id: int) -> None:
    """Mark a recording as having been segmented.

    Args:
        recording_id: Recording ID
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET is_segmented = 1
            WHERE id = ?
        """, (recording_id,))


def update_post_process_status(recording_id: int, status: str, error: Optional[str] = None) -> None:
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


def get_unprocessed_recordings(limit: int = 50) -> List[Dict[str, Any]]:
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
    """Get recordings that are stale (file doesn't exist, stuck in 'recording' status, or has no content).

    Returns:
        List of stale recording dictionaries with file existence check
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get all recordings (we'll check file existence for each)
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
            ORDER BY r.start_time DESC
        """)

        stale_recordings = []
        for row in cursor.fetchall():
            file_exists = os.path.exists(row['file_path'])
            file_size = os.path.getsize(row['file_path']) if file_exists else 0

            # Consider stale if:
            # 1. File doesn't exist (regardless of status)
            # 2. File exists but is tiny (< 1KB)
            # 3. Status is 'recording' but file has no content
            # 4. Status is 'completed' but has no meaningful data
            is_stale = (
                not file_exists or  # File missing
                file_size < 1000 or  # File too small
                row['status'] == 'recording' or  # Stuck in recording state
                (row['status'] == 'completed' and (
                    row['duration_seconds'] is None or
                    row['duration_seconds'] == 0 or
                    row['file_size_bytes'] is None or
                    row['file_size_bytes'] < 1000
                ))
            )

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


def get_orphaned_files(recordings_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get files in recordings directory that have no database entry.

    Args:
        recordings_dir: Directory to scan (defaults to OUTPUT_DIR from config)

    Returns:
        List of orphaned file dictionaries with file info
    """
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
            # Skip non-audio/video files and temp files
            if not (filename.endswith(('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.mp4', '.mkv')) or
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


def update_transcription_status(recording_id: int, status: str, error: Optional[str] = None) -> None:
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


def update_transcription_progress(recording_id: int, progress: Dict[str, Any]) -> None:
    """Update transcription progress details.

    Args:
        recording_id: Recording ID
        progress: Dictionary with progress info (e.g., {'stage': 'transcribing', 'percent': 50})
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE recordings
            SET transcription_progress = ?
            WHERE id = ?
        """, (json.dumps(progress), recording_id))


def add_transcription_log(recording_id: int, message: str, level: str = 'info') -> None:
    """Add a log message to the transcription logs.

    Args:
        recording_id: Recording ID
        message: Log message
        level: Log level ('info', 'warning', 'error')
    """
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


def get_recordings_needing_transcription(limit: int = 50) -> List[Dict[str, Any]]:
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


def update_transcription_step(recording_id: int, step_name: str, status: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Update the status of a specific transcription step.

    Args:
        recording_id: Recording ID
        step_name: Name of step ('extraction', 'whisper', 'diarization', 'gemini', 'merge')
        status: Step status ('pending', 'in_progress', 'completed', 'failed', 'skipped')
        data: Optional dict with step-specific data (e.g., file paths, error messages)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get existing steps
        cursor.execute("SELECT transcription_steps FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        steps = {}
        if row and row['transcription_steps']:
            try:
                steps = json.loads(row['transcription_steps'])
            except (json.JSONDecodeError, TypeError, ValueError):
                steps = {}

        # Update specific step
        if step_name not in steps:
            steps[step_name] = {}

        steps[step_name]['status'] = status
        steps[step_name]['updated_at'] = datetime.now(CALGARY_TZ).isoformat()

        if data:
            steps[step_name].update(data)

        cursor.execute("""
            UPDATE recordings
            SET transcription_steps = ?
            WHERE id = ?
        """, (json.dumps(steps), recording_id))


def get_transcription_steps(recording_id: int) -> Dict[str, Any]:
    """Get transcription steps status for a recording.

    Args:
        recording_id: Recording ID

    Returns:
        Dictionary of steps with their status and data
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT transcription_steps FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        if row and row['transcription_steps']:
            try:
                steps: Dict[str, Any] = json.loads(row['transcription_steps'])
                return steps
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        return {}


def update_wav_path(recording_id: int, wav_path: str) -> None:
    """Update the WAV file path for a recording.

    Args:
        recording_id: Recording ID
        wav_path: Path to WAV file
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE recordings
            SET wav_path = ?
            WHERE id = ?
        """, (wav_path, recording_id))


def update_recording_speakers(recording_id: int, speakers: List[Dict[str, str]]) -> None:
    """Update recording with speaker list from meeting agenda.

    Args:
        recording_id: Recording ID
        speakers: List of speaker dictionaries from agenda parser
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE recordings
            SET speakers = ?
            WHERE id = ?
        """, (json.dumps(speakers), recording_id))


def get_recording_speakers(recording_id: int) -> List[Dict[str, str]]:
    """Get speaker list for a recording.

    Args:
        recording_id: Recording ID

    Returns:
        List of speaker dictionaries, or empty list if none
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT speakers FROM recordings WHERE id = ?", (recording_id,))
        row = cursor.fetchone()

        if row and row['speakers']:
            try:
                speakers_list: List[Dict[str, str]] = json.loads(row['speakers'])
                return speakers_list
            except (json.JSONDecodeError, TypeError, ValueError):
                return []

        return []


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

        # Delete the file if it exists (but don't fail the database deletion if file deletion fails)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                # Log the failure but do not raise, so database deletion still proceeds
                logger.warning(f"Could not delete file {file_path}: {e}", exc_info=True)

        return True
