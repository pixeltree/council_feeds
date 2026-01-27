# Testing Documentation

## Overview

This document describes the testing infrastructure for the Calgary Council Stream Recorder project. The codebase has been refactored to improve testability and includes comprehensive unit and integration tests.

## Test Suite Statistics

- **Total Tests**: 43
- **Unit Tests**: 29
- **Integration Tests**: 14
- **Test Coverage**: Comprehensive coverage of all core modules

## Running Tests

### Run all tests
```bash
python -m pytest tests/
```

### Run with verbose output
```bash
python -m pytest tests/ -v
```

### Run specific test categories
```bash
# Run only unit tests
python -m pytest tests/ -m unit

# Run only integration tests
python -m pytest tests/ -m integration

# Run only slow tests
python -m pytest tests/ -m slow
```

### Run specific test files
```bash
python -m pytest tests/test_database.py
python -m pytest tests/test_services.py
python -m pytest tests/test_integration.py
```

### Run with coverage report
```bash
pip install pytest-cov
python -m pytest tests/ --cov=. --cov-report=html
```

## Test Structure

### Unit Tests

#### `tests/test_database.py`
Tests for database operations:
- Database initialization and schema creation
- Meeting CRUD operations
- Recording lifecycle management
- Stream status logging
- Metadata operations
- Statistics calculation

#### `tests/test_services.py`
Tests for service classes:

**CalendarService**
- Fetching meetings from API
- Handling API errors
- Caching and refresh logic

**MeetingScheduler**
- Meeting window detection
- Next meeting calculation

**StreamService**
- Stream URL detection (yt-dlp, patterns, page parsing)
- Stream availability checking
- Fallback chain handling

**RecordingService**
- Recording initiation and completion
- Error handling during recording

### Integration Tests

#### `tests/test_integration.py`
End-to-end workflow tests:
- Calendar API → Database flow
- Meeting scheduling with real data
- Stream detection fallback chain
- Complete recording lifecycle
- Full monitoring cycle simulation

## Test Fixtures

Located in `tests/conftest.py`:

- `temp_db_path`: Temporary database file for isolated tests
- `temp_db_dir`: Temporary database directory
- `temp_output_dir`: Temporary output directory for recordings
- `sample_meeting`: Single meeting fixture
- `sample_meetings`: Multiple meetings fixture
- `api_response_data`: Sample API response for calendar tests

## Refactoring Changes

### 1. Configuration Module (`config.py`)
Centralized all configuration values:
- URLs and API endpoints
- Polling intervals
- Directory paths
- Stream URL patterns
- Web server settings

### 2. Service Classes (`services.py`)

**CalendarService**
- Encapsulates calendar API interactions
- Manages meeting data fetching and caching

**MeetingScheduler**
- Handles meeting window detection
- Calculates next meeting times

**StreamService**
- Manages stream URL detection
- Checks stream availability

**RecordingService**
- Handles recording operations
- Manages ffmpeg process lifecycle

### 3. Database Improvements (`database.py`)

Added `Database` class for better testability:
- Configurable database path
- Isolated connection management
- Backward compatible with module-level functions

### 4. Main Application (`main.py`)

Refactored to use service classes:
- Cleaner separation of concerns
- Easier to test individual components
- Improved maintainability

## Mocking Strategy

Tests use comprehensive mocking to avoid external dependencies:

- **HTTP requests**: `responses` library for API mocking
- **Subprocess calls**: `unittest.mock.patch` for ffmpeg/yt-dlp
- **File system**: Pytest's `tmp_path` fixture
- **Database**: In-memory or temporary file databases
- **Time**: Mock `time.sleep` to speed up tests

## Continuous Integration

To set up CI/CD, add this workflow file:

`.github/workflows/test.yml`:
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt

    - name: Run tests
      run: |
        python -m pytest tests/ -v
```

## Best Practices

1. **Isolation**: Each test is independent and doesn't affect others
2. **Fast**: Most tests run in milliseconds
3. **Comprehensive**: Tests cover happy paths and error cases
4. **Readable**: Clear test names and documentation
5. **Maintainable**: Tests are organized by module and concern

## Adding New Tests

When adding new functionality:

1. Write tests first (TDD approach)
2. Use appropriate fixtures from `conftest.py`
3. Mock external dependencies
4. Add appropriate pytest markers (`@pytest.mark.unit`, etc.)
5. Ensure tests are isolated and repeatable

Example:
```python
@pytest.mark.unit
def test_new_feature(sample_meeting):
    """Test description."""
    # Arrange
    service = MyService()

    # Act
    result = service.do_something(sample_meeting)

    # Assert
    assert result == expected_value
```

## Troubleshooting

### Tests fail with module import errors
```bash
# Ensure you're in the project root
cd /path/to/council_feeds

# Install test dependencies
pip install -r requirements.txt
```

### Database locked errors
- Tests use temporary databases
- If issues persist, check file permissions

### Mock not working
- Ensure mock path matches the actual import in the code
- Use `patch` decorator in correct order (bottom-up)

## Future Improvements

- [ ] Add performance benchmarks
- [ ] Add API contract tests
- [ ] Increase coverage to 95%+
- [ ] Add mutation testing
- [ ] Add load/stress tests for database operations
