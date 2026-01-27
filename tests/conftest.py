"""Pytest configuration and shared fixtures."""

import pytest
import tempfile
import os
from datetime import datetime
from config import CALGARY_TZ


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database path for testing."""
    db_path = tmp_path / "test_council_feeds.db"
    return str(db_path)


@pytest.fixture
def temp_db_dir(tmp_path):
    """Provide a temporary database directory for testing."""
    return str(tmp_path)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Provide a temporary output directory for recordings."""
    output_dir = tmp_path / "recordings"
    output_dir.mkdir()
    return str(output_dir)


@pytest.fixture
def sample_meeting():
    """Provide a sample meeting dictionary for testing."""
    return {
        'title': 'Council meeting',
        'datetime': CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30)),
        'raw_date': 'Monday, January 27, 2026, 9:30 a.m.',
        'link': 'https://example.com/meeting'
    }


@pytest.fixture
def sample_meetings():
    """Provide a list of sample meetings for testing."""
    return [
        {
            'title': 'Council meeting - First',
            'datetime': CALGARY_TZ.localize(datetime(2026, 1, 27, 9, 30)),
            'raw_date': 'Monday, January 27, 2026, 9:30 a.m.',
            'link': 'https://example.com/meeting1'
        },
        {
            'title': 'Council meeting - Second',
            'datetime': CALGARY_TZ.localize(datetime(2026, 2, 10, 14, 0)),
            'raw_date': 'Tuesday, February 10, 2026, 2:00 p.m.',
            'link': 'https://example.com/meeting2'
        },
        {
            'title': 'Council meeting - Third',
            'datetime': CALGARY_TZ.localize(datetime(2026, 3, 15, 10, 0)),
            'raw_date': 'Sunday, March 15, 2026, 10:00 a.m.',
            'link': 'https://example.com/meeting3'
        }
    ]


@pytest.fixture
def api_response_data():
    """Provide sample API response data for calendar tests."""
    return [
        {
            'title': 'Council meeting',
            'meeting_date': 'Monday, January 27, 2026, 9:30 a.m.',
            'link': 'https://example.com/meeting'
        },
        {
            'title': 'Council meeting - Special Session',
            'meeting_date': 'Tuesday, February 10, 2026, 2:00 p.m.',
            'link': 'https://example.com/meeting2'
        },
        {
            'title': 'Committee meeting',  # Should be filtered out
            'meeting_date': 'Wednesday, February 11, 2026, 10:00 a.m.',
            'link': 'https://example.com/committee'
        }
    ]
