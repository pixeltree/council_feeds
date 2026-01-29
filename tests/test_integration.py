"""Integration tests for the complete system."""

import pytest
import responses
from datetime import datetime, timedelta
from unittest.mock import patch, Mock, MagicMock, mock_open
from config import CALGARY_TZ
import database as db
from services import CalendarService, MeetingScheduler, StreamService, RecordingService


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
        mock_save_meetings.return_value = 3  # Now returns all meetings (2 council + 1 committee)
        mock_get_meetings.return_value = []

        # Execute
        service = CalendarService()
        meetings = service.get_upcoming_meetings(force_refresh=True)

        # Verify
        mock_save_meetings.assert_called_once()
        assert len(mock_save_meetings.call_args[0][0]) == 3  # 2 council + 1 committee


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


@pytest.mark.integration
class TestTranscriptionIntegration:
    """Integration tests for transcription with recording service."""

    @patch('services.ENABLE_TRANSCRIPTION', True)
    @patch('services.db.update_recording_transcript')
    @patch('transcription_service.TranscriptionService')
    @patch('services.subprocess.Popen')
    @patch('os.path.exists')
    @patch('services.subprocess.run')  # Mock audio detection
    @patch('services.db.create_recording')
    @patch('services.db.update_recording')
    @patch('services.db.log_stream_status')
    @patch('time.sleep')
    @patch('os.path.getsize')
    def test_recording_with_transcription(
        self,
        mock_getsize,
        mock_sleep,
        mock_log_status,
        mock_update_recording,
        mock_create_recording,
        mock_run,
        mock_exists,
        mock_popen,
        mock_transcription_service_class,
        mock_update_transcript,
        temp_output_dir
    ):
        """Test complete recording flow with transcription enabled."""
        # Setup recording mocks
        mock_create_recording.return_value = 1
        mock_getsize.return_value = 1024 * 1024
        mock_exists.return_value = True

        # Mock audio detection to show it has content
        mock_run.return_value = Mock(
            stderr="""
            [Parsed_volumedetect_0 @ 0x123] mean_volume: -25.5 dB
            [Parsed_volumedetect_0 @ 0x123] max_volume: -10.2 dB
            """
        )

        mock_process = MagicMock()
        mock_process.pid = 12345
        call_count = {"count": 0}
        def poll_side_effect():
            call_count["count"] += 1
            return None if call_count["count"] == 1 else 0
        mock_process.poll.side_effect = poll_side_effect
        mock_popen.return_value = mock_process

        # Setup transcription mocks
        mock_transcriber = Mock()
        mock_transcriber.transcribe_with_speakers.return_value = {
            'file': '/test/video.mp4',
            'language': 'en',
            'segments': [
                {'start': 0.0, 'end': 5.0, 'text': 'Hello', 'speaker': 'SPEAKER_00'}
            ],
            'full_text': 'Hello',
            'num_speakers': 1
        }
        mock_transcriber.format_transcript_as_text.return_value = "[SPEAKER_00] (0:00:00)\nHello"
        mock_transcription_service_class.return_value = mock_transcriber

        # Setup stream service
        mock_stream_service = Mock()
        mock_stream_service.is_stream_live.return_value = False

        service = RecordingService(
            output_dir=temp_output_dir,
            stream_service=mock_stream_service
        )

        # Execute recording
        with patch('builtins.open', mock_open()):
            result = service.record_stream('https://example.com/stream.m3u8')

        assert result is True

        # Verify transcription was called
        mock_transcriber.transcribe_with_speakers.assert_called_once()
        mock_transcriber.format_transcript_as_text.assert_called_once()

        # Verify database was updated with transcript
        mock_update_transcript.assert_called_once()

    @patch('services.ENABLE_TRANSCRIPTION', True)
    @patch('services.PYANNOTE_API_TOKEN', None)
    @patch('services.subprocess.Popen')
    @patch('services.db.create_recording')
    @patch('services.db.update_recording')
    @patch('services.db.log_stream_status')
    @patch('time.sleep')
    @patch('os.path.getsize')
    def test_recording_continues_if_transcription_fails(
        self,
        mock_getsize,
        mock_sleep,
        mock_log_status,
        mock_update_recording,
        mock_create_recording,
        mock_popen,
        temp_output_dir
    ):
        """Test that recording completes even if transcription fails."""
        # Setup recording mocks
        mock_create_recording.return_value = 1
        mock_getsize.return_value = 1024 * 1024

        mock_process = MagicMock()
        mock_process.pid = 12345
        call_count = {"count": 0}
        def poll_side_effect():
            call_count["count"] += 1
            return None if call_count["count"] == 1 else 0
        mock_process.poll.side_effect = poll_side_effect
        mock_popen.return_value = mock_process

        # Setup stream service
        mock_stream_service = Mock()
        mock_stream_service.is_stream_live.return_value = False

        service = RecordingService(
            output_dir=temp_output_dir,
            stream_service=mock_stream_service
        )

        # Execute recording (transcription will fail due to missing token)
        result = service.record_stream('https://example.com/stream.m3u8')

        # Recording should still succeed
        assert result is True
        mock_update_recording.assert_called_once()


@pytest.mark.integration
class TestPostProcessingIntegration:
    """Integration tests for post-processing with recording service."""

    @patch('services.ENABLE_POST_PROCESSING', True)
    @patch('os.path.exists')
    @patch('services.subprocess.run')  # Mock audio detection
    @patch('post_processor.PostProcessor')
    @patch('services.subprocess.Popen')
    @patch('services.db.create_recording')
    @patch('services.db.update_recording')
    @patch('services.db.log_stream_status')
    @patch('time.sleep')
    @patch('os.path.getsize')
    def test_recording_with_post_processing(
        self,
        mock_getsize,
        mock_sleep,
        mock_log_status,
        mock_update_recording,
        mock_create_recording,
        mock_popen,
        mock_post_processor_class,
        mock_run,
        mock_exists,
        temp_output_dir
    ):
        """Test complete recording flow with post-processing enabled."""
        # Setup recording mocks
        mock_exists.return_value = True

        # Mock audio detection to show it has content
        mock_run.return_value = Mock(
            stderr="""
            [Parsed_volumedetect_0 @ 0x123] mean_volume: -25.5 dB
            [Parsed_volumedetect_0 @ 0x123] max_volume: -10.2 dB
            """
        )

        # Setup recording mocks
        mock_create_recording.return_value = 1
        mock_getsize.return_value = 1024 * 1024

        mock_process = MagicMock()
        mock_process.pid = 12345
        call_count = {"count": 0}
        def poll_side_effect():
            call_count["count"] += 1
            return None if call_count["count"] == 1 else 0
        mock_process.poll.side_effect = poll_side_effect
        mock_popen.return_value = mock_process

        # Setup post-processor mocks
        mock_processor = Mock()
        mock_processor.process_recording.return_value = {
            'success': True,
            'segments_created': 2
        }
        mock_post_processor_class.return_value = mock_processor

        # Setup stream service
        mock_stream_service = Mock()
        mock_stream_service.is_stream_live.return_value = False

        service = RecordingService(
            output_dir=temp_output_dir,
            stream_service=mock_stream_service
        )

        # Execute recording
        result = service.record_stream('https://example.com/stream.m3u8')

        assert result is True

        # Verify post-processing was called
        mock_processor.process_recording.assert_called_once()
