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

    @patch('post_processor.PostProcessor._detect_speech_in_sample')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_has_audio_with_speech(self, mock_duration, mock_speech):
        """Test has_audio when recording has speech content."""
        mock_duration.return_value = 3600  # 1 hour
        mock_speech.return_value = True  # Speech detected in first sample

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        assert result is True
        # Should detect speech in first sample and return early
        mock_speech.assert_called_once()

    @patch('post_processor.PostProcessor._detect_speech_in_sample')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_has_audio_no_speech(self, mock_duration, mock_speech):
        """Test has_audio when recording has no speech."""
        mock_duration.return_value = 3600  # 1 hour
        mock_speech.return_value = False  # No speech in any sample

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        assert result is False
        # Should check all samples (every 30min: 0s, 1800s, plus end at 1800s = 3 calls with dedupe)
        # For 1-hour video: samples at 0s, 1800s, 1800s(end) = 3 positions, but last 2 are same
        assert mock_speech.call_count >= 2

    @patch('post_processor.PostProcessor.get_video_duration')
    def test_has_audio_no_duration(self, mock_duration):
        """Test has_audio when duration cannot be determined."""
        mock_duration.return_value = 0

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        # Should assume has audio if duration check fails
        assert result is True

    @patch('post_processor.PostProcessor._detect_speech_in_sample')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_has_audio_timeout(self, mock_duration, mock_speech):
        """Test has_audio when speech detection times out."""
        mock_duration.return_value = 3600
        mock_speech.side_effect = subprocess.TimeoutExpired('ffmpeg', 60)

        processor = PostProcessor()
        result = processor.has_audio('/fake/video.mp4')

        # Should return False if all samples timeout/fail
        assert result is False

    @patch('post_processor.subprocess.run')
    @patch('post_processor.os.path.exists')
    def test_detect_speech_in_sample_with_speech(self, mock_exists, mock_run):
        """Test speech detection when speech is present."""
        mock_exists.return_value = True
        # Mock ffmpeg extraction success and volume detection showing speech
        mock_run.side_effect = [
            Mock(returncode=0),  # Audio extraction
            Mock(stderr="mean_volume: -30.0 dB\nmax_volume: -15.0 dB")  # Volume detect
        ]

        processor = PostProcessor()
        result = processor._detect_speech_in_sample('/fake/video.mp4', 0, 120)

        assert result is True

    @patch('post_processor.subprocess.run')
    @patch('post_processor.os.path.exists')
    def test_detect_speech_in_sample_no_speech(self, mock_exists, mock_run):
        """Test speech detection when no speech present."""
        mock_exists.return_value = True
        mock_run.side_effect = [
            Mock(returncode=0),  # Audio extraction
            Mock(stderr="mean_volume: -90.0 dB\nmax_volume: -70.0 dB")  # Very quiet
        ]

        processor = PostProcessor()
        result = processor._detect_speech_in_sample('/fake/video.mp4', 0, 120)

        assert result is False

    @patch('post_processor.subprocess.run')
    def test_get_video_duration_success(self, mock_run):
        """Test getting video duration successfully."""
        mock_run.return_value = Mock(
            stdout='{"format": {"duration": "14400.5"}}',
            returncode=0
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

    @patch('post_processor.PostProcessor.extract_wav')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_success(self, mock_duration, mock_exists, mock_has_audio, mock_extract_wav):
        """Test successful processing with WAV extraction."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = True
        mock_extract_wav.return_value = '/fake/video.wav'

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4')

        assert result['success'] is True
        assert result['wav_path'] == '/fake/video.wav'
        assert 'WAV extraction completed' in result['message']
        mock_extract_wav.assert_called_once_with('/fake/video.mp4', None)

    @patch('post_processor.db.add_recording_log')
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
        mock_update_recording,
        mock_add_log
    ):
        """Test processing deletes file when no audio detected."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = False

        processor = PostProcessor()
        result = processor.process_recording('/fake/video.mp4', recording_id=123)

        assert result['success'] is False
        assert result['deleted'] is True
        assert 'No speech detected' in result['error']
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
        assert 'No speech detected' in result['error']
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
        assert 'No speech detected' in result['error']

    @patch('post_processor.PostProcessor.extract_wav')
    @patch('post_processor.PostProcessor.has_audio')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.PostProcessor.get_video_duration')
    def test_process_recording_wav_extraction_fails(
        self,
        mock_duration,
        mock_exists,
        mock_has_audio,
        mock_extract_wav
    ):
        """Test processing when WAV extraction fails."""
        mock_exists.return_value = True
        mock_duration.return_value = 3600
        mock_has_audio.return_value = True
        mock_extract_wav.return_value = None  # Extraction failed

        processor = PostProcessor()
        result = processor.process_recording('/recordings/meeting.mp4')

        assert result['success'] is False
        assert 'WAV extraction failed' in result['error']

    @patch('post_processor.os.path.getsize')
    @patch('post_processor.os.path.exists')
    @patch('post_processor.subprocess.run')
    def test_extract_wav_success(self, mock_run, mock_exists, mock_getsize):
        """Test successful WAV extraction."""
        # First call: check if WAV exists (line 478) - False
        # Second call: check after ffmpeg (line 515) - True
        mock_exists.side_effect = [False, True]
        mock_run.return_value = Mock(returncode=0)
        mock_getsize.return_value = 1024*1024*100

        processor = PostProcessor()
        result = processor.extract_wav('/fake/video.mp4')

        assert result == '/fake/video.wav'
        mock_run.assert_called_once()

    @patch('post_processor.os.path.exists')
    def test_extract_wav_already_exists(self, mock_exists):
        """Test WAV extraction when file already exists."""
        mock_exists.return_value = True

        processor = PostProcessor()
        result = processor.extract_wav('/fake/video.mp4')

        assert result == '/fake/video.wav'

    @patch('post_processor.os.path.exists')
    @patch('post_processor.subprocess.run')
    def test_extract_wav_ffmpeg_fails(self, mock_run, mock_exists):
        """Test WAV extraction when ffmpeg fails."""
        mock_exists.return_value = False
        mock_run.return_value = Mock(returncode=1, stderr="FFmpeg error")

        processor = PostProcessor()
        result = processor.extract_wav('/fake/video.mp4')

        assert result is None
