"""Unit tests for agenda parser (Gemini AI extraction)."""

import pytest
from unittest.mock import Mock, patch
import requests
import json

import agenda_parser


# Sample HTML for testing basic functionality
SAMPLE_HTML = """
<html>
<body>
    <h1>Council Meeting - January 27, 2026</h1>
    <div class="attendance">
        <h2>Members Present:</h2>
        <p>Mayor Jyoti Gondek, Councillor Andre Chabot</p>
    </div>
</body>
</html>
"""


@pytest.mark.unit
class TestAgendaParserGemini:
    """Test Gemini-based agenda parser functions."""

    @patch("config.GEMINI_API_KEY", "test-api-key")
    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_with_gemini_success(self, mock_get, mock_post):
        """Test successful speaker extraction using Gemini."""
        # Mock HTML fetch
        mock_html_response = Mock()
        mock_html_response.status_code = 200
        mock_html_response.text = SAMPLE_HTML
        mock_get.return_value = mock_html_response

        # Mock Gemini API response
        mock_gemini_response = Mock()
        mock_gemini_response.status_code = 200
        mock_gemini_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    [
                                        {
                                            "name": "Jyoti Gondek",
                                            "role": "Mayor",
                                            "confidence": "high",
                                        },
                                        {
                                            "name": "Andre Chabot",
                                            "role": "Councillor",
                                            "confidence": "high",
                                        },
                                    ]
                                )
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_gemini_response

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert len(speakers) == 2
        assert speakers[0]["name"] == "Jyoti Gondek"
        assert speakers[0]["role"] == "Mayor"
        assert speakers[1]["name"] == "Andre Chabot"
        assert speakers[1]["role"] == "Councillor"

    @patch("requests.get")
    def test_extract_speakers_timeout_handling(self, mock_get):
        """Test that network timeout returns empty list."""
        mock_get.side_effect = requests.Timeout("Connection timed out")

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert speakers == []

    @patch("requests.get")
    def test_extract_speakers_network_error_handling(self, mock_get):
        """Test that network errors return empty list."""
        mock_get.side_effect = requests.RequestException("Network error")

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert speakers == []

    def test_extract_speakers_none_link(self):
        """Test that None link returns empty list."""
        speakers = agenda_parser.extract_speakers(None)
        assert speakers == []

    def test_extract_speakers_empty_link(self):
        """Test that empty link returns empty list."""
        speakers = agenda_parser.extract_speakers("")
        assert speakers == []

    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_handles_404(self, mock_get, mock_post):
        """Test that 404 status returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert speakers == []

    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_gemini_returns_empty(self, mock_get, mock_post):
        """Test that empty Gemini response returns empty list."""
        # Mock HTML fetch
        mock_html_response = Mock()
        mock_html_response.status_code = 200
        mock_html_response.text = SAMPLE_HTML
        mock_get.return_value = mock_html_response

        # Mock Gemini API response with empty array
        mock_gemini_response = Mock()
        mock_gemini_response.status_code = 200
        mock_gemini_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "[]"}]}}]
        }
        mock_post.return_value = mock_gemini_response

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert speakers == []

    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_gemini_api_error(self, mock_get, mock_post):
        """Test that Gemini API errors are handled gracefully."""
        # Mock HTML fetch
        mock_html_response = Mock()
        mock_html_response.status_code = 200
        mock_html_response.text = SAMPLE_HTML
        mock_get.return_value = mock_html_response

        # Mock Gemini API error
        mock_post.side_effect = requests.RequestException("API error")

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert speakers == []

    @patch("config.GEMINI_API_KEY", "test-api-key")
    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_removes_markdown_code_blocks(self, mock_get, mock_post):
        """Test that markdown code blocks are properly removed from Gemini response."""
        # Mock HTML fetch
        mock_html_response = Mock()
        mock_html_response.status_code = 200
        mock_html_response.text = SAMPLE_HTML
        mock_get.return_value = mock_html_response

        # Mock Gemini API response with markdown code blocks
        mock_gemini_response = Mock()
        mock_gemini_response.status_code = 200
        mock_gemini_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '```json\n[{"name": "Test User", "role": "Councillor", "confidence": "high"}]\n```'
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_gemini_response

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert len(speakers) == 1
        assert speakers[0]["name"] == "Test User"

    @patch("config.GEMINI_API_KEY", "test-api-key")
    @patch("agenda_parser.requests.post")
    @patch("requests.get")
    def test_extract_speakers_adds_default_confidence(self, mock_get, mock_post):
        """Test that default confidence is added if missing."""
        # Mock HTML fetch
        mock_html_response = Mock()
        mock_html_response.status_code = 200
        mock_html_response.text = SAMPLE_HTML
        mock_get.return_value = mock_html_response

        # Mock Gemini response without confidence field
        mock_gemini_response = Mock()
        mock_gemini_response.status_code = 200
        mock_gemini_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    [{"name": "Test User", "role": "Councillor"}]
                                )
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_gemini_response

        speakers = agenda_parser.extract_speakers("https://example.com/agenda")

        assert len(speakers) == 1
        assert speakers[0]["confidence"] == "high"
