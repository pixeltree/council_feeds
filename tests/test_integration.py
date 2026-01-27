"""Integration tests for the complete system."""

import pytest
import responses
from datetime import datetime, timedelta
from unittest.mock import patch, Mock
from config import CALGARY_TZ
import database as db
from services import CalendarService, MeetingScheduler, StreamService


@pytest.mark.integration
class TestCalendarIntegration:
    """Integration tests for calendar and database."""

    @responses.activate
    @patch('services.db.get_metadata')
    @patch('services.db.save_meetings')
    @patch('services.db.set_metadata')
    @patch('services.db.get_upcoming_meetings')
    def test_calendar_to_database_flow(
        self,
        mock_get_meetings,
        mock_set_metadata,
        mock_save_meetings,
        mock_get_metadata,
        api_response_data
    ):
        """Test full flow from API to database."""
        # Setup
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            json=api_response_data,
            status=200
        )

        mock_get_metadata.return_value = None
        mock_save_meetings.return_value = 2
        mock_get_meetings.return_value = []

        # Execute
        service = CalendarService()
        meetings = service.get_upcoming_meetings(force_refresh=True)

        # Verify
        mock_save_meetings.assert_called_once()
        assert len(mock_save_meetings.call_args[0][0]) == 2


@pytest.mark.integration
class TestMeetingSchedulingIntegration:
    """Integration tests for meeting scheduling logic."""

    def test_active_window_detection(self, sample_meetings):
        """Test detecting active meeting window with real data."""
        scheduler = MeetingScheduler()

        # Test time within window
        test_time = sample_meetings[0]['datetime'] + timedelta(minutes=1)
        in_window, current_meeting = scheduler.is_within_meeting_window(
            test_time,
            sample_meetings
        )

        assert in_window is True
        assert current_meeting == sample_meetings[0]

        # Test time outside window
        test_time = sample_meetings[0]['datetime'] - timedelta(hours=1)
        in_window, current_meeting = scheduler.is_within_meeting_window(
            test_time,
            sample_meetings
        )

        assert in_window is False
        assert current_meeting is None

    def test_next_meeting_detection(self, sample_meetings):
        """Test getting next meeting with real meeting data."""
        scheduler = MeetingScheduler()

        # Between first and second meeting
        test_time = sample_meetings[0]['datetime'] + timedelta(days=1)
        next_meeting = scheduler.get_next_meeting(test_time, sample_meetings)

        assert next_meeting == sample_meetings[1]


@pytest.mark.integration
class TestStreamDetectionIntegration:
    """Integration tests for stream detection."""

    @patch('services.subprocess.run')
    @responses.activate
    def test_stream_url_fallback_chain(self, mock_run):
        """Test fallback chain: yt-dlp -> patterns -> page parsing."""
        # yt-dlp fails
        mock_run.side_effect = FileNotFoundError()

        # First few patterns fail
        service = StreamService()
        for pattern in service.stream_url_patterns[:-1]:
            responses.add(responses.HEAD, pattern, status=404)

        # Last pattern succeeds
        last_pattern = service.stream_url_patterns[-1]
        responses.add(responses.HEAD, last_pattern, status=200)

        url = service.get_stream_url()

        assert url == last_pattern

    @responses.activate
    def test_stream_availability_check(self):
        """Test checking stream availability."""
        stream_url = 'https://example.com/test.m3u8'
        responses.add(responses.HEAD, stream_url, status=200)

        service = StreamService()
        is_live = service.is_stream_live(stream_url)

        assert is_live is True


@pytest.mark.integration
class TestEndToEndScenarios:
    """End-to-end scenario tests."""

    @responses.activate
    @patch('services.db.get_metadata')
    @patch('services.db.save_meetings')
    @patch('services.db.set_metadata')
    @patch('services.db.get_upcoming_meetings')
    def test_full_monitoring_cycle(
        self,
        mock_get_meetings,
        mock_set_metadata,
        mock_save_meetings,
        mock_get_metadata,
        api_response_data,
        sample_meetings
    ):
        """Test a complete monitoring cycle."""
        # 1. Fetch meetings
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            json=api_response_data,
            status=200
        )

        mock_get_metadata.return_value = None
        mock_save_meetings.return_value = 2
        mock_get_meetings.return_value = sample_meetings

        calendar_service = CalendarService()
        meetings = calendar_service.get_upcoming_meetings(force_refresh=True)

        # 2. Check meeting window
        scheduler = MeetingScheduler()
        current_time = sample_meetings[0]['datetime'] + timedelta(minutes=1)
        in_window, current_meeting = scheduler.is_within_meeting_window(
            current_time,
            meetings
        )

        # 3. Verify we're in active mode
        assert in_window is True
        assert current_meeting is not None

    @patch('services.subprocess.run')
    @responses.activate
    def test_stream_detection_when_meeting_active(self, mock_run):
        """Test stream detection during an active meeting."""
        # Mock yt-dlp finding stream
        mock_run.return_value = Mock(
            returncode=0,
            stdout='https://example.com/live.m3u8\n'
        )

        # Mock stream being live
        responses.add(
            responses.HEAD,
            'https://example.com/live.m3u8',
            status=200
        )

        stream_service = StreamService()

        # Get stream URL
        stream_url = stream_service.get_stream_url()
        assert stream_url is not None

        # Verify it's live
        is_live = stream_service.is_stream_live(stream_url)
        assert is_live is True


@pytest.mark.integration
@pytest.mark.slow
class TestDatabaseIntegration:
    """Integration tests with actual database operations."""

    def test_full_recording_lifecycle(self, temp_db_path, temp_db_dir, sample_meeting, monkeypatch):
        """Test complete recording lifecycle in database."""
        monkeypatch.setattr(db, 'DB_PATH', temp_db_path)
        monkeypatch.setattr(db, 'DB_DIR', temp_db_dir)

        # Initialize database
        db.init_database()

        # Save meeting
        db.save_meetings([sample_meeting])

        # Find meeting
        meeting = db.find_meeting_by_datetime(sample_meeting['datetime'])
        assert meeting is not None

        # Create recording
        start_time = CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30))
        recording_id = db.create_recording(
            meeting['id'],
            '/tmp/test.mp4',
            'https://example.com/stream.m3u8',
            start_time
        )

        # Log stream status
        db.log_stream_status(
            'https://example.com/stream.m3u8',
            'live',
            meeting['id'],
            'Recording started'
        )

        # Complete recording
        end_time = start_time + timedelta(hours=2)
        db.update_recording(recording_id, end_time, 'completed')

        # Verify statistics
        stats = db.get_recording_stats()
        assert stats['total_recordings'] == 1
        assert stats['completed'] == 1

        # Verify recent recordings
        recordings = db.get_recent_recordings()
        assert len(recordings) == 1
        assert recordings[0]['status'] == 'completed'
