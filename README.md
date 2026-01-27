# Calgary Council Stream Recorder

[![Tests](https://github.com/pixeltree/council_feeds/actions/workflows/test.yml/badge.svg)](https://github.com/pixeltree/council_feeds/actions/workflows/test.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Automatically monitors and records Calgary City Council webcasts when they go live, using smart scheduling based on the official meeting calendar.

## Quick Start

### Development & Testing

```bash
# Clone and install dependencies
git clone <repository>
cd council_feeds
pip install -r requirements.txt

# Run tests (recommended before making changes)
python -m pytest tests/ -v

# Run the application
python main.py

# View web dashboard at http://localhost:5000
```

### Production with Docker

```bash
# Build and start
docker-compose up --build -d

# View dashboard at http://localhost:5000
# View logs
docker-compose logs -f
```

## Testing

The project includes **43 comprehensive tests** covering all core functionality.

### Run Tests Locally

```bash
# Install dependencies (includes test packages)
pip install -r requirements.txt

# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=. --cov-report=html

# Run specific test types
python -m pytest tests/ -m unit           # Unit tests only
python -m pytest tests/ -m integration    # Integration tests only
python -m pytest tests/ -m slow           # Slow tests only
```

### Test Organization

- `tests/test_database.py` - Database operations (14 tests)
- `tests/test_services.py` - Service classes (17 tests)
- `tests/test_integration.py` - End-to-end workflows (12 tests)

### Continuous Integration

Tests run automatically via GitHub Actions on:
- Every push to `main` or `feature/*` branches
- Every pull request to `main`
- Test matrix: Python 3.9, 3.10, 3.11, 3.12

**See [TESTING.md](TESTING.md) for detailed testing documentation.**

---

## Features

- **Web Dashboard**: Real-time monitoring interface showing current status, statistics, and upcoming meetings
- **Smart Scheduling**: Uses Calgary Open Data API to fetch official meeting schedules
- **Dynamic Polling**: Active monitoring during meeting windows, idle polling otherwise
- **SQLite Database**: Tracks meetings, recordings, and stream status history
- **Automatic Recording**: Starts recording when stream goes live, stops when it ends
- **Meeting Association**: Links recordings to specific council meetings
- **Statistics**: Track recording history, duration, and file sizes
- **Docker Ready**: Persistent storage for database and recordings
- **Comprehensive Tests**: 43 tests ensuring reliability

## Requirements

### Docker (Recommended)
- Docker
- Docker Compose

### Native
- Python 3.9+
- ffmpeg
- pip packages (see requirements.txt)

## Installation & Usage

### Using Docker (Recommended)

1. Build and start the container:
```bash
docker-compose up --build -d
```

2. View the web dashboard:
```
http://localhost:5000
```

The dashboard shows:
- Current recording status (live or monitoring)
- Recording statistics (total recordings, size, etc.)
- Upcoming council meetings
- Recent recordings with duration and file size

3. View logs:
```bash
docker-compose logs -f
```

4. Stop the recorder:
```bash
docker-compose down
```

### Running Natively

1. Install dependencies:
```bash
pip install -r requirements.txt
pip install yt-dlp
```

2. Install ffmpeg (if not already installed):
   - macOS: `brew install ffmpeg`
   - Ubuntu/Debian: `sudo apt-get install ffmpeg`
   - Windows: Download from https://ffmpeg.org/

3. Run the script:
```bash
python3 main.py
```

4. View the web dashboard:
```
http://localhost:5000
```

## Configuration

All configuration is centralized in `config.py`. Key settings:

### Polling Intervals
```python
ACTIVE_CHECK_INTERVAL = 30    # 30 seconds during meeting windows
IDLE_CHECK_INTERVAL = 1800    # 30 minutes outside meeting windows
```

Meeting windows: 5 minutes before to 6 hours after scheduled meeting time.

### Storage Locations
```python
OUTPUT_DIR = "./recordings"   # Video files
DB_DIR = "./data"            # SQLite database and cache
```

For Docker, both directories are mounted as volumes in `docker-compose.yml`:
```yaml
volumes:
  - ./recordings:/app/recordings
  - ./data:/app/data
```

### Stream URLs
The app monitors the Calgary Council Chamber stream. If the stream URL changes, update `STREAM_URL_PATTERNS` in `config.py`.

### Environment Variables
Override defaults using environment variables:
- `OUTPUT_DIR` - Recording output directory
- `DB_DIR` - Database directory
- `WEB_HOST` - Web server host (default: 0.0.0.0)
- `WEB_PORT` - Web server port (default: 5000)

## Architecture

The codebase is organized for maintainability and testability:

```
├── config.py           # Configuration management
├── services.py         # Business logic services
│   ├── CalendarService      # API interactions
│   ├── MeetingScheduler     # Meeting window logic
│   ├── StreamService        # Stream detection
│   └── RecordingService     # Recording management
├── database.py         # Database operations
├── main.py            # Application entry point
├── web_server.py      # Flask dashboard
└── tests/             # Comprehensive test suite
    ├── test_database.py
    ├── test_services.py
    └── test_integration.py
```

## How It Works

1. **Initialization**: Starts scheduler thread for automated tasks
2. **Calendar Sync**: Fetches upcoming Council meetings from Calgary Open Data API
3. **Database Storage**: Stores meeting schedule in SQLite database
4. **Scheduled Refresh**: Automatically refreshes calendar at midnight (00:00) Calgary time
5. **Smart Scheduling**:
   - **Active Mode**: During meeting windows (5 min before → 6 hours after)
     - Polls every 30 seconds for stream availability
   - **Idle Mode**: Outside meeting windows
     - Polls every 30 minutes to catch any unscheduled streams
6. **Stream Detection**: When a live stream is found, recording starts immediately
7. **Recording**: Uses ffmpeg to capture the HLS stream with no re-encoding (codec copy)
8. **Database Tracking**: Links recording to specific meeting, tracks duration and file size
9. **Stream Monitoring**: Checks every 30 seconds if stream is still live during recording
10. **Completion**: When stream ends, updates database and returns to monitoring mode

## Database Schema

The SQLite database (`./data/council_feeds.db`) contains:

- **meetings**: All Council Chamber meetings from the API
- **recordings**: Recording history with file paths, durations, and status
- **stream_status_log**: Stream availability timeline
- **metadata**: App state (last calendar refresh, etc.)

Query the database directly:
```bash
sqlite3 ./data/council_feeds.db "SELECT * FROM recordings ORDER BY start_time DESC LIMIT 10"
```

## Output Format

Recordings are saved as MP4 files with timestamps:
```
council_meeting_YYYYMMDD_HHMMSS.mp4
```

Example: `council_meeting_20260127_143022.mp4`

## Troubleshooting

### Stream not detected
If you see "No stream URL found" in the logs:
1. Open https://www.calgary.ca/council/council-and-committee-webcasts.html
2. Open browser Developer Tools (F12) → Network tab
3. Look for `.m3u8` files
4. Update the `STREAM_URL_PATTERNS` in `config.py` with the correct URL

### Recording stops immediately
The stream URL may have changed. Follow the troubleshooting steps above.

### Permission errors (Docker)
Ensure the `./recordings` directory has proper permissions:
```bash
chmod 755 ./recordings
```

### Tests failing
```bash
# Ensure you have all dependencies
pip install -r requirements.txt

# Check Python version (3.9+ required)
python --version

# Run tests with verbose output
python -m pytest tests/ -v --tb=short
```

## Data Sources

- **Meeting Calendar**: [Calgary Open Data - Council Calendar](https://data.calgary.ca/Government/Council-Calendar/23m4-i42g)
- **Council Webcasts**: https://www.calgary.ca/council/council-and-committee-webcasts.html
- **Stream Player**: https://video.isilive.ca/play/calgarycc/live
- **Stream Provider**: ISILive

## Contributing

1. Create a feature branch
2. Make your changes
3. **Run tests**: `python -m pytest tests/ -v`
4. Ensure all tests pass
5. Submit a pull request

The CI pipeline will automatically run tests on your PR.

## Portability

The SQLite database and recordings are stored in mounted volumes, making the data:

- ✅ **Portable**: Copy `./data/` and `./recordings/` to migrate
- ✅ **Backupable**: Standard file backup tools work perfectly
- ✅ **Version controllable**: Can commit sample database for testing
- ✅ **Docker-friendly**: Persists across container restarts/rebuilds
- ✅ **Cross-platform**: Works identically on any Docker host

## License

This tool is for personal use to record public council meetings.
