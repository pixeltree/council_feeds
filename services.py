#!/usr/bin/env python3
"""
Service classes for Calgary Council Stream Recorder.
Separates business logic from main application flow for better testability.
"""

import logging
import requests
import subprocess
import re
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from transcription_service import TranscriptionService
    from post_processor import PostProcessor

import database as db
from exceptions import RecordingStorageError
from resource_managers import recording_process
from config import (
    CALGARY_TZ,
    COUNCIL_CALENDAR_API,
    STREAM_PAGE_URL,
    STREAM_URL_PATTERNS,
    STREAM_URLS_BY_ROOM,
    COUNCIL_CHAMBER,
    ENGINEERING_TRADITIONS_ROOM,
    MEETING_BUFFER_BEFORE,
    MEETING_BUFFER_AFTER,
    YTDLP_COMMAND,
    OUTPUT_DIR,
    FFMPEG_COMMAND,
    ENABLE_POST_PROCESSING,
    POST_PROCESS_SILENCE_THRESHOLD_DB,
    POST_PROCESS_MIN_SILENCE_DURATION,
    AUDIO_DETECTION_MEAN_THRESHOLD_DB,
    AUDIO_DETECTION_MAX_THRESHOLD_DB,
    ENABLE_TRANSCRIPTION,
    WHISPER_MODEL,
    PYANNOTE_API_TOKEN,
    RECORDING_FORMAT,
    ENABLE_SEGMENTED_RECORDING,
    SEGMENT_DURATION,
    RECORDING_RECONNECT,
    ENABLE_STATIC_DETECTION,
    STATIC_MIN_GROWTH_KB,
    STATIC_CHECK_INTERVAL,
    STATIC_MAX_FAILURES,
    STATIC_SCENE_THRESHOLD
)
import os


class CalendarService:
    """Service for fetching and managing council meeting calendar."""

    def __init__(self, api_url: str = COUNCIL_CALENDAR_API, timezone: Any = CALGARY_TZ):
        self.api_url = api_url
        self.timezone = timezone
        self.logger = logging.getLogger(__name__)

    def determine_room(self, title: str) -> str:
        """Determine meeting room based on title."""
        title_lower = title.lower()
        if 'council meeting' in title_lower:
            return COUNCIL_CHAMBER
        else:
            # All committee meetings use Engineering Traditions Room
            return ENGINEERING_TRADITIONS_ROOM

    def fetch_council_meetings(self) -> List[Dict]:
        """Fetch upcoming meetings from Calgary Open Data API (both Council and Committee)."""
        try:
            response = requests.get(self.api_url, timeout=15)
            response.raise_for_status()
            meetings = response.json()

            # Process all meetings and determine their rooms
            all_meetings = []
            for meeting in meetings:
                title = meeting.get('title', '')
                try:
                    # Parse the meeting date
                    date_str = meeting.get('meeting_date', '')
                    # Parse as naive datetime first
                    meeting_dt_naive = date_parser.parse(date_str, fuzzy=True)

                    # Localize to Calgary timezone
                    meeting_dt = self.timezone.localize(meeting_dt_naive)

                    # Determine room based on title
                    room = self.determine_room(title)

                    all_meetings.append({
                        'title': title,
                        'datetime': meeting_dt,
                        'raw_date': date_str,
                        'link': meeting.get('link', ''),
                        'room': room
                    })
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Could not parse date '{date_str}': {e}")
                    continue

            # Sort by datetime
            all_meetings.sort(key=lambda x: x['datetime'])

            return all_meetings

        except Exception as e:
            self.logger.error(f"Error fetching council meetings: {e}", exc_info=True)
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

                self.logger.info(f"Using cached meeting schedule (last updated: {last_refresh_dt.strftime('%Y-%m-%d %H:%M %Z')})")
            except (ValueError, TypeError):
                needs_refresh = True
        else:
            needs_refresh = True

        # Fetch fresh data if needed
        if needs_refresh:
            self.logger.info("Fetching fresh meeting schedule from Calgary Open Data API...")
            meetings = self.fetch_council_meetings()

            if meetings:
                # Save to database
                saved_count = db.save_meetings(meetings)
                db.set_metadata('last_calendar_refresh', now.isoformat())
                self.logger.info(f"Saved {saved_count} Council meetings to database")

        # Always return from database to ensure consistency
        return db.get_upcoming_meetings()


class MeetingScheduler:
    """Service for determining meeting windows and scheduling logic."""

    def __init__(
        self,
        buffer_before: timedelta = MEETING_BUFFER_BEFORE,
        buffer_after: timedelta = MEETING_BUFFER_AFTER,
        timezone: Any = CALGARY_TZ
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
        stream_url_patterns: Optional[List[str]] = None,
        ytdlp_command: str = YTDLP_COMMAND
    ):
        self.stream_page_url = stream_page_url
        self.stream_url_patterns = stream_url_patterns or STREAM_URL_PATTERNS
        self.ytdlp_command = ytdlp_command
        self.logger = logging.getLogger(__name__)

    def get_stream_url(self, room: Optional[str] = None) -> Optional[str]:
        """Extract the HLS stream URL using yt-dlp or try common patterns.

        Args:
            room: Optional room name to try room-specific stream URLs first
        """
        # Determine which URL patterns to try based on room
        patterns_to_try = []
        if room and room in STREAM_URLS_BY_ROOM:
            # Try room-specific URLs first
            patterns_to_try = STREAM_URLS_BY_ROOM[room]
            self.logger.info(f"Trying {room} stream URLs...")
        else:
            # Fall back to all patterns
            patterns_to_try = self.stream_url_patterns

        # Try using yt-dlp to extract the stream URL (skip if room-specific)
        if not room:
            try:
                result = subprocess.run(
                    [self.ytdlp_command, '-g', '--no-warnings', self.stream_page_url],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if result.returncode == 0 and result.stdout.strip():
                    url = result.stdout.strip()
                    self.logger.info(f"yt-dlp found stream: {url}")
                    return url
            except subprocess.TimeoutExpired:
                self.logger.warning("yt-dlp timed out")
            except FileNotFoundError:
                self.logger.warning("yt-dlp not found, trying manual methods...")
            except Exception as e:
                self.logger.error(f"yt-dlp error: {e}", exc_info=True)

        # Try room-specific or common ISILive URL patterns
        for pattern_url in patterns_to_try:
            try:
                response = requests.head(pattern_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    self.logger.info(f"Found working stream pattern: {pattern_url}")
                    return pattern_url
            except Exception:
                # Try next pattern if this one fails
                pass

        # Try parsing the page
        try:
            response = requests.get(self.stream_page_url, timeout=10)
            response.raise_for_status()

            # Look for m3u8 URL in the page content
            m3u8_pattern = re.compile(r'https?://[^\s"\']+\.m3u8[^\s"\']*')
            matches = m3u8_pattern.findall(response.text)

            if matches:
                return str(matches[0])

            # Alternative: parse for video source tags
            soup = BeautifulSoup(response.text, 'html.parser')
            video_tags = soup.find_all(['video', 'source'])
            for tag in video_tags:
                src = tag.get('src', '')
                if '.m3u8' in src:
                    if src.startswith('http'):
                        return str(src)
                    elif src.startswith('//'):
                        return 'https:' + str(src)

            return None
        except Exception as e:
            self.logger.error(f"Error fetching stream URL: {e}", exc_info=True)
            return None

    def is_stream_live(self, stream_url: str) -> bool:
        """Check if the stream is currently live."""
        if not stream_url:
            return False

        try:
            response = requests.head(stream_url, timeout=10, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            # Try GET request as fallback
            try:
                response = requests.get(stream_url, timeout=10, stream=True)
                return response.status_code == 200
            except Exception:
                # Return False if both HEAD and GET fail
                return False

class RecordingService:
    """Service for recording streams using ffmpeg."""

    def __init__(
        self,
        output_dir: str = OUTPUT_DIR,
        ffmpeg_command: str = FFMPEG_COMMAND,
        timezone: Any = CALGARY_TZ,
        stream_service: Optional[StreamService] = None,
        transcription_service: Optional["TranscriptionService"] = None,
        post_processor: Optional["PostProcessor"] = None
    ):
        self.output_dir = output_dir
        self.ffmpeg_command = ffmpeg_command
        self.timezone = timezone
        self.stream_service = stream_service or StreamService()
        self.transcription_service = transcription_service
        self.post_processor = post_processor
        self.current_process: Optional[subprocess.Popen[bytes]] = None
        self.current_recording_id: Optional[int] = None
        self.stop_requested = False
        self.logger = logging.getLogger(__name__)

    def _determine_output_paths(self, timestamp: str) -> tuple[str, Optional[str], str]:
        """Determine output file paths and format for recording.

        Args:
            timestamp: Timestamp string for file naming

        Returns:
            Tuple of (output_file, output_pattern, format_ext)
        """
        format_ext = RECORDING_FORMAT if RECORDING_FORMAT in ['mkv', 'mp4', 'ts'] else 'mkv'

        if ENABLE_SEGMENTED_RECORDING:
            output_pattern = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}_segment_%03d.{format_ext}"
            )
            output_file = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}.{format_ext}"
            )
        else:
            output_file = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}.{format_ext}"
            )
            output_pattern = None

        return output_file, output_pattern, format_ext

    def _find_meeting_id(self, current_meeting: Optional[Dict[str, Any]]) -> Optional[int]:
        """Find associated meeting ID in database.

        Args:
            current_meeting: Current meeting information

        Returns:
            Meeting ID if found, None otherwise
        """
        if not current_meeting:
            return None

        db_meeting = db.find_meeting_by_datetime(current_meeting['datetime'])
        if db_meeting:
            self.logger.info(f"Associated with meeting: {db_meeting['title']}")
            return int(db_meeting['id'])
        return None

    def _create_recording_record(
        self,
        meeting_id: Optional[int],
        output_file: str,
        stream_url: str,
        start_time: datetime
    ) -> int:
        """Create recording record in database and initialize tracking.

        Args:
            meeting_id: Associated meeting ID
            output_file: Path to output file
            stream_url: Stream URL being recorded
            start_time: Recording start time

        Returns:
            Recording ID
        """
        recording_id_result = db.create_recording(meeting_id, output_file, stream_url, start_time)
        if recording_id_result is None:
            raise RecordingStorageError(output_file, 'create', 'Failed to create recording in database')
        recording_id = int(recording_id_result)
        self.current_recording_id = recording_id
        self.stop_requested = False
        db.log_stream_status(stream_url, 'live', meeting_id, 'Recording started')
        return recording_id

    def _build_ffmpeg_command(
        self,
        stream_url: str,
        output_file: str,
        output_pattern: Optional[str],
        format_ext: str
    ) -> list[str]:
        """Build ffmpeg command with resilient options.

        Args:
            stream_url: URL of the stream to record
            output_file: Path to output file
            output_pattern: Pattern for segmented recording (if enabled)
            format_ext: File format extension

        Returns:
            List of command arguments for ffmpeg
        """
        cmd = [self.ffmpeg_command]

        # Add reconnect options if enabled
        if RECORDING_RECONNECT:
            cmd.extend([
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_delay_max', '5'
            ])

        if not stream_url:
            raise ValueError("stream_url cannot be empty")
        cmd.extend(['-i', stream_url])

        # Copy streams without re-encoding
        cmd.extend(['-c', 'copy'])

        # Fix AAC stream
        if format_ext != 'ts':  # TS doesn't need this
            cmd.extend(['-bsf:a', 'aac_adtstoasc'])

        # Add format-specific options
        if ENABLE_SEGMENTED_RECORDING:
            # Segmented recording for resilience
            if not output_pattern:
                raise ValueError("output_pattern is required when ENABLE_SEGMENTED_RECORDING is True")
            cmd.extend([
                '-f', 'segment',
                '-segment_time', str(SEGMENT_DURATION),
                '-segment_format', format_ext if format_ext == 'mkv' else 'matroska',
                '-reset_timestamps', '1',
                '-strftime', '1',  # Allow time formatting in segment names
                output_pattern
            ])
        else:
            # Single file recording
            if format_ext == 'mp4':
                # Use fragmented MP4 for better resilience
                cmd.extend([
                    '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
                    '-f', 'mp4'
                ])
            elif format_ext == 'ts':
                cmd.extend(['-f', 'mpegts'])
            else:  # mkv
                cmd.extend(['-f', 'matroska'])

            cmd.append(output_file)

        return cmd

    def _check_audio_levels(self, file_path: str) -> tuple[Optional[float], Optional[float]]:
        """Check audio levels in a recording file.

        Args:
            file_path: Path to the file to check

        Returns:
            Tuple of (mean_volume, max_volume) in dB, or (None, None) if check fails
        """
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_command, '-i', file_path,
                    '-af', 'volumedetect',
                    '-f', 'null', '-'
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True
            )

            mean_volume = None
            max_volume = None
            for line in result.stderr.split('\n'):
                if 'mean_volume:' in line:
                    try:
                        mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    except (ValueError, IndexError):
                        pass
                if 'max_volume:' in line:
                    try:
                        max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                    except (ValueError, IndexError):
                        pass

            return mean_volume, max_volume

        except subprocess.TimeoutExpired:
            self.logger.warning(f"[STATIC CHECK] Audio detection timed out on {os.path.basename(file_path)}")
            return None, None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"[STATIC CHECK] Audio detection failed (ffmpeg error): {e}", exc_info=True)
            return None, None
        except Exception as e:
            self.logger.error(f"[STATIC CHECK] Audio detection failed: {e}", exc_info=True)
            return None, None


    def _validate_recording_content(self, output_file: str, recording_id: int, end_time: datetime) -> bool:
        """Validate that recording has audio content and remove if empty.

        Args:
            output_file: Path to the recording file
            recording_id: Database ID of the recording
            end_time: Recording end time

        Returns:
            True if recording has content, False if it was removed
        """
        has_content = False
        if os.path.exists(output_file):
            self.logger.info("Checking if recording has audio content...")
            mean_volume, max_volume = self._check_audio_levels(output_file)

            if mean_volume is not None and max_volume is not None:
                self.logger.info(f"Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB")
                # If audio is reasonably loud, it has content
                if mean_volume > -50 or max_volume > -30:
                    has_content = True
                else:
                    self.logger.warning("Recording appears to have no real audio content (levels too low)")
            else:
                self.logger.warning("Could not detect audio levels, assuming has content")
                has_content = True  # Default to keeping if check fails

        # If no content, remove the recording
        if not has_content:
            self.logger.warning("No audio content detected - removing empty recording")
            try:
                if os.path.exists(output_file):
                    os.remove(output_file)
                    self.logger.info(f"Removed empty recording file: {output_file}")
            except Exception as e:
                self.logger.error(f"Could not delete file: {e}", exc_info=True)

            # Mark recording as failed in database
            db.update_recording(recording_id, end_time, 'failed', 'No audio content detected')
            self.logger.info("Recording marked as failed (no content)")

        return has_content

    def _run_post_processing(self, output_file: str, recording_id: int) -> bool:
        """Run post-processing on the recording.

        Args:
            output_file: Path to the recording file
            recording_id: Database ID of the recording

        Returns:
            True if post-processing deleted the file (skip transcription), False otherwise
        """
        if not ENABLE_POST_PROCESSING:
            return False

        self.logger.info("[EXPERIMENTAL] Post-processing enabled - splitting recording into segments")
        try:
            # Use injected post processor or create a default one
            if self.post_processor is None:
                from post_processor import PostProcessor
                processor = PostProcessor(
                    silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
                    min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION,
                    ffmpeg_command=self.ffmpeg_command
                )
            else:
                processor = self.post_processor

            result = processor.process_recording(output_file, recording_id)
            if result.get('success'):
                self.logger.info(f"[POST-PROCESS] Successfully created {result.get('segments_created', 0)} segments")
            elif result.get('deleted'):
                self.logger.warning(f"[POST-PROCESS] Recording removed: {result.get('message', 'No audio detected')}")
                return True  # File was deleted
            else:
                self.logger.error(f"[POST-PROCESS] Processing failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            self.logger.error(f"[POST-PROCESS] Error during post-processing: {e}", exc_info=True)
            self.logger.info("[POST-PROCESS] Original recording preserved")

        return False

    def _run_transcription(self, output_file: str, recording_id: int) -> None:
        """Run transcription on the recording.

        Args:
            output_file: Path to the recording file
            recording_id: Database ID of the recording
        """
        if not ENABLE_TRANSCRIPTION:
            return

        self.logger.info("[TRANSCRIPTION] Transcription enabled - generating transcript with speaker diarization")
        try:
            # Use injected transcription service or create a default one
            if self.transcription_service is None:
                from transcription_service import TranscriptionService
                transcriber = TranscriptionService(
                    whisper_model=WHISPER_MODEL,
                    pyannote_api_token=PYANNOTE_API_TOKEN
                )
            else:
                transcriber = self.transcription_service

            # Transcribe the video
            transcript_result = transcriber.transcribe_with_speakers(output_file)

            # Save formatted text version
            text_output = output_file + '.transcript.txt'
            formatted_text = transcriber.format_transcript_as_text(transcript_result['segments'])
            with open(text_output, 'w', encoding='utf-8') as f:
                f.write(formatted_text)

            self.logger.info(f"[TRANSCRIPTION] Successfully transcribed with {transcript_result['num_speakers']} speakers")
            self.logger.info(f"[TRANSCRIPTION] Transcript saved to: {text_output}")

            # Update database with transcript path
            if recording_id:
                db.update_recording_transcript(recording_id, output_file + '.transcript.json')

        except Exception as e:
            self.logger.error(f"[TRANSCRIPTION] Error during transcription: {e}", exc_info=True)
            self.logger.info("[TRANSCRIPTION] Recording preserved, transcription skipped")

    def record_stream(
        self,
        stream_url: str,
        current_meeting: Optional[Dict] = None
    ) -> bool:
        """Record the stream to a file using ffmpeg, tracking in database."""
        start_time = datetime.now(self.timezone)
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")

        # Determine output paths
        output_file, output_pattern, format_ext = self._determine_output_paths(timestamp)
        os.makedirs(self.output_dir, exist_ok=True)

        if output_pattern:
            self.logger.info(f"Starting segmented recording: {output_pattern}")
        else:
            self.logger.info(f"Starting recording: {output_file}")

        # Find associated meeting and create recording record
        meeting_id = self._find_meeting_id(current_meeting)
        recording_id = self._create_recording_record(meeting_id, output_file, stream_url, start_time)

        # Build and execute ffmpeg command
        cmd = self._build_ffmpeg_command(stream_url, output_file, output_pattern, format_ext)

        try:
            with recording_process(cmd, timeout=10) as process:
                self.current_process = process

                self.logger.info(f"Recording started (PID: {process.pid})")

                # Monitor the process
                import time
                import glob
                static_checks = 0

                while True:
                    # Check if stream is still live
                    time.sleep(STATIC_CHECK_INTERVAL)

                    # Check for static content using ffmpeg scene detection
                    if ENABLE_STATIC_DETECTION:
                        # Get the most recent file to analyze
                        file_to_check = None
                        if ENABLE_SEGMENTED_RECORDING and output_pattern:
                            base_pattern = output_pattern.replace('%03d', '*')
                            segment_files = sorted(glob.glob(base_pattern))
                            if segment_files:
                                file_to_check = segment_files[-1]  # Most recent segment
                        elif os.path.exists(output_file):
                            file_to_check = output_file

                        if file_to_check and os.path.exists(file_to_check):
                            mean_volume, max_volume = self._check_audio_levels(file_to_check)

                            self.logger.debug(f"[STATIC CHECK] Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB")

                            # If audio is very quiet, likely static placeholder
                            if mean_volume is not None and max_volume is not None:
                                if mean_volume < AUDIO_DETECTION_MEAN_THRESHOLD_DB or max_volume < AUDIO_DETECTION_MAX_THRESHOLD_DB:
                                    static_checks += 1
                                    self.logger.warning(f"Low audio levels detected. Static check {static_checks}/{STATIC_MAX_FAILURES}")

                                    if static_checks >= STATIC_MAX_FAILURES:
                                        self.logger.warning("Stream appears to be static (no audio/placeholder). Stopping recording...")
                                        db.log_stream_status(stream_url, 'static', meeting_id, 'Static content detected (silence)')
                                        self.stop_requested = True
                                else:
                                    if static_checks > 0:
                                        self.logger.info("[STATIC CHECK] Audio detected, resetting counter")
                                    static_checks = 0  # Reset counter if audio detected
                            else:
                                self.logger.warning("[STATIC CHECK] Could not parse audio levels")

                    # Check if stop was requested
                    if self.stop_requested:
                        self.logger.info("Stop requested by user. Stopping recording...")
                        db.log_stream_status(stream_url, 'offline', meeting_id, 'Stopped by user')
                        break

                    if not self.stream_service.is_stream_live(stream_url):
                        self.logger.info("Stream is no longer live. Stopping recording...")
                        db.log_stream_status(stream_url, 'offline', meeting_id, 'Stream ended')
                        break

                    # Check if process is still running
                    if process.poll() is not None:
                        self.logger.info("Recording process ended")
                    break

            end_time = datetime.now(self.timezone)

            # Clean up process tracking
            self.current_process = None
            self.current_recording_id = None

            # If segmented, merge segments into single file
            if ENABLE_SEGMENTED_RECORDING and output_pattern:
                self.logger.info("Merging recording segments...")
                merged_file = self._merge_segments(output_pattern, output_file, timestamp, format_ext)
                if merged_file:
                    output_file = merged_file
                    self.logger.info(f"Recording saved: {output_file}")
                else:
                    self.logger.warning("Could not merge segments, keeping individual segments")
            else:
                self.logger.info(f"Recording saved: {output_file}")

            # Check if recording has any content
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                duration = int((end_time - start_time).total_seconds())
                self.logger.info(f"Duration: {duration}s, Size: {file_size / (1024**2):.1f} MB")

            # Validate recording has content
            has_content = self._validate_recording_content(output_file, recording_id, end_time)
            if not has_content:
                return True  # Return success since we handled it properly

            # Update recording status in database as completed
            db.update_recording(recording_id, end_time, 'completed')

            # Run post-processing if enabled
            file_was_deleted = self._run_post_processing(output_file, recording_id)
            if file_was_deleted:
                return True  # Skip transcription since file was deleted

            # Run transcription if enabled
            self._run_transcription(output_file, recording_id)

            return True

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error during recording: {error_msg}", exc_info=True)

            # Clean up process tracking
            self.current_process = None
            self.current_recording_id = None

            # Update recording as failed
            db.update_recording(recording_id, datetime.now(self.timezone), 'failed', error_msg)
            db.log_stream_status(stream_url, 'error', meeting_id, error_msg)

            return False

    def _merge_segments(self, pattern: str, output_file: str, timestamp: str, format_ext: str) -> Optional[str]:
        """Merge recording segments into a single file."""
        import glob

        # Find all segment files
        segment_dir = os.path.dirname(pattern)
        segment_pattern = os.path.basename(pattern).replace('%03d', '*')
        segments = sorted(glob.glob(os.path.join(segment_dir, segment_pattern)))

        if not segments:
            self.logger.warning("No segments found to merge")
            return None

        if len(segments) == 1:
            # Only one segment, just rename it
            try:
                os.rename(segments[0], output_file)
                return output_file
            except Exception as e:
                self.logger.error(f"Error renaming single segment: {e}", exc_info=True)
                raise RecordingStorageError(segments[0], 'rename', str(e))

        # Create concat file list for ffmpeg
        concat_file = os.path.join(self.output_dir, f"concat_{timestamp}.txt")
        try:
            with open(concat_file, 'w') as f:
                for segment in segments:
                    f.write(f"file '{os.path.abspath(segment)}'\n")

            # Merge using ffmpeg concat
            merge_cmd = [
                self.ffmpeg_command,
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                output_file
            ]

            result = subprocess.run(merge_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Successfully merged, delete segments and concat file
                for segment in segments:
                    try:
                        os.remove(segment)
                    except OSError:
                        # Best-effort cleanup; ignore if file cannot be removed
                        pass
                try:
                    os.remove(concat_file)
                except OSError:
                    # Best-effort cleanup; ignore if file cannot be removed
                    pass
                return output_file
            else:
                self.logger.error(f"Merge failed: {result.stderr}")
                return None

        except Exception as e:
            self.logger.error(f"Error merging segments: {e}", exc_info=True)
            raise RecordingStorageError(output_file, 'merge', str(e))

    def stop_recording(self) -> bool:
        """Request the current recording to stop."""
        if self.current_process and self.current_process.poll() is None:
            self.stop_requested = True
            return True
        return False

    def is_recording(self) -> bool:
        """Check if a recording is currently in progress."""
        return self.current_process is not None and self.current_process.poll() is None
