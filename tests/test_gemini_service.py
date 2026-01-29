"""Unit tests for Gemini service."""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import gemini_service


# Sample test data
SAMPLE_PYANNOTE_JSON = {
    'file': '/test/recording.mp4',
    'segments': [
        {'start': 0.0, 'end': 10.0, 'speaker': 'SPEAKER_00', 'text': 'Good morning everyone'},
        {'start': 10.0, 'end': 20.0, 'speaker': 'SPEAKER_01', 'text': 'Thank you for having me'},
        {'start': 20.0, 'end': 30.0, 'speaker': 'SPEAKER_00', 'text': 'Let us begin'}
    ],
    'num_speakers': 2
}

SAMPLE_EXPECTED_SPEAKERS = [
    {'name': 'Jyoti Gondek', 'role': 'Mayor', 'confidence': 'high'},
    {'name': 'Andre Chabot', 'role': 'Councillor', 'confidence': 'high'}
]

SAMPLE_GEMINI_RESPONSE = {
    'file': '/test/recording.mp4',
    'segments': [
        {'start': 0.0, 'end': 10.0, 'speaker': 'Jyoti Gondek', 'text': 'Good morning everyone'},
        {'start': 10.0, 'end': 20.0, 'speaker': 'Andre Chabot', 'text': 'Thank you for having me'},
        {'start': 20.0, 'end': 30.0, 'speaker': 'Jyoti Gondek', 'text': 'Let us begin'}
    ],
    'num_speakers': 2
}


@pytest.mark.unit
class TestGeminiService:
    """Test Gemini service functions."""

    def test_refine_diarization_no_api_key(self):
        """Test that missing API key returns original JSON."""
        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key=None
        )

        assert result == SAMPLE_PYANNOTE_JSON
        assert 'refined_by' not in result

    def test_refine_diarization_empty_api_key(self):
        """Test that empty API key returns original JSON."""
        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key=''
        )

        assert result == SAMPLE_PYANNOTE_JSON

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_empty_speakers_list(self, mock_types, mock_model_class, mock_configure):
        """Test refinement works with no expected speakers."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        # Mock the API to return the original JSON
        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.text = json.dumps(SAMPLE_PYANNOTE_JSON)
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            [],  # Empty speakers list
            'Council Meeting',
            api_key='test_key'
        )

        # Should still attempt refinement
        assert mock_model.generate_content.called

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_success(self, mock_types, mock_model_class, mock_configure):
        """Test successful diarization refinement."""
        # Setup mocks
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.text = json.dumps(SAMPLE_GEMINI_RESPONSE)
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key',
            model='gemini-1.5-flash',
            timeout=30
        )

        # Verify API was configured
        mock_configure.assert_called_once_with(api_key='test_key')

        # Verify model was created
        mock_model_class.assert_called_once_with('gemini-1.5-flash')

        # Verify generate_content was called with timeout
        mock_model.generate_content.assert_called_once()
        call_kwargs = mock_model.generate_content.call_args[1]
        assert 'request_options' in call_kwargs
        assert call_kwargs['generation_config']['temperature'] == 0.1

        # Verify result has metadata
        assert result['refined_by'] == 'gemini'
        assert result['model'] == 'gemini-1.5-flash'
        assert 'timestamp' in result
        assert result['segments'] == SAMPLE_GEMINI_RESPONSE['segments']

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_api_failure(self, mock_types, mock_model_class, mock_configure):
        """Test that API failure returns original JSON."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API Error")
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key'
        )

        assert result == SAMPLE_PYANNOTE_JSON
        assert 'refined_by' not in result

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_invalid_json_response(self, mock_types, mock_model_class, mock_configure):
        """Test handling of invalid JSON in response."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.text = "This is not valid JSON"
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key'
        )

        assert result == SAMPLE_PYANNOTE_JSON
        assert 'refined_by' not in result

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_timeout(self, mock_types, mock_model_class, mock_configure):
        """Test timeout handling."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = TimeoutError("Request timed out")
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key',
            timeout=30
        )

        assert result == SAMPLE_PYANNOTE_JSON
        assert 'refined_by' not in result

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_preserves_timestamps(self, mock_types, mock_model_class, mock_configure):
        """Test that timestamps are preserved exactly."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.text = json.dumps(SAMPLE_GEMINI_RESPONSE)
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key'
        )

        # Verify timestamps match
        for i, segment in enumerate(result['segments']):
            assert segment['start'] == SAMPLE_GEMINI_RESPONSE['segments'][i]['start']
            assert segment['end'] == SAMPLE_GEMINI_RESPONSE['segments'][i]['end']

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    @patch('google.generativeai.types')
    def test_refine_diarization_adds_metadata(self, mock_types, mock_model_class, mock_configure):
        """Test that refinement metadata is added."""
        mock_request_options = Mock()
        mock_types.RequestOptions.return_value = mock_request_options

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.text = json.dumps(SAMPLE_GEMINI_RESPONSE)
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        result = gemini_service.refine_diarization(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting',
            api_key='test_key',
            model='gemini-1.5-pro'
        )

        assert result['refined_by'] == 'gemini'
        assert result['model'] == 'gemini-1.5-pro'
        assert 'timestamp' in result
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(result['timestamp'])
        assert result['original_file'] == SAMPLE_PYANNOTE_JSON['file']

    def test_refine_diarization_import_error(self):
        """Test handling when google-generativeai is not installed."""
        with patch('builtins.__import__', side_effect=ImportError("No module named 'google.generativeai'")):
            result = gemini_service.refine_diarization(
                SAMPLE_PYANNOTE_JSON,
                SAMPLE_EXPECTED_SPEAKERS,
                'Council Meeting',
                api_key='test_key'
            )

            assert result == SAMPLE_PYANNOTE_JSON

    def test_refine_diarization_large_meeting_warning(self, capfd):
        """Test that large meetings trigger a warning."""
        # Create a large diarization with 800 segments (enough to trigger warning)
        # Each segment with text averages ~100 chars, so 800 segments * 100 = 80,000 chars / 4 = 20k tokens
        # But with full JSON structure it should exceed 30k tokens
        large_diarization = {
            'file': '/test/long_meeting.mp4',
            'segments': [
                {
                    'start': float(i),
                    'end': float(i+1),
                    'speaker': f'SPEAKER_{i%5}',
                    'text': f'This is a longer segment with more text to increase token count segment {i} with additional context'
                }
                for i in range(800)
            ],
            'num_speakers': 5
        }

        with patch('google.generativeai.configure'), \
             patch('google.generativeai.GenerativeModel') as mock_model_class, \
             patch('google.generativeai.types') as mock_types:

            mock_request_options = Mock()
            mock_types.RequestOptions.return_value = mock_request_options

            mock_model = MagicMock()
            mock_response = Mock()
            mock_response.text = json.dumps(large_diarization)
            mock_model.generate_content.return_value = mock_response
            mock_model_class.return_value = mock_model

            gemini_service.refine_diarization(
                large_diarization,
                SAMPLE_EXPECTED_SPEAKERS,
                'Long Council Meeting',
                api_key='test_key'
            )

            captured = capfd.readouterr()
            assert 'WARNING: Diarization is very large' in captured.out

    def test_refine_diarization_skips_huge_meetings(self, capfd):
        """Test that meetings with >1000 segments are skipped."""
        # Create a huge diarization with 1500 segments
        huge_diarization = {
            'file': '/test/very_long_meeting.mp4',
            'segments': [
                {'start': float(i), 'end': float(i+1), 'speaker': f'SPEAKER_{i%5}', 'text': f'Segment {i}'}
                for i in range(1500)
            ],
            'num_speakers': 5
        }

        result = gemini_service.refine_diarization(
            huge_diarization,
            SAMPLE_EXPECTED_SPEAKERS,
            'Very Long Council Meeting',
            api_key='test_key'
        )

        # Should return original without calling API
        assert result == huge_diarization
        assert 'refined_by' not in result

        captured = capfd.readouterr()
        # Check that it logs skipping (this happens before the try/except block)
        assert ('Skipping refinement' in captured.out or
                'too large' in captured.out or
                '1500 segments' in captured.out)


@pytest.mark.unit
class TestConstructPrompt:
    """Test _construct_prompt helper function."""

    def test_construct_prompt_with_speakers(self):
        """Test prompt construction with speakers list."""
        prompt = gemini_service._construct_prompt(
            SAMPLE_PYANNOTE_JSON,
            SAMPLE_EXPECTED_SPEAKERS,
            'Council Meeting'
        )

        assert 'Council Meeting' in prompt
        assert 'Jyoti Gondek' in prompt
        assert 'Mayor' in prompt
        assert 'Andre Chabot' in prompt
        assert 'Councillor' in prompt
        assert 'SPEAKER_00' in prompt
        assert 'Map generic speaker labels' in prompt

    def test_construct_prompt_without_speakers(self):
        """Test prompt construction without speakers list."""
        prompt = gemini_service._construct_prompt(
            SAMPLE_PYANNOTE_JSON,
            [],
            'Council Meeting'
        )

        assert 'Council Meeting' in prompt
        assert 'No speaker list available' in prompt


@pytest.mark.unit
class TestExtractJsonFromResponse:
    """Test _extract_json_from_response helper function."""

    def test_extract_plain_json(self):
        """Test extracting plain JSON."""
        response = json.dumps(SAMPLE_GEMINI_RESPONSE)
        result = gemini_service._extract_json_from_response(response)

        assert result == SAMPLE_GEMINI_RESPONSE

    def test_extract_json_from_markdown_code_block(self):
        """Test extracting JSON from markdown code block."""
        response = f"```json\n{json.dumps(SAMPLE_GEMINI_RESPONSE)}\n```"
        result = gemini_service._extract_json_from_response(response)

        assert result == SAMPLE_GEMINI_RESPONSE

    def test_extract_json_from_code_block_without_language(self):
        """Test extracting JSON from code block without language specifier."""
        response = f"```\n{json.dumps(SAMPLE_GEMINI_RESPONSE)}\n```"
        result = gemini_service._extract_json_from_response(response)

        assert result == SAMPLE_GEMINI_RESPONSE

    def test_extract_json_with_surrounding_text(self):
        """Test extracting JSON when surrounded by explanatory text."""
        response = f"Here is the refined diarization:\n{json.dumps(SAMPLE_GEMINI_RESPONSE)}\nHope this helps!"
        result = gemini_service._extract_json_from_response(response)

        assert result == SAMPLE_GEMINI_RESPONSE

    def test_extract_json_invalid(self):
        """Test that invalid JSON returns None."""
        response = "This is not JSON at all"
        result = gemini_service._extract_json_from_response(response)

        assert result is None

    def test_extract_json_empty_string(self):
        """Test that empty string returns None."""
        result = gemini_service._extract_json_from_response("")

        assert result is None


@pytest.mark.unit
class TestCountUniqueSpeakers:
    """Test _count_unique_speakers helper function."""

    def test_count_unique_speakers_from_segments(self):
        """Test counting unique speakers from segments."""
        speakers = gemini_service._count_unique_speakers(SAMPLE_PYANNOTE_JSON)

        assert len(speakers) == 2
        assert 'SPEAKER_00' in speakers
        assert 'SPEAKER_01' in speakers

    def test_count_unique_speakers_from_diarization_key(self):
        """Test counting when data is under 'diarization' key."""
        diarization = {
            'diarization': [
                {'speaker': 'SPEAKER_00'},
                {'speaker': 'SPEAKER_01'},
                {'speaker': 'SPEAKER_00'}
            ]
        }

        speakers = gemini_service._count_unique_speakers(diarization)

        assert len(speakers) == 2

    def test_count_unique_speakers_empty(self):
        """Test counting with no segments."""
        speakers = gemini_service._count_unique_speakers({'segments': []})

        assert len(speakers) == 0
