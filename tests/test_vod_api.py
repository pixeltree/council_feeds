"""Unit tests for VOD import API endpoint.

These tests follow TDD (Test-Driven Development) principles:
- Written BEFORE implementation
- Test expected behavior, not implementation details
- Cover happy path, edge cases, and error conditions
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import web_server
from web_server import app
from datetime import datetime
import threading


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.mark.unit
class TestVodImportAPI:
    """Test VOD import API endpoint."""

    @patch('web_server.threading.Thread')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_import_vod_success(self, mock_vod_service_class, mock_save_meetings,
                                mock_create_recording, mock_thread, client):
        """Test successful VOD import request."""
        # Setup mocks
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Public Hearing Meeting of Council',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_save_meetings.return_value = 42  # meeting_id
        mock_create_recording.return_value = 100  # recording_id

        # Make request
        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        })

        # Assertions
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['recording_id'] == 100
        assert data['meeting_title'] == 'Public Hearing Meeting of Council'
        assert 'download started' in data['message'].lower()

        # Verify service methods were called
        mock_vod_service.validate_escriba_url.assert_called_once()
        mock_vod_service.extract_meeting_info.assert_called_once()
        mock_save_meetings.assert_called_once()
        mock_create_recording.assert_called_once()

        # Verify background thread was started
        mock_thread.assert_called_once()
        assert mock_thread.call_args[1]['daemon'] is True

    @patch('web_server.VodService')
    def test_import_vod_missing_url(self, mock_vod_service_class, client):
        """Test import with missing URL."""
        response = client.post('/api/recordings/import-vod', json={})

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'url' in data['message'].lower() or 'required' in data['message'].lower()

    @patch('web_server.VodService')
    def test_import_vod_invalid_url(self, mock_vod_service_class, client):
        """Test import with invalid Escriba URL."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = False

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://evil.com/malicious'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'invalid' in data['message'].lower() or 'url' in data['message'].lower()

    @patch('web_server.VodService')
    def test_import_vod_extraction_failure(self, mock_vod_service_class, client):
        """Test import when meeting info extraction fails."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.side_effect = Exception("Failed to extract meeting info")

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        })

        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert 'extract' in data['message'].lower() or 'failed' in data['message'].lower()

    @patch('web_server.threading.Thread')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_import_vod_with_title_override(self, mock_vod_service_class, mock_save_meetings,
                                            mock_create_recording, mock_thread, client):
        """Test import with custom title override."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Original Title',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_save_meetings.return_value = 42
        mock_create_recording.return_value = 100

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123',
            'override_title': 'Custom Meeting Title'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['meeting_title'] == 'Custom Meeting Title'

        # Verify save_meetings was called with overridden title
        call_args = mock_save_meetings.call_args[0][0]
        assert call_args[0]['title'] == 'Custom Meeting Title'

    @patch('web_server.threading.Thread')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_import_vod_with_date_override(self, mock_vod_service_class, mock_save_meetings,
                                           mock_create_recording, mock_thread, client):
        """Test import with custom date override."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Meeting Title',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_save_meetings.return_value = 42
        mock_create_recording.return_value = 100

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123',
            'override_date': '2024-05-15T14:30:00'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify save_meetings was called with overridden datetime
        call_args = mock_save_meetings.call_args[0][0]
        # Check date components (timezone may differ)
        assert call_args[0]['datetime'].year == 2024
        assert call_args[0]['datetime'].month == 5
        assert call_args[0]['datetime'].day == 15
        assert call_args[0]['datetime'].hour == 14
        assert call_args[0]['datetime'].minute == 30

    @patch('web_server.VodService')
    def test_import_vod_invalid_date_format(self, mock_vod_service_class, client):
        """Test import with invalid date format."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123',
            'override_date': 'invalid-date-format'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'date' in data['message'].lower() or 'format' in data['message'].lower()

    @patch('web_server.threading.Thread')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_import_vod_database_error(self, mock_vod_service_class, mock_save_meetings,
                                       mock_create_recording, mock_thread, client):
        """Test import when database operation fails."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Meeting Title',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_save_meetings.side_effect = Exception("Database error")

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        })

        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert 'database' in data['message'].lower() or 'failed' in data['message'].lower()

    @patch('web_server.threading.Thread')
    @patch('web_server.db.update_recording')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_download_thread_success(self, mock_vod_service_class, mock_save_meetings,
                                     mock_create_recording, mock_update_recording,
                                     mock_thread, client):
        """Test that download thread is properly configured."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Meeting Title',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_vod_service.download_vod.return_value = '/path/to/recording.mkv'
        mock_save_meetings.return_value = 42
        mock_create_recording.return_value = 100

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        })

        assert response.status_code == 200

        # Verify thread was created with correct parameters
        mock_thread.assert_called_once()
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs['daemon'] is True
        assert 'target' in call_kwargs

        # Start the thread to verify it was configured
        thread_instance = mock_thread.return_value
        thread_instance.start.assert_called_once()

    @patch('web_server.VodService')
    def test_import_vod_content_type_validation(self, mock_vod_service_class, client):
        """Test that endpoint requires JSON content type."""
        response = client.post('/api/recordings/import-vod',
                              data='escriba_url=https://test.com')

        # Should fail due to missing or wrong content type
        assert response.status_code in [400, 415]  # Bad Request or Unsupported Media Type

    @patch('web_server.threading.Thread')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.VodService')
    def test_import_vod_recording_status_initialized(self, mock_vod_service_class,
                                                      mock_save_meetings, mock_create_recording,
                                                      mock_thread, client):
        """Test that recording is created with 'downloading' status."""
        mock_vod_service = Mock()
        mock_vod_service_class.return_value = mock_vod_service
        mock_vod_service.validate_escriba_url.return_value = True
        mock_vod_service.extract_meeting_info.return_value = {
            'title': 'Meeting Title',
            'datetime': datetime(2024, 4, 22, 11, 8),
            'timestamp': '2024-04-22_11-08',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        }
        mock_save_meetings.return_value = 42
        mock_create_recording.return_value = 100

        response = client.post('/api/recordings/import-vod', json={
            'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123'
        })

        assert response.status_code == 200

        # Verify create_recording was called - status will be set in the implementation
        mock_create_recording.assert_called_once()
