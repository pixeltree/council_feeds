"""Unit tests for agenda parser."""

import pytest
from unittest.mock import Mock, patch
import requests

import agenda_parser


# Sample HTML fixtures
SAMPLE_COUNCIL_HTML = """
<html>
<body>
    <h1>Council Meeting - January 27, 2026</h1>
    <div class="attendance">
        <h2>In Attendance:</h2>
        <ul>
            <li>Mayor Jyoti Gondek</li>
            <li>Councillor Andre Chabot</li>
            <li>Councillor Sonya Sharp</li>
            <li>Councillor Gian-Carlo Carra</li>
        </ul>
    </div>
    <div class="agenda">
        <h2>Items:</h2>
        <p>Presenter: John Smith from Planning Department</p>
        <p>Presentation by Sarah Johnson on Infrastructure</p>
    </div>
</body>
</html>
"""

SAMPLE_PUBLIC_HEARING_HTML = """
<html>
<body>
    <h1>Public Hearing - February 10, 2026</h1>
    <div class="speakers">
        <h2>Delegations:</h2>
        <p>Delegation: Michael Brown</p>
        <p>Speaker: Amanda Lee</p>
        <p>Delegation: Robert Wilson</p>
    </div>
</body>
</html>
"""

MALFORMED_HTML = """
<html><body><h1>Meeting</h1><p>Invalid data &nbsp;
"""

EMPTY_HTML = """
<html><body><h1>Meeting</h1></body></html>
"""


@pytest.mark.unit
class TestAgendaParser:
    """Test agenda parser functions."""

    @patch('requests.get')
    def test_extract_speakers_from_valid_html(self, mock_get):
        """Test extracting speakers from valid council meeting HTML."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_COUNCIL_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Should find mayor, councillors, and presenters
        assert len(speakers) >= 4
        speaker_names = [s['name'] for s in speakers]

        # Check that we found some expected names
        assert any('Gondek' in name for name in speaker_names)
        assert any('Chabot' in name for name in speaker_names)
        assert any('Smith' in name or 'Johnson' in name for name in speaker_names)

    @patch('requests.get')
    def test_extract_speakers_finds_council_members(self, mock_get):
        """Test that council members are found and labeled correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_COUNCIL_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Find mayor and councillors
        mayors = [s for s in speakers if s['role'] == 'Mayor']
        councillors = [s for s in speakers if s['role'] == 'Councillor']

        assert len(mayors) >= 1
        assert len(councillors) >= 3
        assert all(s['confidence'] == 'high' for s in mayors + councillors)

    @patch('requests.get')
    def test_extract_speakers_finds_presenters(self, mock_get):
        """Test that presenters are found and labeled correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_COUNCIL_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Find presenters
        presenters = [s for s in speakers if s['role'] == 'Presenter']

        assert len(presenters) >= 2
        presenter_names = [s['name'] for s in presenters]
        assert any('John Smith' in name for name in presenter_names)
        assert any('Sarah Johnson' in name for name in presenter_names)

    @patch('requests.get')
    def test_extract_speakers_finds_delegations(self, mock_get):
        """Test that delegation names are found in public hearing HTML."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PUBLIC_HEARING_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Find delegations
        delegations = [s for s in speakers if s['role'] == 'Delegation']

        assert len(delegations) >= 3
        delegation_names = [s['name'] for s in delegations]
        assert any('Michael Brown' in name for name in delegation_names)
        assert any('Amanda Lee' in name for name in delegation_names)

    @patch('requests.get')
    def test_extract_speakers_empty_list_on_invalid_html(self, mock_get):
        """Test that malformed HTML returns empty list instead of crashing."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = MALFORMED_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Should handle gracefully and return empty list or partial results
        assert isinstance(speakers, list)
        # No crash = success

    @patch('requests.get')
    def test_extract_speakers_timeout_handling(self, mock_get):
        """Test that network timeout returns empty list."""
        mock_get.side_effect = requests.Timeout("Connection timed out")

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        assert speakers == []

    @patch('requests.get')
    def test_extract_speakers_network_error_handling(self, mock_get):
        """Test that network errors return empty list."""
        mock_get.side_effect = requests.RequestException("Network error")

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        assert speakers == []

    def test_extract_speakers_none_link(self):
        """Test that None link returns empty list."""
        speakers = agenda_parser.extract_speakers(None)
        assert speakers == []

    def test_extract_speakers_empty_link(self):
        """Test that empty link returns empty list."""
        speakers = agenda_parser.extract_speakers('')
        assert speakers == []

    @patch('requests.get')
    def test_extract_speakers_deduplicates(self, mock_get):
        """Test that duplicate speakers are deduplicated."""
        html_with_duplicates = """
        <html><body>
            <p>Mayor Jyoti Gondek</p>
            <p>Presenter: Jyoti Gondek</p>
        </body></html>
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html_with_duplicates
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Should only have one entry for Jyoti Gondek (prefers higher confidence)
        gondek_entries = [s for s in speakers if 'Gondek' in s['name']]
        assert len(gondek_entries) == 1
        # Should prefer Mayor (high confidence) over Presenter (medium)
        assert gondek_entries[0]['role'] == 'Mayor'

    @patch('requests.get')
    def test_extract_speakers_case_insensitive_deduplication(self, mock_get):
        """Test that deduplication is case-insensitive."""
        html_with_case_variants = """
        <html><body>
            <p>Councillor John Smith</p>
            <p>Presenter: john smith</p>
        </body></html>
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html_with_case_variants
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        # Should only have one entry (case-insensitive)
        smith_entries = [s for s in speakers if 'smith' in s['name'].lower()]
        assert len(smith_entries) == 1

    @patch('requests.get')
    def test_extract_speakers_handles_404(self, mock_get):
        """Test that 404 status returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        assert speakers == []

    @patch('requests.get')
    def test_extract_speakers_no_speakers_warning(self, mock_get, capfd):
        """Test that warning is logged when no speakers found."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = EMPTY_HTML
        mock_get.return_value = mock_response

        speakers = agenda_parser.extract_speakers('https://example.com/agenda', use_gemini=False)

        assert speakers == []
        captured = capfd.readouterr()
        assert 'WARNING: No speakers found in agenda' in captured.out


@pytest.mark.unit
class TestExtractCouncilMembers:
    """Test _extract_council_members helper function."""

    def test_extract_councillors_from_list(self):
        """Test extracting councillors from HTML list."""
        from bs4 import BeautifulSoup

        html = """
        <ul>
            <li>Councillor John Doe</li>
            <li>Councillor Jane Smith</li>
        </ul>
        """
        soup = BeautifulSoup(html, 'html.parser')
        members = agenda_parser._extract_council_members(soup)

        assert len(members) == 2
        assert all(m['role'] == 'Councillor' for m in members)
        assert all(m['confidence'] == 'high' for m in members)

    def test_extract_mayor(self):
        """Test extracting mayor from text."""
        from bs4 import BeautifulSoup

        html = "<p>Mayor Jyoti Gondek presiding</p>"
        soup = BeautifulSoup(html, 'html.parser')
        members = agenda_parser._extract_council_members(soup)

        assert len(members) >= 1
        mayor = [m for m in members if m['role'] == 'Mayor']
        assert len(mayor) >= 1
        assert 'Gondek' in mayor[0]['name']


@pytest.mark.unit
class TestExtractPresenters:
    """Test _extract_presenters helper function."""

    def test_extract_presenters_with_colon(self):
        """Test extracting presenters with 'Presenter:' format."""
        from bs4 import BeautifulSoup

        html = "<p>Presenter: John Smith</p>"
        soup = BeautifulSoup(html, 'html.parser')
        presenters = agenda_parser._extract_presenters(soup)

        assert len(presenters) == 1
        assert presenters[0]['name'] == 'John Smith'
        assert presenters[0]['role'] == 'Presenter'
        assert presenters[0]['confidence'] == 'medium'

    def test_extract_presentation_by(self):
        """Test extracting presenters with 'Presentation by' format."""
        from bs4 import BeautifulSoup

        html = "<p>Presentation by Sarah Johnson</p>"
        soup = BeautifulSoup(html, 'html.parser')
        presenters = agenda_parser._extract_presenters(soup)

        assert len(presenters) == 1
        assert presenters[0]['name'] == 'Sarah Johnson'


@pytest.mark.unit
class TestExtractDelegations:
    """Test _extract_delegations helper function."""

    def test_extract_delegations(self):
        """Test extracting delegation names."""
        from bs4 import BeautifulSoup

        html = """
        <div>
            <p>Delegation: Michael Brown</p>
            <p>Speaker: Amanda Lee</p>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        delegations = agenda_parser._extract_delegations(soup)

        assert len(delegations) == 2
        names = [d['name'] for d in delegations]
        assert 'Michael Brown' in names
        assert 'Amanda Lee' in names
        assert all(d['confidence'] == 'medium' for d in delegations)


@pytest.mark.unit
class TestDeduplicateSpeakers:
    """Test _deduplicate_speakers helper function."""

    def test_deduplicate_exact_match(self):
        """Test deduplication with exact name match."""
        speakers = [
            {'name': 'John Smith', 'role': 'Councillor', 'confidence': 'high'},
            {'name': 'John Smith', 'role': 'Presenter', 'confidence': 'medium'}
        ]

        unique = agenda_parser._deduplicate_speakers(speakers)

        assert len(unique) == 1
        # Should prefer higher confidence
        assert unique[0]['confidence'] == 'high'

    def test_deduplicate_case_insensitive(self):
        """Test deduplication is case-insensitive."""
        speakers = [
            {'name': 'John Smith', 'role': 'Councillor', 'confidence': 'high'},
            {'name': 'john smith', 'role': 'Presenter', 'confidence': 'medium'},
            {'name': 'JOHN SMITH', 'role': 'Delegation', 'confidence': 'medium'}
        ]

        unique = agenda_parser._deduplicate_speakers(speakers)

        assert len(unique) == 1
        assert unique[0]['confidence'] == 'high'

    def test_deduplicate_no_duplicates(self):
        """Test that list without duplicates is unchanged."""
        speakers = [
            {'name': 'John Smith', 'role': 'Councillor', 'confidence': 'high'},
            {'name': 'Jane Doe', 'role': 'Councillor', 'confidence': 'high'}
        ]

        unique = agenda_parser._deduplicate_speakers(speakers)

        assert len(unique) == 2
