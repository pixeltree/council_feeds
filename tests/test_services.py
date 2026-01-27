"""Unit tests for service classes."""

import pytest
import responses
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from config import CALGARY_TZ
from services import (
    CalendarService,
    MeetingScheduler,
    StreamService,
    RecordingService
)


@pytest.mark.unit
class TestCalendarService:
    """Test CalendarService class."""

    def test_init(self):
        """Test CalendarService initialization."""
        service = CalendarService()
        assert service.api_url is not None
        assert service.timezone == CALGARY_TZ

    @responses.activate
    def test_fetch_council_meetings_success(self, api_response_data):
        """Test fetching council meetings successfully."""
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            json=api_response_data,
            status=200
        )

        service = CalendarService()
        meetings = service.fetch_council_meetings()

        # Should filter out non-Council meetings
        assert len(meetings) == 2
        assert all('Council meeting' in m['title'] for m in meetings)
        assert all('datetime' in m for m in meetings)
        assert all(m['datetime'].tzinfo is not None for m in meetings)

    @responses.activate
    def test_fetch_council_meetings_api_error(self):
        """Test handling API errors."""
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            status=500
        )

        service = CalendarService()
        meetings = service.fetch_council_meetings()

        assert meetings == []

    @responses.activate
    def test_fetch_council_meetings_invalid_date(self):
        """Test handling invalid date in API response."""
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            json=[{
                'title': 'Council meeting',
                'meeting_date': 'invalid date format',
                'link': 'https://example.com'
            }],
            status=200
        )

        service = CalendarService()
        meetings = service.fetch_council_meetings()

        # Should skip meetings with invalid dates
        assert len(meetings) == 0

    @patch('services.db.get_metadata')
    @patch('services.db.get_upcoming_meetings')
    def test_get_upcoming_meetings_cached(self, mock_get_meetings, mock_get_metadata):
        """Test getting meetings from cache."""
        mock_get_metadata.return_value = datetime.now(CALGARY_TZ).isoformat()
        mock_get_meetings.return_value = []

        service = CalendarService()
        meetings = service.get_upcoming_meetings(force_refresh=False)

        mock_get_meetings.assert_called_once()
        assert meetings == []

    @responses.activate
    @patch('services.db.get_metadata')
    @patch('services.db.save_meetings')
    @patch('services.db.set_metadata')
    @patch('services.db.get_upcoming_meetings')
    def test_get_upcoming_meetings_force_refresh(
        self,
        mock_get_meetings,
        mock_set_metadata,
        mock_save_meetings,
        mock_get_metadata,
        api_response_data
    ):
        """Test forcing a refresh from API."""
        responses.add(
            responses.GET,
            'https://data.calgary.ca/resource/23m4-i42g.json',
            json=api_response_data,
            status=200
        )

        mock_get_metadata.return_value = None  # No cached data
        mock_save_meetings.return_value = 2
        mock_get_meetings.return_value = []

        service = CalendarService()
        meetings = service.get_upcoming_meetings(force_refresh=True)

        mock_save_meetings.assert_called_once()
        mock_set_metadata.assert_called_once()


@pytest.mark.unit
class TestMeetingScheduler:
    """Test MeetingScheduler class."""

    def test_init(self):
        """Test MeetingScheduler initialization."""
        scheduler = MeetingScheduler()
        assert scheduler.buffer_before is not None
        assert scheduler.buffer_after is not None
        assert scheduler.timezone == CALGARY_TZ

    def test_is_within_meeting_window_true(self, sample_meeting):
        """Test detection when within meeting window."""
        scheduler = MeetingScheduler()

        # Current time is 2 minutes before meeting
        current_time = sample_meeting['datetime'] - timedelta(minutes=2)
        in_window, meeting = scheduler.is_within_meeting_window(
            current_time,
            [sample_meeting]
        )

        assert in_window is True
        assert meeting == sample_meeting

    def test_is_within_meeting_window_false(self, sample_meeting):
        """Test detection when outside meeting window."""
        scheduler = MeetingScheduler()

        # Current time is 10 minutes before meeting (outside 5 min buffer)
        current_time = sample_meeting['datetime'] - timedelta(minutes=10)
        in_window, meeting = scheduler.is_within_meeting_window(
            current_time,
            [sample_meeting]
        )

        assert in_window is False
        assert meeting is None

    def test_get_next_meeting(self, sample_meetings):
        """Test getting next meeting."""
        scheduler = MeetingScheduler()

        # Current time is before first meeting
        current_time = sample_meetings[0]['datetime'] - timedelta(days=1)
        next_meeting = scheduler.get_next_meeting(current_time, sample_meetings)

        assert next_meeting == sample_meetings[0]

    def test_get_next_meeting_none(self, sample_meetings):
        """Test getting next meeting when all meetings are in past."""
        scheduler = MeetingScheduler()

        # Current time is after all meetings
        current_time = sample_meetings[-1]['datetime'] + timedelta(days=1)
        next_meeting = scheduler.get_next_meeting(current_time, sample_meetings)

        assert next_meeting is None


@pytest.mark.unit
class TestStreamService:
    """Test StreamService class."""

    def test_init(self):
        """Test StreamService initialization."""
        service = StreamService()
        assert service.stream_page_url is not None
        assert service.stream_url_patterns is not None
        assert len(service.stream_url_patterns) > 0

    @patch('services.subprocess.run')
    def test_get_stream_url_with_ytdlp(self, mock_run):
        """Test getting stream URL using yt-dlp."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='https://example.com/stream.m3u8\n'
        )

        service = StreamService()
        url = service.get_stream_url()

        assert url == 'https://example.com/stream.m3u8'

    @patch('services.subprocess.run')
    @responses.activate
    def test_get_stream_url_with_pattern(self, mock_run):
        """Test getting stream URL using common patterns."""
        mock_run.side_effect = FileNotFoundError()

        # Mock first pattern URL to return 200
        responses.add(
            responses.HEAD,
            'https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8',
            status=200
        )

        service = StreamService()
        url = service.get_stream_url()

        assert url == 'https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8'

    @patch('services.subprocess.run')
    @responses.activate
    def test_get_stream_url_from_page(self, mock_run):
        """Test extracting stream URL from page HTML."""
        mock_run.side_effect = FileNotFoundError()

        # Mock pattern URLs to fail
        for pattern in StreamService().stream_url_patterns:
            responses.add(responses.HEAD, pattern, status=404)

        # Mock page with stream URL
        html_content = '''
        <html>
            <video>
                <source src="https://example.com/found.m3u8" type="application/x-mpegURL">
            </video>
        </html>
        '''
        responses.add(
            responses.GET,
            'https://video.isilive.ca/play/calgarycc/live',
            body=html_content,
            status=200
        )

        service = StreamService()
        url = service.get_stream_url()

        assert url == 'https://example.com/found.m3u8'

    @responses.activate
    def test_is_stream_live_true(self):
        """Test checking if stream is live (returns True)."""
        stream_url = 'https://example.com/stream.m3u8'
        responses.add(responses.HEAD, stream_url, status=200)

        service = StreamService()
        is_live = service.is_stream_live(stream_url)

        assert is_live is True

    @responses.activate
    def test_is_stream_live_false(self):
        """Test checking if stream is not live (returns False)."""
        stream_url = 'https://example.com/stream.m3u8'
        responses.add(responses.HEAD, stream_url, status=404)
        responses.add(responses.GET, stream_url, status=404)

        service = StreamService()
        is_live = service.is_stream_live(stream_url)

        assert is_live is False

    def test_is_stream_live_empty_url(self):
        """Test checking empty stream URL."""
        service = StreamService()
        is_live = service.is_stream_live('')

        assert is_live is False


@pytest.mark.unit
class TestRecordingService:
    """Test RecordingService class."""

    def test_init(self, temp_output_dir):
        """Test RecordingService initialization."""
        service = RecordingService(output_dir=temp_output_dir)
        assert service.output_dir == temp_output_dir
        assert service.timezone == CALGARY_TZ

    @patch('time.sleep')
    @patch('services.subprocess.Popen')
    @patch('services.db.create_recording')
    @patch('services.db.update_recording')
    @patch('services.db.log_stream_status')
    @patch('services.db.find_meeting_by_datetime')
    @patch('os.path.getsize')
    def test_record_stream_success(
        self,
        mock_getsize,
        mock_find_meeting,
        mock_log_status,
        mock_update_recording,
        mock_create_recording,
        mock_popen,
        mock_sleep,
        temp_output_dir
    ):
        """Test successful stream recording."""
        # Setup mocks
        mock_create_recording.return_value = 1
        mock_find_meeting.return_value = None
        mock_getsize.return_value = 1024 * 1024  # 1 MB

        # Mock process that ends after first check
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.side_effect = [None, 0]  # Running, then ended
        mock_popen.return_value = mock_process

        # Mock stream service
        mock_stream_service = Mock()
        mock_stream_service.is_stream_live.return_value = False

        service = RecordingService(
            output_dir=temp_output_dir,
            stream_service=mock_stream_service
        )

        result = service.record_stream('https://example.com/stream.m3u8')

        assert result is True
        mock_create_recording.assert_called_once()
        mock_update_recording.assert_called_once()

    @patch('services.subprocess.Popen')
    @patch('services.db.create_recording')
    @patch('services.db.update_recording')
    @patch('services.db.log_stream_status')
    def test_record_stream_failure(
        self,
        mock_log_status,
        mock_update_recording,
        mock_create_recording,
        mock_popen,
        temp_output_dir
    ):
        """Test recording failure handling."""
        mock_create_recording.return_value = 1
        mock_popen.side_effect = Exception("FFmpeg failed")

        service = RecordingService(output_dir=temp_output_dir)
        result = service.record_stream('https://example.com/stream.m3u8')

        assert result is False
        # Should update recording as failed
        call_args = mock_update_recording.call_args
        assert call_args[0][2] == 'failed'
