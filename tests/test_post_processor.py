"""Unit tests for post-processing service."""

import pytest
import os
import subprocess
from unittest.mock import Mock, patch, MagicMock, call
from post_processor import PostProcessor


@pytest.mark.unit
class TestPostProcessor:
    """Test PostProcessor class."""

    def test_init(self):
        """Test PostProcessor initialization."""
        processor = PostProcessor(
            silence_threshold_db=-35,
            min_silence_duration=180,
            ffmpeg_command="/usr/bin/ffmpeg",
            ffprobe_command="/usr/bin/ffprobe"
        )

        assert processor.silence_threshold_db == -35
        assert processor.min_silence_duration == 180
        assert processor.ffmpeg_command == "/usr/bin/ffmpeg"
        assert processor.ffprobe_command == "/usr/bin/ffprobe"

    def test_init_defaults(self):
        """Test PostProcessor with default values."""
        processor = PostProcessor()

        assert processor.silence_threshold_db == -40
        assert processor.min_silence_duration == 120
        assert processor.ffmpeg_command == "ffmpeg"
        assert processor.ffprobe_command == "ffprobe"

    @patch('post_processor.subprocess.run')
    def test_detect_silent_periods_success(self, mock_run):
        """Test detecting silent periods successfully."""
        mock_run.return_value = Mock(
            stderr="""
            [silencedetect @ 0x123] silence_start: 600.5
            [silencedetect @ 0x123] silence_end: 720.8 | silence_duration: 120.3
            [silencedetect @ 0x123] silence_start: 1800.0
            [silencedetect @ 0x123] silence_end: 2100.5 | silence_duration: 300.5
            """
        )

        processor = PostProcessor()
        periods = processor.detect_silent_periods('/fake/video.mp4')

        assert len(periods) == 2
        assert periods[0] == (600.5, 720.8)
        assert periods[1] == (1800.0, 2100.5)

    @patch('post_processor.subprocess.run')
    def test_detect_silent_periods_no_silence(self, mock_run):
        """Test when no silent periods are found."""
        mock_run.return_value = Mock(stderr="No silence detected")

        processor = PostProcessor()
        periods = processor.detect_silent_periods('/fake/video.mp4')

        assert len(periods) == 0

    @patch('post_processor.subprocess.run')
    def test_detect_silent_periods_timeout(self, mock_run):
        """Test handling timeout during silence detection."""
        mock_run.side_effect = subprocess.TimeoutExpired('ffmpeg', 300)

        processor = PostProcessor()
        periods = processor.detect_silent_periods('/fake/video.mp4')

        assert len(periods) == 0

    @patch('post_processor.subprocess.run')
    def test_detect_silent_periods_error(self, mock_run):
        """Test handling errors during silence detection."""
        mock_run.side_effect = Exception("FFmpeg error")

        processor = PostProcessor()
        periods = processor.detect_silent_periods('/fake/video.mp4')

        assert len(periods) == 0

    @patch('post_processor.subprocess.run')
    def test_has_audio_with_audio(self, mock_run):
        """Test has_audio when recording has audio content."""
        mock_run.return_value = Mock(
            stderr="""
            [Parsed_volumedetect_0 @ 0x123] mean_volume: -25.5 dB
            [Parsed_volumedetect_0 @ 0x123] max_volume: -10.2 dB
            """
        )

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        assert result is True

    @patch('post_processor.subprocess.run')
    def test_has_audio_silent_recording(self, mock_run):
        """Test has_audio when recording is silent."""
        mock_run.return_value = Mock(
            stderr="""
            [Parsed_volumedetect_0 @ 0x123] mean_volume: -55.0 dB
            [Parsed_volumedetect_0 @ 0x123] max_volume: -35.0 dB
            """
        )

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        assert result is False

    @patch('post_processor.subprocess.run')
    def test_has_audio_no_audio_stream(self, mock_run):
        """Test has_audio when no audio stream detected."""
        mock_run.return_value = Mock(stderr="No audio stream found")

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        assert result is False

    @patch('post_processor.subprocess.run')
    def test_has_audio_timeout(self, mock_run):
        """Test has_audio when analysis times out."""
        mock_run.side_effect = subprocess.TimeoutExpired('ffmpeg', 300)

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        # Should assume has audio if check fails
        assert result is True

    @patch('post_processor.subprocess.run')
    def test_has_audio_error(self, mock_run):
        """Test has_audio when error occurs."""
        mock_run.side_effect = Exception("FFmpeg error")

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        # Should assume has audio if check fails
        assert result is True

    @patch('post_processor.subprocess.run')
    def test_get_video_duration_success(self, mock_run):
        """Test getting video duration successfully."""
        mock_run.return_value = Mock(
            stdout='{"format": {"duration": "14400.5"}}'
        )

        processor = PostProcessor()
        duration = processor.get_video_duration('/fake/video.mp4')

        assert duration == 14400.5
        mock_run.assert_called_once()
        assert processor.ffprobe_command in mock_run.call_args[0][0]

    @patch('post_processor.subprocess.run')
    def test_get_video_duration_error(self, mock_run):
        """Test handling error when getting duration."""
        mock_run.side_effect = Exception("FFprobe error")

        processor = PostProcessor()
        duration = processor.get_video_duration('/fake/video.mp4')

        assert duration == 0

    def test_calculate_segments_no_silence(self):
        """Test calculating segments when no silence detected."""
        processor = PostProcessor()
        segments = processor.calculate_segments(3600, [])

        assert len(segments) == 0

    def test_calculate_segments_single_break(self):
        """Test calculating segments with single break."""
        processor = PostProcessor()
        silent_periods = [(1800, 2400)]  # 10-20 minute break

        segments = processor.calculate_segments(7200, silent_periods)

        assert len(segments) == 2
        assert segments[0] == (0, 1800)  # Before break
        assert segments[1] == (2400, 7200)  # After break

    def test_calculate_segments_multiple_breaks(self):
        """Test calculating segments with multiple breaks."""
        processor = PostProcessor()
        silent_periods = [
            (1800, 2100),  # First break
            (3600, 3900)   # Second break
        ]

        segments = processor.calculate_segments(7200, silent_periods)

        assert len(segments) == 3
        assert segments[0] == (0, 1800)
        assert segments[1] == (2100, 3600)
        assert segments[2] == (3900, 7200)

    def test_calculate_segments_ignores_short_segments(self):
        """Test that very short segments are ignored."""
        processor = PostProcessor()
        # Short segment at the start (< 30 seconds)
        silent_periods = [(15, 1800)]

        segments = processor.calculate_segments(3600, silent_periods)

        # Should only have segment after the break
        assert len(segments) == 1
        assert segments[0] == (1800, 3600)

    @patch('post_processor.os.path.getsize')
    @patch('post_processor.subprocess.run')
    def test_extract_segment_success(self, mock_run, mock_getsize):
        """Test extracting segment successfully."""
        mock_run.return_value = Mock(returncode=0)
        mock_getsize.return_value = 1024 * 1024

        processor = PostProcessor()
        result = processor.extract_segment(
            '/input.mp4',
            '/output.mp4',
            start=100.0,
            end=200.0
        )

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert processor.ffmpeg_command in cmd
        assert '-ss' in cmd
        assert '-t' in cmd
        assert '-c' in cmd
        assert 'copy' in cmd

    @patch('post_processor.subprocess.run')
    def test_extract_segment_error(self, mock_run):
        """Test handling error during segment extraction."""
        mock_run.side_effect = Exception("FFmpeg failed")

        processor = PostProcessor()
        result = processor.extract_segment(
            '/input.mp4',
            '/output.mp4',
            start=100.0,
            end=200.0
        )

        assert result is False

    def test_process_recording_file_not_found(self):
        """Test processing when file doesn't exist."""
        processor = PostProcessor()
        result = processor.process_recording('/nonexistent/file.mp4')

        assert result['success'] is False
        assert 'not found' in result['error'].lower()

    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_no_duration(self, mock_duration, mock_exists):
        """Test processing when duration cannot be determined."""
        mock_exists.return_value = True
        mock_duration.return_value = 0

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4')

        assert result['success'] is False
        assert 'duration' in result['error'].lower()

    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    @patch('post_processor.PostProcessor.detect_silent_periods')
    def test_process_recording_no_breaks(self, mock_detect, mock_duration, mock_exists, mock_has_audio):
        """Test processing when no breaks detected."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = True
        mock_detect.return_value = []

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4')

        assert result['success'] is True
        assert result['segments_created'] == 0
        assert 'No breaks detected' in result['message']

    @patch('post_processor.db.update_recording')
    @patch('post_processor.os.remove')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_no_audio_deletes_file(
        self,
        mock_duration,
        mock_exists,
        mock_has_audio,
        mock_remove,
        mock_update_recording
    ):
        """Test processing deletes file when no audio detected."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = False

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4', recording_id=123)

        assert result['success'] is False
        assert result['deleted'] is True
        assert 'No audio detected' in result['error']
        mock_remove.assert_called_once_with('/fake/video.mp4')
        mock_update_recording.assert_called_once()

    @patch('post_processor.os.remove')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_no_audio_without_recording_id(
        self,
        mock_duration,
        mock_exists,
        mock_has_audio,
        mock_remove
    ):
        """Test processing deletes file when no audio and no recording_id."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = False

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4')

        assert result['success'] is False
        assert result['deleted'] is True
        assert 'No audio detected' in result['error']
        mock_remove.assert_called_once_with('/fake/video.mp4')

    @patch('post_processor.os.remove')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_no_audio_delete_fails(
        self,
        mock_duration,
        mock_exists,
        mock_has_audio,
        mock_remove
    ):
        """Test processing handles delete failure gracefully."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = False
        mock_remove.side_effect = OSError("Permission denied")

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4')

        assert result['success'] is False
        assert result['deleted'] is True
        assert 'No audio detected' in result['error']

    @patch('shutil.copy2')
    @patch('post_processor.os.path.getsize')
    @patch('post_processor.os.makedirs')
    @patch('post_processor.PostProcessor.extract_segment')
    @patch('post_processor.PostProcessor.detect_silent_periods')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.PostProcessor.get_video_duration')
    @patch('post_processor.os.path.exists')
    def test_process_recording_with_segments(
        self,
        mock_exists,
        mock_duration,
        mock_has_audio,
        mock_detect,
        mock_extract,
        mock_makedirs,
        mock_getsize,
        mock_copy
    ):
        """Test full processing with segment creation."""
        mock_exists.return_value = True
        mock_duration.return_value = 7200  # 2 hours
        mock_has_audio.return_value = True
        mock_detect.return_value = [(1800, 2100)]  # 5-minute break
        mock_extract.return_value = True
        mock_getsize.return_value = 1024 * 1024 * 100  # 100 MB

        processor = PostProcessor()
        result = processor.process_recording('/recordings/meeting.mp4')

        assert result['success'] is True
        assert result['segments_created'] == 2
        assert 'output_dir' in result
        assert 'segment_files' in result
        assert len(result['segment_files']) == 2

        # Verify segments were created
        assert result['segment_files'][0]['segment'] == 1
        assert result['segment_files'][1]['segment'] == 2

        # Verify extract was called for each segment
        assert mock_extract.call_count == 2

    @patch('shutil.copy2')
    @patch('post_processor.os.path.getsize')
    @patch('post_processor.os.makedirs')
    @patch('post_processor.PostProcessor.extract_segment')
    @patch('post_processor.PostProcessor.detect_silent_periods')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.PostProcessor.get_video_duration')
    @patch('post_processor.os.path.exists')
    def test_process_recording_partial_failure(
        self,
        mock_exists,
        mock_duration,
        mock_has_audio,
        mock_detect,
        mock_extract,
        mock_makedirs,
        mock_getsize,
        mock_copy
    ):
        """Test processing when some segment extractions fail."""
        mock_exists.return_value = True
        mock_duration.return_value = 7200
        mock_has_audio.return_value = True
        mock_detect.return_value = [(1800, 2100)]
        # First extract succeeds, second fails
        mock_extract.side_effect = [True, False]
        mock_getsize.return_value = 1024 * 1024 * 100

        processor = PostProcessor()
        result = processor.process_recording('/recordings/meeting.mp4')

        assert result['success'] is True
        assert result['segments_created'] == 1  # Only 1 succeeded
        assert len(result['segment_files']) == 1
