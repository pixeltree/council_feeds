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
class TestWebServerLogsAPI:
    """Test logs and status API endpoints."""

    @patch('web_server.db.get_recording_by_id')
    def test_get_recording_success(self, mock_get_recording, client):
        """Test getting recording details."""
        mock_recording = {
            'id': 1,
            'status': 'completed',
            'post_process_status': 'completed'
        }
        mock_get_recording.return_value = mock_recording

        response = client.get('/api/recordings/1')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['recording'] == mock_recording

    @patch('web_server.db.get_recording_by_id')
    def test_get_recording_not_found(self, mock_get_recording, client):
        """Test getting non-existent recording."""
        mock_get_recording.return_value = None

        response = client.get('/api/recordings/1')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False

    @patch('web_server.db.get_recording_logs')
    @patch('web_server.db.get_recording_by_id')
    def test_get_recording_logs_success(self, mock_get_recording, mock_get_logs, client):
        """Test getting recording logs."""
        mock_get_recording.return_value = {'id': 1}
        mock_get_logs.return_value = [
            {'id': 1, 'message': 'Starting', 'level': 'info'},
            {'id': 2, 'message': 'Processing', 'level': 'info'},
            {'id': 3, 'message': 'Complete', 'level': 'info'}
        ]

        response = client.get('/api/recordings/1/logs')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert len(data['logs']) == 3

    @patch('web_server.db.get_recording_logs')
    @patch('web_server.db.get_recording_by_id')
    def test_get_recording_logs_since(self, mock_get_recording, mock_get_logs, client):
        """Test getting logs since a specific ID."""
        mock_get_recording.return_value = {'id': 1}
        mock_get_logs.return_value = [
            {'id': 1, 'message': 'Starting', 'level': 'info'},
            {'id': 2, 'message': 'Processing', 'level': 'info'},
            {'id': 3, 'message': 'Complete', 'level': 'info'}
        ]

        response = client.get('/api/recordings/1/logs?since=1')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        # Should only return logs with id > 1
        assert len(data['logs']) == 2
        assert all(log['id'] > 1 for log in data['logs'])

    @patch('web_server.db.get_recording_by_id')
    def test_get_recording_logs_not_found(self, mock_get_recording, client):
        """Test getting logs for non-existent recording."""
        mock_get_recording.return_value = None

        response = client.get('/api/recordings/1/logs')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
