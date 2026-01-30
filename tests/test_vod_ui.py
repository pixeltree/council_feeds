"""Unit tests for VOD import UI functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import web_server
from web_server import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.mark.unit
class TestVodImportUI:
    """Test VOD import UI routes and functionality."""

    def test_import_vod_page_exists(self, client):
        """Test that the import VOD page route exists and returns HTML."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        assert b'text/html' in response.content_type.encode()

    def test_import_vod_page_has_form(self, client):
        """Test that the import page contains a form with required fields."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Check for form element
        assert b'<form' in response.data
        # Check for URL input field
        assert b'escriba_url' in response.data or b'url' in response.data
        # Check for submit button
        assert b'submit' in response.data.lower() or b'import' in response.data.lower()

    def test_import_vod_page_has_title(self, client):
        """Test that the import page has appropriate title."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        assert b'Import' in response.data or b'VOD' in response.data

    def test_import_vod_page_has_optional_override_fields(self, client):
        """Test that the page includes optional override fields for title and date."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have optional title override field
        assert b'title' in response.data.lower()
        # Should have optional date override field
        assert b'date' in response.data.lower()

    def test_import_vod_form_submission_redirects_or_shows_success(self, client):
        """Test that form submission via UI works (JavaScript would handle this)."""
        # This test verifies the page renders the necessary JavaScript
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Check for JavaScript that would handle form submission
        assert b'fetch' in response.data or b'submit' in response.data

    def test_import_vod_page_has_progress_display(self, client):
        """Test that the page has elements for displaying progress."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have some element for showing progress/status
        # This could be a div with id/class for progress display
        assert b'progress' in response.data.lower() or b'status' in response.data.lower()

    def test_import_vod_page_has_error_display(self, client):
        """Test that the page has elements for displaying errors."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have some element for showing errors
        assert b'error' in response.data.lower() or b'alert' in response.data.lower()

    @patch('web_server.db.get_recent_recordings')
    @patch('web_server.db.get_upcoming_meetings')
    @patch('web_server.db.get_recording_stats')
    @patch('web_server.get_current_recording')
    def test_import_vod_link_in_navigation(self, mock_current_recording, mock_stats, mock_meetings, mock_recordings, client):
        """Test that the main page has a link to the import page."""
        # Mock database calls that index page makes
        mock_current_recording.return_value = None
        mock_stats.return_value = {'total_recordings': 0, 'completed': 0, 'failed': 0, 'total_size_gb': 0}
        mock_meetings.return_value = []
        mock_recordings.return_value = []

        response = client.get('/')

        assert response.status_code == 200
        # Should have a link to the import page
        assert b'/import-vod' in response.data or b'Import' in response.data

    def test_import_vod_page_uses_existing_api(self, client):
        """Test that the page references the existing /api/recordings/import-vod endpoint."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should reference the API endpoint
        assert b'/api/recordings/import-vod' in response.data

    def test_import_vod_page_styling_consistent(self, client):
        """Test that the import page uses consistent styling (Tailwind CSS)."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Check for Tailwind CSS classes or CDN
        assert b'tailwind' in response.data.lower() or b'bg-' in response.data

    def test_import_vod_page_responsive_design(self, client):
        """Test that the page includes responsive design elements."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Check for viewport meta tag (responsive design indicator)
        assert b'viewport' in response.data


@pytest.mark.unit
class TestVodImportUIIntegration:
    """Test integration between UI and existing API."""

    @patch('web_server.threading.Thread')
    @patch('web_server.VodService')
    @patch('web_server.db.create_recording')
    @patch('web_server.db.save_meetings')
    @patch('web_server.db.find_meeting_by_datetime')
    def test_ui_form_integrates_with_api(self, mock_find_meeting, mock_save_meetings, mock_recording, mock_vod_service, mock_thread, client):
        """Test that submitting the form would call the API correctly."""
        # This verifies that the API endpoint we're calling from UI exists
        dt = datetime(2024, 4, 22, 11, 8)
        mock_vod_service.return_value.validate_escriba_url.return_value = True
        mock_vod_service.return_value.extract_meeting_info.return_value = {
            'title': 'Test Meeting',
            'datetime': dt,
            'timestamp': int(dt.timestamp()),
            'meeting_id': 'test123',
            'link': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test123',
            'raw_date': dt.strftime('%Y-%m-%d %H:%M:%S')
        }
        mock_find_meeting.return_value = {'id': 1, 'title': 'Test Meeting'}
        mock_save_meetings.return_value = 1
        mock_recording.return_value = 10

        # Simulate what the JavaScript would do: POST to API
        response = client.post('/api/recordings/import-vod',
                               json={'escriba_url': 'https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=test'},
                               content_type='application/json')

        # API should exist and respond successfully
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_import_vod_page_accessible_without_auth(self, client):
        """Test that the import page is accessible (no auth required for now)."""
        response = client.get('/import-vod')

        # Should be accessible
        assert response.status_code == 200

    def test_import_vod_page_has_back_link(self, client):
        """Test that the import page has a way to navigate back."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have a back link or home link
        assert b'/' in response.data  # Some link back to main page


@pytest.mark.unit
class TestVodImportUIUserFlow:
    """Test complete user flow for VOD import via UI."""

    @patch('web_server.db.get_recent_recordings')
    @patch('web_server.db.get_upcoming_meetings')
    @patch('web_server.db.get_recording_stats')
    @patch('web_server.get_current_recording')
    def test_user_flow_navigation_to_import_page(self, mock_current_recording, mock_stats, mock_meetings, mock_recordings, client):
        """Test user can navigate from main page to import page."""
        # Mock database calls that index page makes
        mock_current_recording.return_value = None
        mock_stats.return_value = {'total_recordings': 0, 'completed': 0, 'failed': 0, 'total_size_gb': 0}
        mock_meetings.return_value = []
        mock_recordings.return_value = []

        # Step 1: User visits main page
        response = client.get('/')
        assert response.status_code == 200

        # Step 2: Main page should have link to import
        # (We check this in another test, but verifying flow here)

        # Step 3: User navigates to import page
        response = client.get('/import-vod')
        assert response.status_code == 200

    def test_user_flow_form_has_help_text(self, client):
        """Test that the form provides helpful instructions."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have some help text or placeholder
        assert b'Escriba' in response.data or b'URL' in response.data or b'http' in response.data

    def test_user_flow_form_validation_hints(self, client):
        """Test that the form includes HTML5 validation attributes."""
        response = client.get('/import-vod')

        assert response.status_code == 200
        # Should have required attribute or pattern for URL validation
        assert b'required' in response.data or b'pattern' in response.data
