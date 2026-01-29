"""Unit tests for web server module."""

import pytest
from unittest.mock import Mock, patch
import web_server
from web_server import app
from shared_state import monitoring_state


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.mark.unit
class TestWebServerMonitoring:
    """Test monitoring control API endpoints."""

    def test_start_monitoring(self, client):
        """Test starting monitoring."""
        # Set initial state
        monitoring_state.disable()

        response = client.post('/api/monitoring/start')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'started' in data['message'].lower()
        # Verify state was actually changed
        assert monitoring_state.enabled is True

    def test_stop_monitoring(self, client):
        """Test stopping monitoring."""
        # Set initial state
        monitoring_state.enable()

        response = client.post('/api/monitoring/stop')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'stopped' in data['message'].lower()
        # Verify state was actually changed
        assert monitoring_state.enabled is False

    def test_monitoring_status_enabled(self, client):
        """Test getting monitoring status when enabled."""
        monitoring_state.enable()

        response = client.get('/api/monitoring/status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['monitoring_enabled'] is True

    def test_monitoring_status_disabled(self, client):
        """Test getting monitoring status when disabled."""
        monitoring_state.disable()

        response = client.get('/api/monitoring/status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['monitoring_enabled'] is False


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


@pytest.mark.unit
class TestWebServerProcessRecording:
    """Test process recording API endpoint."""

    @patch('web_server.db.update_post_process_status')
    @patch('web_server.db.get_recording_by_id')
    @patch('web_server.os.path.exists')
    @patch('web_server.threading.Thread')
    def test_process_recording_success(self, mock_thread, mock_exists, mock_get_recording, mock_update_status, client):
        """Test successfully starting post-processing."""
        mock_get_recording.return_value = {
            'id': 1,
            'status': 'completed',
            'file_path': '/fake/path.mp4',
            'post_process_status': 'pending'
        }
        mock_exists.return_value = True

        response = client.post('/api/recordings/1/process')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'started' in data['message'].lower()
        mock_thread.assert_called_once()

    @patch('web_server.db.get_recording_by_id')
    def test_process_recording_not_found(self, mock_get_recording, client):
        """Test processing when recording doesn't exist."""
        mock_get_recording.return_value = None

        response = client.post('/api/recordings/999/process')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False

    @patch('web_server.db.get_recording_by_id')
    def test_process_recording_not_completed(self, mock_get_recording, client):
        """Test processing when recording is not completed."""
        mock_get_recording.return_value = {
            'id': 1,
            'status': 'recording',
            'file_path': '/fake/path.mp4'
        }

        response = client.post('/api/recordings/1/process')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False

    @patch('web_server.db.get_recording_by_id')
    def test_process_recording_already_processing(self, mock_get_recording, client):
        """Test processing when already being processed."""
        mock_get_recording.return_value = {
            'id': 1,
            'status': 'completed',
            'file_path': '/fake/path.mp4',
            'post_process_status': 'processing'
        }

        response = client.post('/api/recordings/1/process')

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'already being processed' in data['error'].lower()

    @patch('web_server.db.get_recording_by_id')
    @patch('web_server.os.path.exists')
    def test_process_recording_file_not_found(self, mock_exists, mock_get_recording, client):
        """Test processing when file doesn't exist."""
        mock_get_recording.return_value = {
            'id': 1,
            'status': 'completed',
            'file_path': '/fake/path.mp4',
            'post_process_status': 'pending'
        }
        mock_exists.return_value = False

        response = client.post('/api/recordings/1/process')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert 'file not found' in data['error'].lower()
