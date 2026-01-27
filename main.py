#!/usr/bin/env python3
import requests
import subprocess
import time
import os
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
import re
import pytz

# Import database functions
import database as db

# Calgary timezone (Council meetings are in local Calgary time)
CALGARY_TZ = pytz.timezone('America/Edmonton')

STREAM_PAGE_URL = "https://video.isilive.ca/play/calgarycc/live"
COUNCIL_CALENDAR_API = "https://data.calgary.ca/resource/23m4-i42g.json"

# Polling intervals
ACTIVE_CHECK_INTERVAL = 30  # Check every 30 seconds during meeting windows
IDLE_CHECK_INTERVAL = 1800  # Check every 30 minutes outside meeting windows
CALENDAR_REFRESH_HOURS = 24  # Refresh calendar daily

OUTPUT_DIR = "./recordings"
MAX_RETRIES = 3

# Meeting window: start checking 15 minutes before, continue up to 6 hours after scheduled time
MEETING_BUFFER_BEFORE = timedelta(minutes=15)
MEETING_BUFFER_AFTER = timedelta(hours=6)

# Common ISILive stream URL patterns
STREAM_URL_PATTERNS = [
    "https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8",
    "https://lin12.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/_definst_/calgarycc/live/playlist.m3u8",
]

def fetch_council_meetings():
    """Fetch upcoming Council Chamber meetings from Calgary Open Data API."""
    try:
        response = requests.get(COUNCIL_CALENDAR_API, timeout=15)
        response.raise_for_status()
        meetings = response.json()

        # Filter for Council meetings (held in Council Chamber)
        council_meetings = []
        for meeting in meetings:
            title = meeting.get('title', '')
            if 'Council meeting' in title:
                try:
                    # Parse the meeting date
                    date_str = meeting.get('meeting_date', '')
                    # Extract just the date/time portion (before any extra text)
                    # Example: "Tuesday, January 27, 2026, 9:30 a.m."
                    # Parse as naive datetime first
                    meeting_dt_naive = date_parser.parse(date_str, fuzzy=True)

                    # Localize to Calgary timezone (meetings are in local Calgary time)
                    # This properly handles DST transitions
                    meeting_dt = CALGARY_TZ.localize(meeting_dt_naive)

                    council_meetings.append({
                        'title': title,
                        'datetime': meeting_dt,
                        'raw_date': date_str,
                        'link': meeting.get('link', '')
                    })
                except (ValueError, TypeError) as e:
                    print(f"Warning: Could not parse date '{date_str}': {e}")
                    continue

        # Sort by datetime
        council_meetings.sort(key=lambda x: x['datetime'])

        return council_meetings

    except Exception as e:
        print(f"Error fetching council meetings: {e}")
        return []

def get_upcoming_meetings(force_refresh=False):
    """Get upcoming meetings, using database cache if available and fresh."""
    # Check if we need to refresh from API
    last_refresh = db.get_metadata('last_calendar_refresh')
    needs_refresh = force_refresh

    # Use timezone-aware current time
    now_calgary = datetime.now(CALGARY_TZ)

    if last_refresh:
        try:
            last_refresh_dt = datetime.fromisoformat(last_refresh)
            # Make timezone-aware if it isn't already
            if last_refresh_dt.tzinfo is None:
                last_refresh_dt = CALGARY_TZ.localize(last_refresh_dt)

            if (now_calgary - last_refresh_dt) >= timedelta(hours=CALENDAR_REFRESH_HOURS):
                needs_refresh = True
            else:
                print(f"Using cached meeting schedule (last updated: {last_refresh_dt.strftime('%Y-%m-%d %H:%M %Z')})")
        except (ValueError, TypeError):
            needs_refresh = True
    else:
        needs_refresh = True

    # Fetch fresh data if needed
    if needs_refresh:
        print("Fetching fresh meeting schedule from Calgary Open Data API...")
        meetings = fetch_council_meetings()

        if meetings:
            # Save to database
            saved_count = db.save_meetings(meetings)
            db.set_metadata('last_calendar_refresh', now_calgary.isoformat())
            print(f"Saved {saved_count} Council meetings to database")

    # Always return from database to ensure consistency
    return db.get_upcoming_meetings()

def is_within_meeting_window(current_time, meetings):
    """Check if current time is within any meeting window."""
    for meeting in meetings:
        start_window = meeting['datetime'] - MEETING_BUFFER_BEFORE
        end_window = meeting['datetime'] + MEETING_BUFFER_AFTER

        if start_window <= current_time <= end_window:
            return True, meeting

    return False, None

def get_next_meeting(current_time, meetings):
    """Get the next upcoming meeting after current time."""
    future_meetings = [m for m in meetings if m['datetime'] > current_time]
    return future_meetings[0] if future_meetings else None

def get_stream_url():
    """Extract the HLS stream URL using yt-dlp or try common patterns."""
    # Try using yt-dlp to extract the stream URL
    try:
        result = subprocess.run(
            ['yt-dlp', '-g', '--no-warnings', STREAM_PAGE_URL],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            print(f"yt-dlp found stream: {url}")
            return url
    except subprocess.TimeoutExpired:
        print("yt-dlp timed out")
    except FileNotFoundError:
        print("yt-dlp not found, trying manual methods...")
    except Exception as e:
        print(f"yt-dlp error: {e}")

    # Try common ISILive URL patterns
    for pattern_url in STREAM_URL_PATTERNS:
        try:
            response = requests.head(pattern_url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                print(f"Found working stream pattern: {pattern_url}")
                return pattern_url
        except:
            pass

    # Try parsing the page
    try:
        response = requests.get(STREAM_PAGE_URL, timeout=10)
        response.raise_for_status()

        # Look for m3u8 URL in the page content
        m3u8_pattern = re.compile(r'https?://[^\s"\']+\.m3u8[^\s"\']*')
        matches = m3u8_pattern.findall(response.text)

        if matches:
            return matches[0]

        # Alternative: parse for video source tags
        soup = BeautifulSoup(response.text, 'html.parser')
        video_tags = soup.find_all(['video', 'source'])
        for tag in video_tags:
            src = tag.get('src', '')
            if '.m3u8' in src:
                if src.startswith('http'):
                    return src
                elif src.startswith('//'):
                    return 'https:' + src

        return None
    except Exception as e:
        print(f"Error fetching stream URL: {e}")
        return None

def is_stream_live(stream_url):
    """Check if the stream is currently live."""
    if not stream_url:
        return False

    try:
        response = requests.head(stream_url, timeout=10, allow_redirects=True)
        return response.status_code == 200
    except:
        # Try GET request as fallback
        try:
            response = requests.get(stream_url, timeout=10, stream=True)
            return response.status_code == 200
        except:
            return False

def record_stream(stream_url, current_meeting=None):
    """Record the stream to a file using ffmpeg, tracking in database."""
    start_time = datetime.now(CALGARY_TZ)
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"council_meeting_{timestamp}.mp4")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Starting recording: {output_file}")

    # Find associated meeting in database
    meeting_id = None
    if current_meeting:
        db_meeting = db.find_meeting_by_datetime(current_meeting['datetime'])
        if db_meeting:
            meeting_id = db_meeting['id']
            print(f"Associated with meeting: {db_meeting['title']}")

    # Create recording record in database
    recording_id = db.create_recording(meeting_id, output_file, stream_url, start_time)
    db.log_stream_status(stream_url, 'live', meeting_id, 'Recording started')

    # ffmpeg command to record HLS stream
    cmd = [
        'ffmpeg',
        '-i', stream_url,
        '-c', 'copy',  # Copy codec (no re-encoding for efficiency)
        '-bsf:a', 'aac_adtstoasc',  # Fix AAC stream
        '-f', 'mp4',
        output_file
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        print(f"Recording started (PID: {process.pid})")

        # Monitor the process
        while True:
            # Check if stream is still live every 30 seconds
            time.sleep(30)

            if not is_stream_live(stream_url):
                print("Stream is no longer live. Stopping recording...")
                db.log_stream_status(stream_url, 'offline', meeting_id, 'Stream ended')
                process.terminate()
                time.sleep(5)
                if process.poll() is None:
                    process.kill()
                break

            # Check if process is still running
            if process.poll() is not None:
                print("Recording process ended")
                break

        end_time = datetime.now(CALGARY_TZ)
        print(f"Recording saved: {output_file}")

        # Update recording status in database
        db.update_recording(recording_id, end_time, 'completed')

        # Log statistics
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            duration = int((end_time - start_time).total_seconds())
            print(f"Duration: {duration}s, Size: {file_size / (1024**2):.1f} MB")

        return True

    except Exception as e:
        error_msg = str(e)
        print(f"Error during recording: {error_msg}")

        # Update recording as failed
        db.update_recording(recording_id, datetime.now(CALGARY_TZ), 'failed', error_msg)
        db.log_stream_status(stream_url, 'error', meeting_id, error_msg)

        return False

def main():
    """Main monitoring loop with smart scheduling."""
    print("=" * 70)
    print("Calgary Council Stream Recorder - Smart Scheduler Edition")
    print("=" * 70)
    print(f"Stream URL: {STREAM_PAGE_URL}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Database: {db.DB_PATH}")
    print(f"Active polling: every {ACTIVE_CHECK_INTERVAL}s (during meeting windows)")
    print(f"Idle polling: every {IDLE_CHECK_INTERVAL}s (outside meeting windows)")
    print("-" * 70)

    # Initialize database
    db.init_database()

    # Show recording statistics
    stats = db.get_recording_stats()
    if stats['total_recordings'] > 0:
        print(f"\nRecording Statistics:")
        print(f"  Total recordings: {stats['total_recordings']}")
        print(f"  Completed: {stats['completed']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Total size: {stats['total_size_gb']} GB")
        print("-" * 70)

    # Fetch initial meeting schedule
    meetings = get_upcoming_meetings()

    if meetings:
        print("\nUpcoming Council Chamber meetings:")
        for i, meeting in enumerate(meetings[:5], 1):  # Show first 5
            print(f"  {i}. {meeting['title']}")
            print(f"     {meeting['raw_date']}")
        if len(meetings) > 5:
            print(f"  ... and {len(meetings) - 5} more")
    else:
        print("\nNo upcoming meetings found. Will poll periodically.")

    print("-" * 70)

    last_calendar_refresh = datetime.now(CALGARY_TZ)
    active_mode = False

    while True:
        try:
            current_time = datetime.now(CALGARY_TZ)

            # Refresh calendar if needed
            if (current_time - last_calendar_refresh) > timedelta(hours=CALENDAR_REFRESH_HOURS):
                meetings = get_upcoming_meetings(force_refresh=True)
                last_calendar_refresh = current_time

            # Determine if we're in active monitoring mode
            in_window, current_meeting = is_within_meeting_window(current_time, meetings)

            # Log mode changes
            if in_window and not active_mode:
                print(f"\n{'='*70}")
                print(f"⚡ ACTIVE MODE: Meeting window detected!")
                print(f"   Meeting: {current_meeting['title']}")
                print(f"   Scheduled: {current_meeting['raw_date']}")
                print(f"   Polling every {ACTIVE_CHECK_INTERVAL} seconds")
                print(f"{'='*70}\n")
                active_mode = True
            elif not in_window and active_mode:
                next_meeting = get_next_meeting(current_time, meetings)
                print(f"\n{'='*70}")
                print(f"💤 IDLE MODE: Meeting window ended")
                if next_meeting:
                    time_until = next_meeting['datetime'] - current_time
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    print(f"   Next meeting in {hours}h {minutes}m: {next_meeting['title']}")
                print(f"   Polling every {IDLE_CHECK_INTERVAL} seconds")
                print(f"{'='*70}\n")
                active_mode = False

            # Check for stream
            stream_url = get_stream_url()

            if stream_url:
                if is_stream_live(stream_url):
                    mode_label = "🔴 ACTIVE" if active_mode else "IDLE"
                    print(f"[{current_time.strftime('%H:%M:%S')}] [{mode_label}] Stream is LIVE! Starting recording...")
                    record_stream(stream_url, current_meeting)
                    print(f"[{current_time.strftime('%H:%M:%S')}] Recording completed. Resuming monitoring...")
                    # Refresh meetings after recording in case schedule changed
                    meetings = get_upcoming_meetings(force_refresh=True)
                    last_calendar_refresh = current_time
                else:
                    if active_mode:  # Only log during active mode to reduce noise
                        print(f"[{current_time.strftime('%H:%M:%S')}] [🔴 ACTIVE] Stream found but not live yet...")
            else:
                if active_mode:  # Only log during active mode
                    print(f"[{current_time.strftime('%H:%M:%S')}] [🔴 ACTIVE] No stream URL found...")

            # Dynamic sleep interval
            check_interval = ACTIVE_CHECK_INTERVAL if active_mode else IDLE_CHECK_INTERVAL
            time.sleep(check_interval)

        except KeyboardInterrupt:
            print("\n\nShutting down recorder...")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {e}")
            time.sleep(ACTIVE_CHECK_INTERVAL)  # Use shorter interval on error

if __name__ == '__main__':
    main()
