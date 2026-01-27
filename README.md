# Calgary Council Stream Recorder

Automatically monitors and records Calgary City Council webcasts when they go live, using smart scheduling based on the official meeting calendar.

## Features

- **Smart Scheduling**: Uses Calgary Open Data API to fetch official meeting schedules
- **Dynamic Polling**: Active monitoring during meeting windows, idle polling otherwise
- **SQLite Database**: Tracks meetings, recordings, and stream status history
- **Automatic Recording**: Starts recording when stream goes live, stops when it ends
- **Meeting Association**: Links recordings to specific council meetings
- **Statistics**: Track recording history, duration, and file sizes
- **Docker Ready**: Persistent storage for database and recordings
- Runs continuously to catch all Council Chamber meetings

## Requirements

### Docker (Recommended)
- Docker
- Docker Compose

### Native
- Python 3.10+
- ffmpeg
- pip packages: requests, beautifulsoup4, python-dateutil, yt-dlp

## Installation & Usage

### Using Docker (Recommended)

1. Build and start the container:
```bash
docker-compose up --build -d
```

2. View logs:
```bash
docker-compose logs -f
```

3. Stop the recorder:
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

## Configuration

### Polling Intervals
The app uses dynamic polling based on meeting schedules:

```python
ACTIVE_CHECK_INTERVAL = 30    # 30 seconds during meeting windows
IDLE_CHECK_INTERVAL = 1800    # 30 minutes outside meeting windows
```

Meeting windows are defined as 5 minutes before to 6 hours after scheduled meeting time.

### Scheduled Tasks
The application includes a built-in scheduler that runs in a background thread:

- **Midnight Calendar Refresh**: Automatically refreshes the meeting calendar at 00:00 (midnight) Calgary time every day
- This ensures the database always has the latest meeting schedule
- No cron daemon required - pure Python scheduling

### Storage Locations
Recordings and database are stored separately:

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
The app monitors the Calgary Council Chamber stream. The primary stream URL is:
```
https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8
```

If the stream URL changes, update the `STREAM_URL_PATTERNS` list in `main.py`:

```python
STREAM_URL_PATTERNS = [
    "https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8",
    "https://lin12.isilive.ca/live/calgarycc/live/playlist.m3u8",
    # Add additional fallback URLs here
]
```

## Output Format

Recordings are saved as MP4 files with timestamps:
```
council_meeting_YYYYMMDD_HHMMSS.mp4
```

Example: `council_meeting_20260127_143022.mp4`

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

## Troubleshooting

### Stream not detected
If you see "No stream URL found" in the logs:
1. Open https://www.calgary.ca/council/council-and-committee-webcasts.html
2. Open browser Developer Tools (F12) → Network tab
3. Look for `.m3u8` files
4. Update the `STREAM_URL_PATTERNS` in `main.py` with the correct URL

### Recording stops immediately
The stream URL may have changed. Follow the troubleshooting steps above.

### Permission errors (Docker)
Ensure the `./recordings` directory has proper permissions:
```bash
chmod 755 ./recordings
```

## Data Sources

- **Meeting Calendar**: [Calgary Open Data - Council Calendar](https://data.calgary.ca/Government/Council-Calendar/23m4-i42g)
- **Council Webcasts**: https://www.calgary.ca/council/council-and-committee-webcasts.html
- **Stream Player**: https://video.isilive.ca/play/calgarycc/live
- **Stream Provider**: ISILive

## Portability

The SQLite database and recordings are stored in mounted volumes, making the data:

- ✅ **Portable**: Copy `./data/` and `./recordings/` to migrate
- ✅ **Backupable**: Standard file backup tools work perfectly
- ✅ **Version controllable**: Can commit sample database for testing
- ✅ **Docker-friendly**: Persists across container restarts/rebuilds
- ✅ **Cross-platform**: Works identically on any Docker host

## License

This tool is for personal use to record public council meetings.
