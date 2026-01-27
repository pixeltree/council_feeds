"""Unit tests for database module."""

import pytest
import os
from datetime import datetime, timedelta
from config import CALGARY_TZ
import database as db


@pytest.mark.unit
class TestTranscriptDatabase:
    """Test database functions for transcripts."""

    def test_update_recording_transcript(self, temp_db_path, temp_db_dir, sample_meeting, monkeypatch):
        """Test updating recording with transcript path."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        db.save_meetings([sample_meeting])

        # Create a recording
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        recording_id = db.create_recording(
            None,
            '/recordings/test.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        # Update with transcript path
        transcript_path = '/recordings/test.mp4.transcript.json'
        db.update_recording_transcript(recording_id, transcript_path)

        # Verify it was updated
        recordings = db.get_recent_recordings(limit=1)
        assert len(recordings) == 1
        assert recordings[0]['transcript_path'] == transcript_path

    def test_get_recent_recordings_includes_transcript(self, temp_db_path, temp_db_dir, sample_meeting, monkeypatch):
        """Test that get_recent_recordings returns transcript_path."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        db.save_meetings([sample_meeting])

        # Create recording with transcript
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        recording_id = db.create_recording(
            None,
            '/recordings/test.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        transcript_path = '/recordings/test.mp4.transcript.json'
        db.update_recording_transcript(recording_id, transcript_path)

        # Retrieve recordings
        recordings = db.get_recent_recordings()
        assert len(recordings) == 1
        assert 'transcript_path' in recordings[0]
        assert recordings[0]['transcript_path'] == transcript_path

    def test_recording_without_transcript(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test recording without transcript has None for transcript_path."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        # Create recording without transcript
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        db.create_recording(
            None,
            '/recordings/test.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        # Retrieve recordings
        recordings = db.get_recent_recordings()
        assert len(recordings) == 1
        assert 'transcript_path' in recordings[0]
        assert recordings[0]['transcript_path'] is None


@pytest.mark.unit
class TestDatabase:
    """Test Database class."""

    def test_database_init(self, temp_db_path, temp_db_dir):
        """Test Database initialization."""
        database = db.Database(db_path=temp_db_path, db_dir=temp_db_dir)
        assert database.db_path == temp_db_path
        assert database.db_dir == temp_db_dir

    def test_ensure_db_directory(self, tmp_path):
        """Test database directory creation."""
        db_dir = str(tmp_path / "new_db_dir")
        database = db.Database(db_dir=db_dir)

        assert not os.path.exists(db_dir)
        database.ensure_db_directory()
        assert os.path.exists(db_dir)

    def test_get_connection(self, temp_db_path, temp_db_dir):
        """Test database connection context manager."""
        database = db.Database(db_path=temp_db_path, db_dir=temp_db_dir)
        database.ensure_db_directory()

        with database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1


@pytest.mark.unit
class TestDatabaseFunctions:
    """Test database module-level functions."""

    def test_parse_datetime_from_db_with_timezone(self):
        """Test parsing timezone-aware datetime from database."""
        dt = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        dt_str = dt.isoformat()

        parsed = db.parse_datetime_from_db(dt_str)

        assert parsed == dt
        assert parsed.tzinfo is not None

    def test_parse_datetime_from_db_naive(self):
        """Test parsing naive datetime from database (should add timezone)."""
        dt_naive = datetime(2026, 1, 27, 9, 30)
        dt_str = dt_naive.isoformat()

        parsed = db.parse_datetime_from_db(dt_str)

        assert parsed.year == 2026
        assert parsed.month == 1
        assert parsed.day == 27
        assert parsed.tzinfo is not None

    def test_init_database(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test database schema initialization."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        assert os.path.exists(temp_db_path)

        # Verify tables exist
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert 'meetings' in tables
            assert 'recordings' in tables
            assert 'stream_status_log' in tables
            assert 'metadata' in tables

    def test_save_meetings(self, temp_db_path, temp_db_dir, sample_meetings, monkeypatch):
        """Test saving meetings to database."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        count = db.save_meetings(sample_meetings)

        assert count == len(sample_meetings)

        # Verify meetings are in database
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM meetings")
            assert cursor.fetchone()[0] == len(sample_meetings)

    def test_get_upcoming_meetings(self, temp_db_path, temp_db_dir, sample_meetings, monkeypatch):
        """Test retrieving upcoming meetings."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        db.save_meetings(sample_meetings)

        meetings = db.get_upcoming_meetings()

        assert len(meetings) > 0
        assert all('datetime' in m for m in meetings)
        assert all('title' in m for m in meetings)

    def test_find_meeting_by_datetime(self, temp_db_path, temp_db_dir, sample_meeting, monkeypatch):
        """Test finding meeting by datetime with tolerance."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        db.save_meetings([sample_meeting])

        # Find with exact time
        found = db.find_meeting_by_datetime(sample_meeting['datetime'])
        assert found is not None
        assert found['title'] == sample_meeting['title']

        # Find with time slightly off (within tolerance)
        time_offset = sample_meeting['datetime'] + timedelta(minutes=10)
        found_offset = db.find_meeting_by_datetime(time_offset, tolerance_minutes=30)
        assert found_offset is not None

    def test_create_and_update_recording(self, temp_db_path, temp_db_dir, sample_meeting, monkeypatch):
        """Test creating and updating a recording."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()
        db.save_meetings([sample_meeting])

        meeting = db.find_meeting_by_datetime(sample_meeting['datetime'])

        # Create recording
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        recording_id = db.create_recording(
            meeting['id'],
            '/tmp/test_recording.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        assert recording_id > 0

        # Update recording
        end_time = start_time + timedelta(hours=1)
        db.update_recording(recording_id, end_time, 'completed')

        # Verify update
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, end_time FROM recordings WHERE id = ?", (recording_id,))
            row = cursor.fetchone()
            assert row['status'] == 'completed'
            assert row['end_time'] is not None

    def test_metadata_operations(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test metadata set and get operations."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        # Set metadata
        db.set_metadata('test_key', 'test_value')

        # Get metadata
        value = db.get_metadata('test_key')
        assert value == 'test_value'

        # Get non-existent key with default
        value = db.get_metadata('non_existent', default='default_value')
        assert value == 'default_value'

    def test_get_recording_stats(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test getting recording statistics."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        # Create some test recordings
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        for i in range(3):
            recording_id = db.create_recording(
                None,
                f'/tmp/test_recording_{i}.mp4',
                'https://example.com/stream.m3u8',
                start_time
            )
            if i < 2:  # Complete first two
                db.update_recording(recording_id, start_time + timedelta(hours=1), 'completed')
            else:  # Leave one in progress
                pass

        stats = db.get_recording_stats()

        assert stats['total_recordings'] == 3
        assert stats['completed'] == 2
        assert stats['in_progress'] == 1

    def test_get_recent_recordings(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test getting recent recordings."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        recording_id = db.create_recording(
            None,
            '/tmp/test_recording.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        recordings = db.get_recent_recordings(limit=10)

        assert len(recordings) == 1
        assert recordings[0]['id'] == recording_id

    def test_log_stream_status(self, temp_db_path, temp_db_dir, monkeypatch):
        """Test logging stream status."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        db.init_database()

        db.log_stream_status(
            'https://example.com/stream.m3u8',
            'live',
            None,
            'Test status log'
        )

        # Verify log entry
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stream_status_log")
            assert cursor.fetchone()[0] == 1
