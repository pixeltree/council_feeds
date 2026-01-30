"""Segment repository for database operations."""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from config import CALGARY_TZ
from database.connection import get_db_connection

logger = logging.getLogger(__name__)


def create_segment(recording_id: int, segment_number: int, file_path: str,
                  start_time: float, end_time: float, duration: float,
                  file_size_bytes: Optional[int] = None) -> int:
    """Create a new segment record and return its ID.

    Args:
        recording_id: Recording ID this segment belongs to
        segment_number: Sequential segment number
        file_path: Path to segment file
        start_time: Start time in seconds
        end_time: End time in seconds
        duration: Duration in seconds
        file_size_bytes: Optional file size

    Returns:
        ID of created segment
    """
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
    """Get all segments for a recording.

    Args:
        recording_id: Recording ID

    Returns:
        List of segment dictionaries
    """
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


def update_segment_transcript(segment_id: int, transcript_path: str):
    """Update segment with transcript file path.

    Args:
        segment_id: Segment ID
        transcript_path: Path to transcript file
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE segments
            SET transcript_path = ?, has_transcript = 1
            WHERE id = ?
        """, (transcript_path, segment_id))
