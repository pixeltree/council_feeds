# Calgary Council Stream Recorder

Automatically monitors and records Calgary City Council webcasts when they go live.

## Features

- Monitors the Calgary Council livestream every 10 seconds
- Automatically starts recording when a stream is detected
- Stops recording when the stream ends
- Saves recordings with timestamps
- Runs continuously to catch all future streams
- Works in Docker container or natively

## Requirements

### Docker (Recommended)
- Docker
- Docker Compose

### Native
- Python 3.10+
- ffmpeg
- pip packages: requests, beautifulsoup4, yt-dlp

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

### Check Interval
The app checks for live streams every 10 seconds by default. To change this, edit `main.py`:

```python
CHECK_INTERVAL = 10  # Check every 10 seconds
```

- Lower values (e.g., 5) = faster detection but more server requests
- Higher values (e.g., 60) = slower detection but fewer server requests

### Output Directory
Recordings are saved to `./recordings/` by default. To change this, edit `main.py`:

```python
OUTPUT_DIR = "./recordings"
```

For Docker, the directory is mapped in `docker-compose.yml`:
```yaml
volumes:
  - ./recordings:/recordings
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

1. **Monitoring**: Checks the stream URL every 10 seconds
2. **Detection**: When a live stream is found, recording starts immediately
3. **Recording**: Uses ffmpeg to capture the HLS stream with no re-encoding (codec copy)
4. **Monitoring During Recording**: Checks every 30 seconds if stream is still live
5. **Completion**: When stream ends, stops recording and saves the file
6. **Resume**: Returns to monitoring mode for the next stream

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

## Source Information

- Council webcasts page: https://www.calgary.ca/council/council-and-committee-webcasts.html
- Stream player: https://video.isilive.ca/play/calgarycc/live
- Stream provider: ISILive

## License

This tool is for personal use to record public council meetings.
