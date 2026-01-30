#!/usr/bin/env python3
import os
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any
import schedule
import logging

# Import logging configuration
from logging_config import setup_logging

# Import database functions
import database as db

# Import web server
import web_server

# Import shared state for thread-safe access
from shared_state import monitoring_state, calendar_refresh_state

# Import configuration and services
from config import (
    CALGARY_TZ,
    ACTIVE_CHECK_INTERVAL,
    IDLE_CHECK_INTERVAL,
    STREAM_PAGE_URL,
    OUTPUT_DIR,
    MEETING_BUFFER_BEFORE,
    MEETING_BUFFER_AFTER,
    ENABLE_TRANSCRIPTION,
    ENABLE_POST_PROCESSING,
    WHISPER_MODEL,
    PYANNOTE_API_TOKEN,
    POST_PROCESS_SILENCE_THRESHOLD_DB,
    POST_PROCESS_MIN_SILENCE_DURATION,
    FFMPEG_COMMAND,
    validate_config
)
from services import (
    CalendarService,
    MeetingScheduler,
    StreamService,
    RecordingService
)

# Initialize services with dependency injection
calendar_service = CalendarService()
meeting_scheduler = MeetingScheduler()
stream_service = StreamService()

# Create optional services based on configuration
transcription_service = None
if ENABLE_TRANSCRIPTION:
    from transcription_service import TranscriptionService
    transcription_service = TranscriptionService(
        whisper_model=WHISPER_MODEL,
        pyannote_api_token=PYANNOTE_API_TOKEN
    )

post_processor = None
if ENABLE_POST_PROCESSING:
    from post_processor import PostProcessor
    post_processor = PostProcessor(
        silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
        min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION,
        ffmpeg_command=FFMPEG_COMMAND
    )

# Initialize recording service with all dependencies
recording_service = RecordingService(
    stream_service=stream_service,
    transcription_service=transcription_service,
    post_processor=post_processor
)

def daily_calendar_refresh() -> None:
    """Scheduled task: Refresh calendar at midnight."""
    logger = logging.getLogger(__name__)
    now = datetime.now(CALGARY_TZ)
    logger.info(f"\n[{now.strftime('%H:%M:%S')}] SCHEDULED TASK: Daily calendar refresh at midnight")
    calendar_refresh_state.request()

def run_scheduler() -> None:
    """Run the scheduler in a separate thread."""
    logger = logging.getLogger(__name__)
    # Schedule daily calendar refresh at midnight Calgary time
    schedule.every().day.at("00:00").do(daily_calendar_refresh)

    logger.info(f"Scheduler initialized: Calendar refresh at 00:00 (midnight) Calgary time")

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

def main() -> None:
    """Main monitoring loop with smart scheduling."""
    # Initialize logging first
    log_level = os.environ.get('LOG_LEVEL', 'INFO')
    log_dir = os.environ.get('LOG_DIR', './logs')
    setup_logging(log_level=log_level, log_dir=log_dir)

    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("Calgary Council Stream Recorder - Smart Scheduler Edition")
    logger.info("=" * 70)

    # Validate configuration at startup (fail fast if misconfigured)
    try:
        validate_config()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        logger.error("Please fix the configuration errors and restart the application")
        return  # Exit gracefully
    logger.info(f"Stream URL: {STREAM_PAGE_URL}")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info(f"Database: {db.DB_PATH}")
    logger.info(f"Active polling: every {ACTIVE_CHECK_INTERVAL}s (during meeting windows)")
    logger.info(f"Idle polling: every {IDLE_CHECK_INTERVAL}s (outside meeting windows)")
    logger.info(f"Meeting buffer: {MEETING_BUFFER_BEFORE.seconds//60} min before, {MEETING_BUFFER_AFTER.seconds//3600} hours after")
    logger.info(f"Web interface: http://0.0.0.0:5000")
    logger.info("-" * 70)

    # Check if monitoring should auto-start
    auto_start = os.environ.get('AUTO_START_MONITORING', 'false').lower() == 'true'
    monitoring_state.enabled = auto_start
    if auto_start:
        logger.info("Auto-start monitoring: ENABLED")
    else:
        logger.info("Auto-start monitoring: DISABLED - Use web interface to start")
    logger.info("-" * 70)

    # Set recording service in web server so it can stop recordings
    web_server.set_recording_service(recording_service)
    web_server.set_post_processor(post_processor)

    # Start web server in background thread
    web_thread = threading.Thread(target=web_server.run_server, daemon=True)
    web_thread.start()
    logger.info("Web server started on http://0.0.0.0:5000")
    logger.info("-" * 70)

    # Initialize database
    db.init_database()

    # Start scheduler thread for midnight calendar refresh
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Show recording statistics
    stats = db.get_recording_stats()
    if stats['total_recordings'] > 0:
        logger.info("\nRecording Statistics:")
        logger.info(f"  Total recordings: {stats['total_recordings']}")
        logger.info(f"  Completed: {stats['completed']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info(f"  Total size: {stats['total_size_gb']} GB")
        logger.info("-" * 70)

    # Fetch initial meeting schedule
    meetings = calendar_service.get_upcoming_meetings()

    if meetings:
        logger.info("\nUpcoming meetings:")
        for i, meeting in enumerate(meetings[:5], 1):  # Show first 5
            room = meeting.get('room', 'Unknown')
            logger.info(f"  {i}. {meeting['title']} [{room}]")
            logger.info(f"     {meeting['raw_date']}")
        if len(meetings) > 5:
            logger.info(f"  ... and {len(meetings) - 5} more")
    else:
        logger.info("\nNo upcoming meetings found. Will poll periodically.")

    logger.info("-" * 70)

    active_mode = False

    while True:
        try:
            current_time = datetime.now(CALGARY_TZ)

            # If monitoring is disabled, just sleep and check again
            if not monitoring_state.enabled:
                time.sleep(10)  # Check every 10 seconds if monitoring should be enabled
                continue

            # Refresh calendar if scheduled task requested it
            if calendar_refresh_state.requested:
                logger.info(f"[{current_time.strftime('%H:%M:%S')}] Processing scheduled calendar refresh...")
                meetings = calendar_service.get_upcoming_meetings(force_refresh=True)
                calendar_refresh_state.clear()

            # Determine if we're in active monitoring mode
            in_window, current_meeting = meeting_scheduler.is_within_meeting_window(current_time, meetings)

            # Log mode changes
            if in_window and not active_mode and current_meeting is not None:
                logger.info(f"\n{'='*70}")
                logger.info(f"ACTIVE MODE: Meeting window detected!")
                logger.info(f"   Meeting: {current_meeting['title']}")
                logger.info(f"   Scheduled: {current_meeting['raw_date']}")
                logger.info(f"   Polling every {ACTIVE_CHECK_INTERVAL} seconds")
                logger.info(f"{'='*70}\n")
                active_mode = True
            elif not in_window and active_mode:
                next_meeting = meeting_scheduler.get_next_meeting(current_time, meetings)
                logger.info(f"\n{'='*70}")
                logger.info(f"IDLE MODE: Meeting window ended")
                if next_meeting:
                    time_until = next_meeting['datetime'] - current_time
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    logger.info(f"   Next meeting in {hours}h {minutes}m: {next_meeting['title']}")
                logger.info(f"   Polling every {IDLE_CHECK_INTERVAL} seconds")
                logger.info(f"{'='*70}\n")
                active_mode = False

            # Check for stream - pass room info if available
            meeting_room = current_meeting.get('room') if current_meeting else None
            stream_url = stream_service.get_stream_url(room=meeting_room)

            if stream_url:
                if stream_service.is_stream_live(stream_url):
                    mode_label = "ACTIVE" if active_mode else "IDLE"
                    room_label = f" ({meeting_room})" if meeting_room else ""
                    logger.info(f"[{current_time.strftime('%H:%M:%S')}] [{mode_label}] Stream is LIVE{room_label}! Starting recording...")
                    recording_service.record_stream(stream_url, current_meeting)
                    logger.info(f"[{current_time.strftime('%H:%M:%S')}] Recording completed. Resuming monitoring...")
                else:
                    if active_mode:  # Only log during active mode to reduce noise
                        logger.info(f"[{current_time.strftime('%H:%M:%S')}] [ACTIVE] Stream found but not live yet...")
            else:
                if active_mode:  # Only log during active mode
                    room_label = f" ({meeting_room})" if meeting_room else ""
                    logger.info(f"[{current_time.strftime('%H:%M:%S')}] [ACTIVE] No stream URL found{room_label}...")

            # Dynamic sleep interval
            check_interval = ACTIVE_CHECK_INTERVAL if active_mode else IDLE_CHECK_INTERVAL
            time.sleep(check_interval)

        except KeyboardInterrupt:
            logger.info("\n\nShutting down recorder...")
            break
        except Exception as e:
            logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected error: {e}", exc_info=True)
            time.sleep(ACTIVE_CHECK_INTERVAL)  # Use shorter interval on error

if __name__ == '__main__':
    main()
