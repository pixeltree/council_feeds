#!/usr/bin/env python3
"""
Service classes for Calgary Council Stream Recorder.
Separates business logic from main application flow for better testability.
"""

import requests
import subprocess
import re
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple

import database as db
from config import (
    CALGARY_TZ,
    COUNCIL_CALENDAR_API,
    STREAM_PAGE_URL,
    STREAM_URL_PATTERNS,
    MEETING_BUFFER_BEFORE,
    MEETING_BUFFER_AFTER,
    YTDLP_COMMAND,
    OUTPUT_DIR,
    FFMPEG_COMMAND,
    ENABLE_POST_PROCESSING,
    POST_PROCESS_SILENCE_THRESHOLD_DB,
    POST_PROCESS_MIN_SILENCE_DURATION
)
import os


class CalendarService:
    """Service for fetching and managing council meeting calendar."""

    def __init__(self, api_url: str = COUNCIL_CALENDAR_API, timezone=CALGARY_TZ):
        self.api_url = api_url
        self.timezone = timezone

    def fetch_council_meetings(self) -> List[Dict]:
        """Fetch upcoming Council Chamber meetings from Calgary Open Data API."""
        try:
            response = requests.get(self.api_url, timeout=15)
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
                        # Parse as naive datetime first
                        meeting_dt_naive = date_parser.parse(date_str, fuzzy=True)

                        # Localize to Calgary timezone
                        meeting_dt = self.timezone.localize(meeting_dt_naive)

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

    def get_upcoming_meetings(self, force_refresh: bool = False) -> List[Dict]:
        """Get upcoming meetings, using database cache if available and fresh."""
        # Check if we need to refresh from API
        last_refresh = db.get_metadata('last_calendar_refresh')
        needs_refresh = force_refresh

        # Use timezone-aware current time
        now = datetime.now(self.timezone)

        if last_refresh and not needs_refresh:
            try:
                last_refresh_dt = datetime.fromisoformat(last_refresh)
                # Make timezone-aware if it isn't already
                if last_refresh_dt.tzinfo is None:
                    last_refresh_dt = self.timezone.localize(last_refresh_dt)

                print(f"Using cached meeting schedule (last updated: {last_refresh_dt.strftime('%Y-%m-%d %H:%M %Z')})")
            except (ValueError, TypeError):
                needs_refresh = True
        else:
            needs_refresh = True

        # Fetch fresh data if needed
        if needs_refresh:
            print("Fetching fresh meeting schedule from Calgary Open Data API...")
            meetings = self.fetch_council_meetings()

            if meetings:
                # Save to database
                saved_count = db.save_meetings(meetings)
                db.set_metadata('last_calendar_refresh', now.isoformat())
                print(f"Saved {saved_count} Council meetings to database")

        # Always return from database to ensure consistency
        return db.get_upcoming_meetings()


class MeetingScheduler:
    """Service for determining meeting windows and scheduling logic."""

    def __init__(
        self,
        buffer_before: timedelta = MEETING_BUFFER_BEFORE,
        buffer_after: timedelta = MEETING_BUFFER_AFTER,
        timezone=CALGARY_TZ
    ):
        self.buffer_before = buffer_before
        self.buffer_after = buffer_after
        self.timezone = timezone

    def is_within_meeting_window(
        self,
        current_time: datetime,
        meetings: List[Dict]
    ) -> Tuple[bool, Optional[Dict]]:
        """Check if current time is within any meeting window."""
        for meeting in meetings:
            start_window = meeting['datetime'] - self.buffer_before
            end_window = meeting['datetime'] + self.buffer_after

            if start_window <= current_time <= end_window:
                return True, meeting

        return False, None

    def get_next_meeting(
        self,
        current_time: datetime,
        meetings: List[Dict]
    ) -> Optional[Dict]:
        """Get the next upcoming meeting after current time."""
        future_meetings = [m for m in meetings if m['datetime'] > current_time]
        return future_meetings[0] if future_meetings else None


class StreamService:
    """Service for detecting and checking stream availability."""

    def __init__(
        self,
        stream_page_url: str = STREAM_PAGE_URL,
        stream_url_patterns: List[str] = None,
        ytdlp_command: str = YTDLP_COMMAND
    ):
        self.stream_page_url = stream_page_url
        self.stream_url_patterns = stream_url_patterns or STREAM_URL_PATTERNS
        self.ytdlp_command = ytdlp_command

    def get_stream_url(self) -> Optional[str]:
        """Extract the HLS stream URL using yt-dlp or try common patterns."""
        # Try using yt-dlp to extract the stream URL
        try:
            result = subprocess.run(
                [self.ytdlp_command, '-g', '--no-warnings', self.stream_page_url],
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
        for pattern_url in self.stream_url_patterns:
            try:
                response = requests.head(pattern_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    print(f"Found working stream pattern: {pattern_url}")
                    return pattern_url
            except:
                pass

        # Try parsing the page
        try:
            response = requests.get(self.stream_page_url, timeout=10)
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

    def is_stream_live(self, stream_url: str) -> bool:
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


class RecordingService:
    """Service for recording streams using ffmpeg."""

    def __init__(
        self,
        output_dir: str = OUTPUT_DIR,
        ffmpeg_command: str = FFMPEG_COMMAND,
        timezone=CALGARY_TZ,
        stream_service: Optional[StreamService] = None
    ):
        self.output_dir = output_dir
        self.ffmpeg_command = ffmpeg_command
        self.timezone = timezone
        self.stream_service = stream_service or StreamService()

    def record_stream(
        self,
        stream_url: str,
        current_meeting: Optional[Dict] = None
    ) -> bool:
        """Record the stream to a file using ffmpeg, tracking in database."""
        start_time = datetime.now(self.timezone)
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(self.output_dir, f"council_meeting_{timestamp}.mp4")

        os.makedirs(self.output_dir, exist_ok=True)

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
            self.ffmpeg_command,
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
            import time
            while True:
                # Check if stream is still live every 30 seconds
                time.sleep(30)

                if not self.stream_service.is_stream_live(stream_url):
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

            end_time = datetime.now(self.timezone)
            print(f"Recording saved: {output_file}")

            # Update recording status in database
            db.update_recording(recording_id, end_time, 'completed')

            # Log statistics
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                duration = int((end_time - start_time).total_seconds())
                print(f"Duration: {duration}s, Size: {file_size / (1024**2):.1f} MB")

            # Post-processing (experimental)
            if ENABLE_POST_PROCESSING:
                print("\n[EXPERIMENTAL] Post-processing enabled - splitting recording into segments")
                try:
                    from post_processor import PostProcessor
                    processor = PostProcessor(
                        silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
                        min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION,
                        ffmpeg_command=self.ffmpeg_command
                    )
                    result = processor.process_recording(output_file)
                    if result.get('success'):
                        print(f"[POST-PROCESS] Successfully created {result.get('segments_created', 0)} segments")
                    else:
                        print(f"[POST-PROCESS] Processing failed: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    print(f"[POST-PROCESS] Error during post-processing: {e}")
                    print("[POST-PROCESS] Original recording preserved")

            return True

        except Exception as e:
            error_msg = str(e)
            print(f"Error during recording: {error_msg}")

            # Update recording as failed
            db.update_recording(recording_id, datetime.now(self.timezone), 'failed', error_msg)
            db.log_stream_status(stream_url, 'error', meeting_id, error_msg)

            return False
