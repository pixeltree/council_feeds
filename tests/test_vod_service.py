"""Unit tests for VodService."""

import pytest
import responses
import subprocess
from datetime import datetime
from unittest.mock import Mock, patch
from services.vod_service import VodService
from config import CALGARY_TZ


@pytest.mark.unit
class TestVodService:
    """Test VodService class."""

    def test_init(self):
        """Test VodService initialization."""
        service = VodService()
        assert service.ytdlp_command is not None
        assert service.recording_format is not None
        assert service.output_dir is not None

    def test_validate_escriba_url_valid(self):
        """Test validation of valid Escriba URLs."""
        service = VodService()
        valid_urls = [
            'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=abc123',
            'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=ebebe843-9973-424f-b948-d25117da269c&Agenda=Agenda&lang=English'
        ]
        for url in valid_urls:
            assert service.validate_escriba_url(url) is True

    def test_validate_escriba_url_invalid(self):
        """Test validation of invalid Escriba URLs."""
        service = VodService()
        invalid_urls = [
            'https://evil.com/Meeting.aspx?Id=abc123',
            'https://google.com',
            'not-a-url',
            ''
        ]
        for url in invalid_urls:
            assert service.validate_escriba_url(url) is False

    def test_extract_date_from_title_various_formats(self):
        """Test date extraction from various title formats."""
        service = VodService()

        # Test "Month Day, Year" format
        title1 = "Public Hearing Meeting of Council - April 22, 2024"
        date1 = service._extract_date_from_title(title1)
        assert date1 is not None
        assert date1.year == 2024
        assert date1.month == 4
        assert date1.day == 22

        # Test "Month Day with ordinal, Year" format
        title2 = "Council Meeting - December 15th, 2023"
        date2 = service._extract_date_from_title(title2)
        assert date2 is not None
        assert date2.year == 2023
        assert date2.month == 12
        assert date2.day == 15

        # Test "YYYY-MM-DD" format
        title3 = "Meeting 2024-04-22"
        date3 = service._extract_date_from_title(title3)
        assert date3 is not None
        assert date3.year == 2024
        assert date3.month == 4
        assert date3.day == 22

        # Test no date found
        title4 = "Some Meeting Without Date"
        date4 = service._extract_date_from_title(title4)
        assert date4 is None

    @responses.activate
    def test_extract_meeting_info_success(self):
        """Test extracting meeting info from valid Escriba URL."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123&Agenda=Agenda&lang=English'

        # Mock HTML response
        html_content = """
        <html>
            <head><title>Public Hearing Meeting of Council - April 22, 2024</title></head>
            <body>
                <h1>Public Hearing Meeting of Council - April 22, 2024</h1>
                <div id="isi_player" data-client_id="calgary" data-stream_name="test.mp4"></div>
            </body>
        </html>
        """
        responses.add(
            responses.GET,
            url,
            body=html_content,
            status=200
        )

        info = service.extract_meeting_info(url)

        assert info['title'] == 'Public Hearing Meeting of Council - April 22, 2024'
        assert info['meeting_id'] == 'test123'
        assert info['link'] == url
        assert isinstance(info['datetime'], datetime)
        assert info['datetime'].year == 2024
        assert info['datetime'].month == 4
        assert info['datetime'].day == 22
        assert info['datetime'].tzinfo is not None
        assert 'timestamp' in info

    def test_extract_meeting_info_invalid_url(self):
        """Test extracting meeting info from invalid URL."""
        service = VodService()
        url = 'https://evil.com/Meeting.aspx?Id=test123'

        with pytest.raises(ValueError, match="Invalid Escriba URL"):
            service.extract_meeting_info(url)

    @responses.activate
    def test_extract_meeting_info_no_meeting_id(self):
        """Test extracting meeting info when URL has no meeting ID."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx'

        with pytest.raises(ValueError, match="Could not extract meeting ID"):
            service.extract_meeting_info(url)

    @responses.activate
    def test_extract_video_url_isilive_player(self):
        """Test extracting video URL from ISILive player data."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        # Mock HTML with ISILive player
        html_content = """
        <html>
            <body>
                <div id="isi_player"
                     data-client_id="calgary"
                     data-stream_name="Council Primary_Public Hearing Meeting of Council_2024-04-22-11-08.mp4">
                </div>
            </body>
        </html>
        """
        responses.add(
            responses.GET,
            url,
            body=html_content,
            status=200
        )

        video_url = service.extract_video_url(url)

        assert video_url is not None
        assert 'video.isilive.ca' in video_url
        assert 'calgary' in video_url
        # URL should be properly encoded (spaces become %20)
        assert 'Council%20Primary' in video_url or 'Council Primary' in video_url

    @responses.activate
    def test_extract_video_url_direct_mp4(self):
        """Test extracting direct MP4 URL from page."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        # Mock HTML with direct MP4 link
        html_content = """
        <html>
            <body>
                <video src="https://video.isilive.ca/vod/calgary/test.mp4"></video>
            </body>
        </html>
        """
        responses.add(
            responses.GET,
            url,
            body=html_content,
            status=200
        )

        video_url = service.extract_video_url(url)

        assert video_url is not None
        assert video_url.endswith('.mp4')

    @responses.activate
    def test_extract_video_url_not_found(self):
        """Test when video URL cannot be extracted."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        # Mock HTML without video player
        html_content = """
        <html>
            <body>
                <h1>Meeting Page</h1>
            </body>
        </html>
        """
        responses.add(
            responses.GET,
            url,
            body=html_content,
            status=200
        )

        video_url = service.extract_video_url(url)
        assert video_url is None

    def test_extract_video_url_invalid_url(self):
        """Test extract_video_url with invalid URL."""
        service = VodService()
        url = 'https://evil.com/Meeting.aspx?Id=test123'

        video_url = service.extract_video_url(url)
        assert video_url is None

    @responses.activate
    def test_extract_meeting_info_http_error(self):
        """Test extract_meeting_info with HTTP 500 error."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        responses.add(
            responses.GET,
            url,
            status=500
        )

        with pytest.raises(ValueError, match="Failed to fetch meeting info"):
            service.extract_meeting_info(url)

    @responses.activate
    def test_extract_meeting_info_timeout(self):
        """Test extract_meeting_info with timeout."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        responses.add(
            responses.GET,
            url,
            body=responses.ConnectionError("Connection timeout")
        )

        with pytest.raises(ValueError, match="Failed to fetch meeting info"):
            service.extract_meeting_info(url)

    @responses.activate
    def test_extract_video_url_http_error(self):
        """Test extract_video_url with HTTP error."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        responses.add(
            responses.GET,
            url,
            status=500
        )

        video_url = service.extract_video_url(url)
        assert video_url is None

    @patch('subprocess.run')
    def test_download_with_ytdlp_success(self, mock_run, tmp_path):
        """Test successful download with yt-dlp."""
        service = VodService()
        output_file = tmp_path / "recording.mkv"

        # Mock successful yt-dlp execution that creates file
        def mock_subprocess(*args, **kwargs):
            # Simulate yt-dlp creating the file
            output_file.touch()
            return Mock(returncode=0, stderr='', stdout='')

        mock_run.side_effect = mock_subprocess

        service._download_with_ytdlp('https://example.com/video', str(output_file))

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == service.ytdlp_command
        assert '--merge-output-format' in mock_run.call_args[0][0]
        assert output_file.exists()

    @patch('subprocess.run')
    def test_download_with_ytdlp_failure(self, mock_run):
        """Test yt-dlp download failure."""
        service = VodService()

        # Mock failed yt-dlp execution
        mock_run.return_value = Mock(returncode=1, stderr='Download failed', stdout='')

        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            service._download_with_ytdlp('https://example.com/video', '/tmp/output.mkv')

    @patch('subprocess.run')
    def test_download_with_ffmpeg_success(self, mock_run, tmp_path):
        """Test successful download with ffmpeg."""
        service = VodService()
        output_file = tmp_path / "recording.mkv"

        # Mock successful ffmpeg execution that creates file
        def mock_subprocess(*args, **kwargs):
            # Simulate ffmpeg creating the file
            output_file.touch()
            return Mock(returncode=0, stderr='', stdout='')

        mock_run.side_effect = mock_subprocess

        service._download_with_ffmpeg('https://example.com/video.mp4', str(output_file))

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == 'ffmpeg'
        assert '-i' in args
        assert '-c' in args
        assert 'copy' in args
        assert output_file.exists()

    @patch('subprocess.run')
    def test_download_with_ffmpeg_failure(self, mock_run):
        """Test ffmpeg download failure."""
        service = VodService()

        # Mock failed ffmpeg execution
        mock_run.return_value = Mock(returncode=1, stderr='ffmpeg error', stdout='')

        with pytest.raises(RuntimeError, match="ffmpeg download failed"):
            service._download_with_ffmpeg('https://example.com/video.mp4', '/tmp/output.mkv')

    @patch('subprocess.run')
    def test_download_with_ytdlp_timeout(self, mock_run):
        """Test yt-dlp download timeout."""
        service = VodService()

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired('yt-dlp', 3600)

        with pytest.raises(RuntimeError, match="timed out after 1 hour"):
            service._download_with_ytdlp('https://example.com/video', '/tmp/output.mkv')

    @patch('subprocess.run')
    def test_download_with_ffmpeg_timeout(self, mock_run):
        """Test ffmpeg download timeout."""
        service = VodService()

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired('ffmpeg', 3600)

        with pytest.raises(RuntimeError, match="timed out after 1 hour"):
            service._download_with_ffmpeg('https://example.com/video.mp4', '/tmp/output.mkv')

    @patch('subprocess.run')
    def test_download_with_ytdlp_no_file_created(self, mock_run):
        """Test yt-dlp completes but doesn't create file."""
        service = VodService()

        # Mock successful execution but no file created
        mock_run.return_value = Mock(returncode=0, stderr='', stdout='')

        with pytest.raises(RuntimeError, match="no output file was created"):
            service._download_with_ytdlp('https://example.com/video', '/tmp/output.mkv')

    @patch('services.vod_service.VodService._download_with_ytdlp')
    def test_download_vod_ytdlp_success(self, mock_ytdlp, tmp_path):
        """Test successful VOD download using yt-dlp."""
        service = VodService(output_dir=str(tmp_path))
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        output_file = tmp_path / "recordings" / "recording.mkv"
        output_file.parent.mkdir(parents=True)

        # Mock yt-dlp download
        def create_file(url, path):
            output_file.touch()

        mock_ytdlp.side_effect = create_file

        result = service.download_vod(url, str(output_file))

        assert result == str(output_file)
        assert output_file.exists()
        mock_ytdlp.assert_called_once()

    def test_download_vod_invalid_url(self):
        """Test download with invalid URL."""
        service = VodService()
        url = 'https://evil.com/video'

        with pytest.raises(ValueError, match="Invalid Escriba URL"):
            service.download_vod(url, '/tmp/output.mkv')

    @patch('services.vod_service.VodService._download_with_ytdlp')
    @patch('services.vod_service.VodService.extract_video_url')
    @patch('services.vod_service.VodService._download_with_ffmpeg')
    def test_download_vod_fallback_to_ffmpeg(self, mock_ffmpeg, mock_extract, mock_ytdlp, tmp_path):
        """Test VOD download falls back to ffmpeg when yt-dlp fails."""
        service = VodService(output_dir=str(tmp_path))
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        output_file = tmp_path / "recordings" / "recording.mkv"
        output_file.parent.mkdir(parents=True)

        # Mock yt-dlp failure
        mock_ytdlp.side_effect = RuntimeError("yt-dlp failed")

        # Mock video URL extraction
        mock_extract.return_value = 'https://video.isilive.ca/vod/test.mp4'

        # Mock ffmpeg success
        def create_file(url, path):
            output_file.touch()

        mock_ffmpeg.side_effect = create_file

        result = service.download_vod(url, str(output_file))

        assert result == str(output_file)
        assert output_file.exists()
        mock_ytdlp.assert_called_once()
        mock_extract.assert_called_once()
        mock_ffmpeg.assert_called_once()

    @patch('services.vod_service.VodService._download_with_ytdlp')
    @patch('services.vod_service.VodService.extract_video_url')
    def test_download_vod_all_methods_fail(self, mock_extract, mock_ytdlp):
        """Test VOD download when all methods fail."""
        service = VodService()
        url = 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'

        # Mock all methods failing
        mock_ytdlp.side_effect = RuntimeError("yt-dlp failed")
        mock_extract.return_value = None

        with pytest.raises(RuntimeError, match="Failed to download video"):
            service.download_vod(url, '/tmp/output.mkv')
