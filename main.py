#!/usr/bin/env python3
import time
import threading
from datetime import datetime
import schedule

# Import database functions
import database as db

# Import web server
import web_server

# Import configuration and services
from config import (
    CALGARY_TZ,
    ACTIVE_CHECK_INTERVAL,
    IDLE_CHECK_INTERVAL,
    STREAM_PAGE_URL,
    OUTPUT_DIR,
    MEETING_BUFFER_BEFORE,
    MEETING_BUFFER_AFTER
)
from services import (
    CalendarService,
    MeetingScheduler,
    StreamService,
    RecordingService
)

# Global flag to trigger calendar refresh
calendar_refresh_requested = False

# Initialize services
calendar_service = CalendarService()
meeting_scheduler = MeetingScheduler()
stream_service = StreamService()
recording_service = RecordingService(stream_service=stream_service)

def daily_calendar_refresh():
    """Scheduled task: Refresh calendar at midnight."""
    global calendar_refresh_requested
    now = datetime.now(CALGARY_TZ)
    print(f"\n[{now.strftime('%H:%M:%S')}] 📅 SCHEDULED TASK: Daily calendar refresh at midnight")
    calendar_refresh_requested = True

def run_scheduler():
    """Run the scheduler in a separate thread."""
    # Schedule daily calendar refresh at midnight Calgary time
    schedule.every().day.at("00:00").do(daily_calendar_refresh)

    print(f"📅 Scheduler initialized: Calendar refresh at 00:00 (midnight) Calgary time")

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

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
    print(f"Meeting buffer: {MEETING_BUFFER_BEFORE.seconds//60} min before, {MEETING_BUFFER_AFTER.seconds//3600} hours after")
    print(f"Web interface: http://0.0.0.0:5000")
    print("-" * 70)

    # Set recording service in web server so it can stop recordings
    web_server.set_recording_service(recording_service)

    # Start web server in background thread
    web_thread = threading.Thread(target=web_server.run_server, daemon=True)
    web_thread.start()
    print("Web server started on http://0.0.0.0:5000")
    print("-" * 70)

    # Initialize database
    db.init_database()

    # Start scheduler thread for midnight calendar refresh
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

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
    meetings = calendar_service.get_upcoming_meetings()

    if meetings:
        print("\nUpcoming meetings:")
        for i, meeting in enumerate(meetings[:5], 1):  # Show first 5
            room = meeting.get('room', 'Unknown')
            print(f"  {i}. {meeting['title']} [{room}]")
            print(f"     {meeting['raw_date']}")
        if len(meetings) > 5:
            print(f"  ... and {len(meetings) - 5} more")
    else:
        print("\nNo upcoming meetings found. Will poll periodically.")

    print("-" * 70)

    active_mode = False

    while True:
        try:
            global calendar_refresh_requested
            current_time = datetime.now(CALGARY_TZ)

            # Refresh calendar if scheduled task requested it
            if calendar_refresh_requested:
                print(f"[{current_time.strftime('%H:%M:%S')}] Processing scheduled calendar refresh...")
                meetings = calendar_service.get_upcoming_meetings(force_refresh=True)

            # Determine if we're in active monitoring mode
            in_window, current_meeting = meeting_scheduler.is_within_meeting_window(current_time, meetings)

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
                next_meeting = meeting_scheduler.get_next_meeting(current_time, meetings)
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

            # Check for stream - pass room info if available
            meeting_room = current_meeting.get('room') if current_meeting else None
            stream_url = stream_service.get_stream_url(room=meeting_room)

            if stream_url:
                if stream_service.is_stream_live(stream_url):
                    mode_label = "🔴 ACTIVE" if active_mode else "IDLE"
                    room_label = f" ({meeting_room})" if meeting_room else ""
                    print(f"[{current_time.strftime('%H:%M:%S')}] [{mode_label}] Stream is LIVE{room_label}! Starting recording...")
                    recording_service.record_stream(stream_url, current_meeting)
                    print(f"[{current_time.strftime('%H:%M:%S')}] Recording completed. Resuming monitoring...")
                else:
                    if active_mode:  # Only log during active mode to reduce noise
                        print(f"[{current_time.strftime('%H:%M:%S')}] [🔴 ACTIVE] Stream found but not live yet...")
            else:
                if active_mode:  # Only log during active mode
                    room_label = f" ({meeting_room})" if meeting_room else ""
                    print(f"[{current_time.strftime('%H:%M:%S')}] [🔴 ACTIVE] No stream URL found{room_label}...")

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
