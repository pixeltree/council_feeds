"""Unit tests for transcription service."""

import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock, mock_open

# Import will use mocked modules from conftest.py
from transcription_service import TranscriptionService


@pytest.mark.unit
class TestTranscriptionService:
    """Test TranscriptionService class."""

    def test_init_cpu_device(self):
        """Test initialization with CPU device."""
        with patch('torch.cuda.is_available', return_value=False):
            service = TranscriptionService(whisper_model="base", pyannote_api_token="test_token")
            assert service.whisper_model_name == "base"
            assert service.pyannote_api_token == "test_token"
            assert service.device == "cpu"
            assert service._whisper_model is None

    def test_init_cuda_device(self):
        """Test initialization with CUDA device."""
        with patch('torch.cuda.is_available', return_value=True):
            service = TranscriptionService()
            assert service.device == "cuda"

    def test_init_explicit_device(self):
        """Test initialization with explicit device."""
        service = TranscriptionService(device="cpu")
        assert service.device == "cpu"

    @patch('transcription_service.WhisperModel')
    def test_load_whisper_model(self, mock_whisper_model):
        """Test lazy loading of Whisper model."""
        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        service = TranscriptionService(whisper_model="tiny", device="cpu")

        # First call should load
        model = service._load_whisper_model()
        assert model == mock_model
        mock_whisper_model.assert_called_once_with("tiny", device="cpu", compute_type="int8")

        # Second call should return cached
        model2 = service._load_whisper_model()
        assert model2 == mock_model
        assert mock_whisper_model.call_count == 1  # Not called again

    def test_perform_diarization_no_token(self):
        """Test diarization fails without API token."""
        service = TranscriptionService(pyannote_api_token=None)

        with pytest.raises(ValueError, match="pyannote.ai API token required"):
            service.perform_diarization('/fake/audio.wav')

    @patch('os.path.getsize')
    @patch('builtins.open', mock_open(read_data=b'fake audio data'))
    @patch('requests.put')
    @patch('requests.post')
    def test_perform_diarization_api_success(self, mock_post, mock_put, mock_getsize):
        """Test diarization via API."""
        mock_getsize.return_value = 1024 * 1024  # 1 MB

        # Mock the upload URL response
        mock_upload_response = Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {'url': 'https://fake-upload-url.com'}

        # Mock the file upload response
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock the diarization job response (sync)
        mock_diarization_response = Mock()
        mock_diarization_response.status_code = 200
        mock_diarization_response.json.return_value = {
            'diarization': [
                {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'}
            ]
        }

        # Setup post to return different responses based on call
        mock_post.side_effect = [mock_upload_response, mock_diarization_response]

        service = TranscriptionService(pyannote_api_token="test_token", device="cpu")

        segments = service.perform_diarization('/fake/audio.wav')

        assert len(segments) == 1
        assert segments[0]['start'] == 0.0
        assert segments[0]['end'] == 10.0
        assert segments[0]['speaker'] == 'SPEAKER_00'
        assert mock_post.call_count == 2

    def test_merge_transcription_and_diarization(self):
        """Test merging transcription with diarization."""
        service = TranscriptionService()

        transcription = {
            'segments': [
                {'start': 0.0, 'end': 5.0, 'text': ' Hello everyone'},
                {'start': 5.0, 'end': 10.0, 'text': ' Welcome to the meeting'},
                {'start': 10.0, 'end': 15.0, 'text': ' Thank you for joining'}
            ]
        }

        diarization_segments = [
            {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'},
            {'start': 10.0, 'end': 20.0, 'speaker': 'SPEAKER_01'}
        ]

        merged = service.merge_transcription_and_diarization(
            transcription, diarization_segments
        )

        assert len(merged) == 3
        assert merged[0]['speaker'] == 'SPEAKER_00'
        assert merged[0]['text'] == 'Hello everyone'
        assert merged[1]['speaker'] == 'SPEAKER_00'
        assert merged[2]['speaker'] == 'SPEAKER_01'

    def test_find_speaker_for_segment_perfect_overlap(self):
        """Test finding speaker with perfect overlap."""
        service = TranscriptionService()

        diarization = [
            {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'},
            {'start': 10.0, 'end': 20.0, 'speaker': 'SPEAKER_01'}
        ]

        # Segment entirely within first speaker
        speaker_info = service._find_speaker_for_segment(2.0, 8.0, diarization)
        assert speaker_info['speaker'] == 'SPEAKER_00'

        # Segment entirely within second speaker
        speaker_info = service._find_speaker_for_segment(12.0, 18.0, diarization)
        assert speaker_info['speaker'] == 'SPEAKER_01'

    def test_find_speaker_for_segment_partial_overlap(self):
        """Test finding speaker with partial overlap (picks best)."""
        service = TranscriptionService()

        diarization = [
            {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'},
            {'start': 10.0, 'end': 20.0, 'speaker': 'SPEAKER_01'}
        ]

        # Segment spanning both speakers - more overlap with first
        speaker_info = service._find_speaker_for_segment(8.0, 12.0, diarization)
        assert speaker_info['speaker'] == 'SPEAKER_00'

        # Segment spanning both speakers - more overlap with second
        speaker_info = service._find_speaker_for_segment(9.0, 15.0, diarization)
        assert speaker_info['speaker'] == 'SPEAKER_01'

    def test_find_speaker_for_segment_no_overlap(self):
        """Test finding speaker with no overlap returns UNKNOWN."""
        service = TranscriptionService()

        diarization = [
            {'start': 10.0, 'end': 20.0, 'speaker': 'SPEAKER_00'}
        ]

        # Segment before any diarization
        speaker_info = service._find_speaker_for_segment(0.0, 5.0, diarization)
        assert speaker_info['speaker'] == 'UNKNOWN'

    def test_format_transcript_as_text(self):
        """Test formatting transcript as readable text."""
        service = TranscriptionService()

        segments = [
            {'start': 0.0, 'end': 5.0, 'text': 'Hello everyone', 'speaker': 'SPEAKER_00'},
            {'start': 5.0, 'end': 10.0, 'text': 'Welcome', 'speaker': 'SPEAKER_00'},
            {'start': 10.0, 'end': 15.0, 'text': 'Thank you', 'speaker': 'SPEAKER_01'},
            {'start': 15.0, 'end': 20.0, 'text': 'You\'re welcome', 'speaker': 'SPEAKER_00'}
        ]

        text = service.format_transcript_as_text(segments)

        assert '[SPEAKER_00]' in text
        assert '[SPEAKER_01]' in text
        assert 'Hello everyone' in text
        assert 'Thank you' in text
        assert text.count('[SPEAKER_00]') == 2  # Speaker changes back
        assert text.count('[SPEAKER_01]') == 1

    @patch('requests.put')
    @patch('os.path.getsize')
    @patch('subprocess.run')
    @patch('transcription_service.TranscriptionService._load_whisper_model')
    @patch('requests.post')
    @patch('os.path.exists')
    def test_transcribe_with_speakers_success(self, mock_exists, mock_post, mock_load_whisper, mock_subprocess, mock_getsize, mock_put):
        """Test complete transcription pipeline."""
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 * 1024  # 1 MB

        # Mock subprocess.run for ffmpeg audio extraction
        mock_subprocess.return_value = Mock(returncode=0)

        # Mock Whisper model (faster-whisper returns segments generator and info tuple)
        mock_whisper = Mock()
        mock_segment = Mock()
        mock_segment.start = 0.0
        mock_segment.end = 5.0
        mock_segment.text = ' Hello'
        mock_info = Mock()
        mock_info.language = 'en'
        mock_whisper.transcribe.return_value = ([mock_segment], mock_info)
        mock_load_whisper.return_value = mock_whisper

        # Mock file upload
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock API responses for diarization
        mock_upload_response = Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {'url': 'https://fake-upload-url.com'}

        mock_diarization_response = Mock()
        mock_diarization_response.status_code = 200
        mock_diarization_response.json.return_value = {
            'diarization': [
                {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'}
            ]
        }
        mock_post.side_effect = [mock_upload_response, mock_diarization_response]

        service = TranscriptionService(pyannote_api_token="test_token")

        # Test without saving to file
        with patch('builtins.open', mock_open()), \
             patch('tempfile.NamedTemporaryFile') as mock_temp, \
             patch('os.remove'):
            # Mock the temporary file
            mock_temp_file = Mock()
            mock_temp_file.name = '/tmp/test.wav'
            mock_temp.__enter__ = Mock(return_value=mock_temp_file)
            mock_temp.__exit__ = Mock(return_value=False)
            mock_temp.return_value = mock_temp

            result = service.transcribe_with_speakers(
                '/fake/video.mp4',
                save_to_file=False
            )

        assert result['file'] == '/fake/video.mp4'
        assert result['language'] == 'en'
        assert ' Hello' in result['full_text']
        assert len(result['segments']) == 1
        assert result['segments'][0]['speaker'] == 'SPEAKER_00'
        assert result['num_speakers'] == 1

    def test_transcribe_with_speakers_file_not_found(self):
        """Test transcription fails if file doesn't exist."""
        service = TranscriptionService()

        with pytest.raises(FileNotFoundError):
            service.transcribe_with_speakers('/nonexistent/file.mp4')

    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_extract_audio_to_wav_creates_persistent_file(self, mock_exists, mock_subprocess):
        """Test audio extraction creates persistent WAV file next to video."""
        mock_exists.return_value = False  # WAV doesn't exist yet
        mock_subprocess.return_value = Mock(returncode=0)

        service = TranscriptionService()
        result_path = service.extract_audio_to_wav('/fake/video.mp4')

        # Should save next to video file, not in temp directory
        assert result_path == '/fake/video.wav'
        mock_subprocess.assert_called_once()
        # Verify ffmpeg was called with correct parameters
        call_args = mock_subprocess.call_args[0][0]
        assert 'ffmpeg' in call_args
        assert '-i' in call_args
        assert '/fake/video.mp4' in call_args
        assert '-acodec' in call_args
        assert 'pcm_s16le' in call_args
        assert '-ar' in call_args
        assert '16000' in call_args
        assert '-ac' in call_args
        assert '1' in call_args
        assert '/fake/video.wav' in call_args

    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_extract_audio_to_wav_reuses_existing(self, mock_exists, mock_subprocess):
        """Test audio extraction skips extraction if WAV already exists."""
        mock_exists.return_value = True  # WAV already exists

        service = TranscriptionService()
        result_path = service.extract_audio_to_wav('/fake/video.mp4')

        # Should return existing path without calling ffmpeg
        assert result_path == '/fake/video.wav'
        mock_subprocess.assert_not_called()

    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_extract_audio_to_wav_with_output_path(self, mock_exists, mock_subprocess):
        """Test audio extraction with specified output path."""
        mock_exists.return_value = False  # Custom path doesn't exist yet
        mock_subprocess.return_value = Mock(returncode=0)

        service = TranscriptionService()
        result_path = service.extract_audio_to_wav('/fake/video.mp4', '/output/audio.wav')

        assert result_path == '/output/audio.wav'
        call_args = mock_subprocess.call_args[0][0]
        assert '/output/audio.wav' in call_args

    @patch('requests.put')
    @patch('os.path.getsize')
    @patch('subprocess.run')
    @patch('transcription_service.TranscriptionService._load_whisper_model')
    @patch('requests.post')
    @patch('os.path.exists')
    @patch('os.remove')
    def test_transcribe_with_speakers_extracts_audio_once(self, mock_remove, mock_exists, mock_post, mock_load_whisper, mock_subprocess, mock_getsize, mock_put):
        """Test that transcribe_with_speakers extracts audio once for both Whisper and diarization."""
        mock_getsize.return_value = 1024 * 1024  # 1 MB
        # Video exists, WAV doesn't exist initially, then exists for cleanup
        def exists_side_effect(path):
            if path == '/fake/video.mp4':
                return True
            elif path == '/fake/video.wav':
                # First call during extraction check: False (needs extraction)
                # Second call during cleanup check: True (exists to be deleted)
                if not hasattr(exists_side_effect, 'wav_call_count'):
                    exists_side_effect.wav_call_count = 0
                exists_side_effect.wav_call_count += 1
                return exists_side_effect.wav_call_count > 1
            return False

        mock_exists.side_effect = exists_side_effect
        mock_subprocess.return_value = Mock(returncode=0)

        # Mock Whisper model
        mock_whisper = Mock()
        mock_segment = Mock()
        mock_segment.start = 0.0
        mock_segment.end = 5.0
        mock_segment.text = ' Test audio'
        mock_info = Mock()
        mock_info.language = 'en'
        mock_whisper.transcribe.return_value = ([mock_segment], mock_info)
        mock_load_whisper.return_value = mock_whisper

        # Mock file upload
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock API responses for diarization
        mock_upload_response = Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {'url': 'https://fake-upload-url.com'}

        mock_diarization_response = Mock()
        mock_diarization_response.status_code = 200
        mock_diarization_response.json.return_value = {
            'diarization': [
                {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'}
            ]
        }
        mock_post.side_effect = [mock_upload_response, mock_diarization_response]

        service = TranscriptionService(pyannote_api_token="test_token")

        with patch('builtins.open', mock_open()):
            result = service.transcribe_with_speakers(
                '/fake/video.mp4',
                save_to_file=False
            )

        # Verify ffmpeg was called exactly once for audio extraction
        ffmpeg_calls = [call for call in mock_subprocess.call_args_list if 'ffmpeg' in str(call)]
        assert len(ffmpeg_calls) == 1, "Audio should be extracted only once"

        # Verify both Whisper and diarization used the extracted audio
        mock_whisper.transcribe.assert_called_once()
        assert mock_post.call_count == 2  # Upload URL + diarization API

        # Verify the same audio path was used for both
        whisper_audio_path = mock_whisper.transcribe.call_args[0][0]
        assert whisper_audio_path == '/fake/video.wav', "Should use persistent WAV file"

        # Verify WAV file was cleaned up after successful transcription
        mock_remove.assert_called_once_with('/fake/video.wav')

        # Verify result
        assert result['file'] == '/fake/video.mp4'
        assert result['num_speakers'] == 1

    @patch('requests.put')
    @patch('os.path.getsize')
    @patch('subprocess.run')
    @patch('transcription_service.TranscriptionService._load_whisper_model')
    @patch('requests.post')
    @patch('os.path.exists')
    @patch('os.remove')
    def test_transcribe_with_speakers_resumes_after_failure(self, mock_remove, mock_exists, mock_post, mock_load_whisper, mock_subprocess, mock_getsize, mock_put):
        """Test that transcribe_with_speakers can resume using existing WAV after failure."""
        mock_getsize.return_value = 1024 * 1024  # 1 MB
        # Video exists, WAV already exists (from previous failed attempt)
        mock_exists.return_value = True
        mock_subprocess.return_value = Mock(returncode=0)

        # Mock Whisper model
        mock_whisper = Mock()
        mock_segment = Mock()
        mock_segment.start = 0.0
        mock_segment.end = 5.0
        mock_segment.text = ' Test audio'
        mock_info = Mock()
        mock_info.language = 'en'
        mock_whisper.transcribe.return_value = ([mock_segment], mock_info)
        mock_load_whisper.return_value = mock_whisper

        # Mock file upload
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock API responses for diarization
        mock_upload_response = Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {'url': 'https://fake-upload-url.com'}

        mock_diarization_response = Mock()
        mock_diarization_response.status_code = 200
        mock_diarization_response.json.return_value = {
            'diarization': [
                {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'}
            ]
        }
        mock_post.side_effect = [mock_upload_response, mock_diarization_response]

        service = TranscriptionService(pyannote_api_token="test_token")

        with patch('builtins.open', mock_open()):
            result = service.transcribe_with_speakers(
                '/fake/video.mp4',
                save_to_file=False
            )

        # Verify ffmpeg was NOT called (reused existing WAV)
        mock_subprocess.assert_not_called()

        # Verify both Whisper and diarization still worked
        mock_whisper.transcribe.assert_called_once()
        assert mock_post.call_count == 2  # Upload URL + diarization API

        # Verify WAV file was cleaned up after successful transcription
        mock_remove.assert_called_once_with('/fake/video.wav')

        # Verify result
        assert result['file'] == '/fake/video.mp4'
        assert result['num_speakers'] == 1

    @patch('requests.put')
    @patch('os.path.getsize')
    @patch('builtins.open', mock_open(read_data=b'fake audio data'))
    @patch('subprocess.run')
    @patch('requests.post')
    @patch('os.path.exists')
    def test_perform_diarization_accepts_wav_directly(self, mock_exists, mock_post, mock_subprocess, mock_getsize, mock_put):
        """Test that perform_diarization accepts WAV files directly without conversion."""
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 * 1024  # 1 MB

        # Mock file upload
        mock_put_response = Mock()
        mock_put_response.status_code = 200
        mock_put.return_value = mock_put_response

        # Mock API responses for diarization
        mock_upload_response = Mock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {'url': 'https://fake-upload-url.com'}

        mock_diarization_response = Mock()
        mock_diarization_response.status_code = 200
        mock_diarization_response.json.return_value = {
            'diarization': [
                {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00'}
            ]
        }
        mock_post.side_effect = [mock_upload_response, mock_diarization_response]

        service = TranscriptionService(pyannote_api_token="test_token")
        segments = service.perform_diarization('/fake/audio.wav')

        # Verify no subprocess (ffmpeg) was called since it's already WAV
        mock_subprocess.assert_not_called()

        # Verify diarization API was called
        assert mock_post.call_count == 2
        assert len(segments) == 1
        assert segments[0]['speaker'] == 'SPEAKER_00'

    @patch('transcription_service.json.dump')
    def test_save_transcript(self, mock_json_dump):
        """Test saving transcript to file."""
        service = TranscriptionService()

        transcript = {
            'file': '/test/video.mp4',
            'segments': [],
            'num_speakers': 2
        }

        m = mock_open()
        with patch('builtins.open', m):
            service.save_transcript(transcript, '/test/output.json')

        m.assert_called_once_with('/test/output.json', 'w', encoding='utf-8')
        mock_json_dump.assert_called_once()
        assert mock_json_dump.call_args[0][0] == transcript
