"""Unit tests for web server module."""

import pytest
from unittest.mock import Mock, patch
import web_server
from web_server import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.mark.unit
class TestWebServerStopRecording:
    """Test stop recording API endpoint."""

    def test_stop_recording_success(self, client):
        """Test successfully stopping a recording."""
        mock_service = Mock()
        mock_service.is_recording.return_value = True
        mock_service.stop_recording.return_value = True
        web_server.set_recording_service(mock_service)
        
        response = client.post('/api/stop-recording')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_stop_recording_no_recording_in_progress(self, client):
        """Test stopping when no recording is active."""
        mock_service = Mock()
        mock_service.is_recording.return_value = False
        web_server.set_recording_service(mock_service)
        
        response = client.post('/api/stop-recording')
        
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False

    def test_stop_recording_service_not_available(self, client):
        """Test stopping when recording service is not set."""
        web_server.set_recording_service(None)
        
        response = client.post('/api/stop-recording')
        
        assert response.status_code == 500
