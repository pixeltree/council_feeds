#!/usr/bin/env python3
"""
Web server module for Calgary Council Stream Recorder.
Provides a simple web interface to view recording status and upcoming meetings.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Union, Tuple, Any

from flask import Flask, render_template, jsonify, send_file, request, Response

import database as db
from config import CALGARY_TZ, WEB_HOST, WEB_PORT, OUTPUT_DIR
from shared_state import monitoring_state
from exceptions import (
    CouncilRecorderError,
    RecordingStorageError,
    TranscriptionError,
    DatabaseError
)
from services.vod_service import VodService
from background_tasks import task_manager

logger = logging.getLogger(__name__)
app = Flask(__name__)

# Global references to services (set by main.py)
recording_service = None

def set_recording_service(service: Any) -> None:
    """Set the recording service instance for the web server to use."""
    global recording_service
    recording_service = service


def download_vod_with_retry(recording_id: int, escriba_url: str, output_path: str, is_manual_retry: bool = False) -> None:
    """
    Helper function to download VOD with retry logic and exponential backoff.

    Args:
        recording_id: Database ID of the recording
        escriba_url: URL to download from
        output_path: Path to save the video
        is_manual_retry: Whether this is a manual retry initiated by user
    """
    vod_service = VodService()
    max_retries = 3
    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            if retry_count > 0:
                logger.info(f"Retry {retry_count}/{max_retries} for recording {recording_id}")
                db.add_recording_log(recording_id, f"Retry attempt {retry_count}/{max_retries}", 'info')
            else:
                if is_manual_retry:
                    logger.info(f"Starting VOD download retry for recording {recording_id} from {escriba_url}")
                    db.add_recording_log(recording_id, "Manual retry initiated by user", 'info')
                else:
                    logger.info(f"Starting VOD download for recording {recording_id} from {escriba_url}")

            # Download the video
            vod_service.download_vod(escriba_url, output_path, recording_id)

            # Update recording to completed (file size and duration are calculated by update_recording)
            db.update_recording(
                recording_id,
                datetime.now(CALGARY_TZ),
                'completed'
            )

            logger.info(f"VOD download completed for recording {recording_id}")
            if is_manual_retry:
                db.add_recording_log(recording_id, "Download completed successfully", 'info')
            return

        except Exception as e:
            last_error = e
            retry_count += 1
            logger.warning(f"VOD download attempt {retry_count} failed for recording {recording_id}: {e}")
            db.add_recording_log(recording_id, f"Download attempt {retry_count}/{max_retries} failed: {str(e)}", 'error')

            if retry_count < max_retries:
                wait_time = 5 * retry_count  # Exponential backoff: 5s, 10s, 15s
                db.add_recording_log(recording_id, f"Retrying in {wait_time} seconds...", 'info')
                time.sleep(wait_time)

    # All retries failed
    logger.error(f"VOD download failed for recording {recording_id} after {max_retries} attempts: {last_error}", exc_info=True)
    db.add_recording_log(recording_id, f"All {max_retries} download attempts failed", 'error')
    db.update_recording(
        recording_id,
        datetime.now(CALGARY_TZ),
        'failed',
        error_message=f"Failed after {max_retries} attempts: {str(last_error)}"
    )


def get_current_recording() -> Optional[Dict[str, Any]]:
    """Get currently active recording if any."""
    with db.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                r.id,
                r.start_time,
                r.file_path,
                m.title as meeting_title
            FROM recordings r
            LEFT JOIN meetings m ON r.meeting_id = m.id
            WHERE r.status = 'recording'
            ORDER BY r.start_time DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            start_time = db.parse_datetime_from_db(row['start_time'])
            return {
                'id': row['id'],
                'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'file_path': row['file_path'],
                'meeting_title': row['meeting_title']
            }
        return None


def format_recordings(recordings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format recordings for display."""
    formatted = []
    for rec in recordings:
        start_time = db.parse_datetime_from_db(rec['start_time']) if rec['start_time'] else None

        formatted.append({
            'meeting_title': rec['meeting_title'],
            'start_time': start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown',
            'duration_seconds': rec['duration_seconds'],
            'duration_minutes': round(rec['duration_seconds'] / 60) if rec['duration_seconds'] else None,
            'file_size_bytes': rec['file_size_bytes'],
            'file_size_mb': round(rec['file_size_bytes'] / (1024**2), 1) if rec['file_size_bytes'] else None,
            'status': rec['status'],
            'post_process_status': rec.get('post_process_status'),
            'post_process_error': rec.get('post_process_error')
        })

    return formatted


@app.route('/')
def index() -> str:
    """Main status page."""
    # Get current recording status
    current_recording = get_current_recording()

    # Get statistics
    stats = db.get_recording_stats()

    # Get upcoming meetings
    meetings = db.get_upcoming_meetings(limit=10)

    # Get recent recordings
    recent_recordings = db.get_recent_recordings(limit=10)
    formatted_recordings = format_recordings(recent_recordings)

    # Get monitoring status
    monitoring_enabled = monitoring_state.enabled

    # Current time
    now = datetime.now(CALGARY_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')

    return render_template(
        'index.html',
        current_recording=current_recording,
        stats=stats,
        meetings=meetings,
        recordings=formatted_recordings,
        monitoring_enabled=monitoring_enabled,
        now=now
    )


@app.route('/recordings')
def recordings_list() -> str:
    """Recordings list page with segments."""
    recordings = db.get_recent_recordings(limit=50)

    # Format recordings
    formatted_recordings = []
    for rec in recordings:
        start_time = db.parse_datetime_from_db(rec['start_time']) if rec['start_time'] else None

        formatted_recordings.append({
            'id': rec['id'],
            'meeting_title': rec['meeting_title'] or 'Council Meeting',
            'start_time': start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown',
            'duration_minutes': round(rec['duration_seconds'] / 60) if rec['duration_seconds'] else None,
            'file_size_mb': round(rec['file_size_bytes'] / (1024**2), 1) if rec['file_size_bytes'] else None,
            'status': rec['status'],
            'has_transcript': bool(rec['transcript_path']),
            'transcript_path': rec['transcript_path'],
            'file_path': rec['file_path']
        })

    return render_template('recordings.html', recordings=formatted_recordings)


@app.route('/import-vod')
def import_vod_page() -> str:
    """VOD import form page."""
    return render_template('import_vod.html')


@app.route('/recording/<int:recording_id>')
def recording_detail(recording_id: int) -> Union[str, Tuple[str, int]]:
    """Recording detail page."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    # Format recording data
    start_time = db.parse_datetime_from_db(recording['start_time']) if recording['start_time'] else None
    end_time = db.parse_datetime_from_db(recording['end_time']) if recording['end_time'] else None

    # Get meeting link if available
    meeting_link = None
    meeting_id = recording.get('meeting_id')
    if meeting_id:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT link FROM meetings WHERE id = ?", (meeting_id,))
            row = cursor.fetchone()
            if row:
                meeting_link = row['link']

    formatted_recording = {
        'id': recording['id'],
        'meeting_id': meeting_id,
        'meeting_link': meeting_link,
        'meeting_title': recording['meeting_title'] or 'Council Meeting',
        'start_time': start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown',
        'end_time': end_time.strftime('%Y-%m-%d %H:%M') if end_time else None,
        'duration_minutes': round(recording['duration_seconds'] / 60) if recording['duration_seconds'] else None,
        'file_size_mb': round(recording['file_size_bytes'] / (1024**2), 1) if recording['file_size_bytes'] else None,
        'status': recording['status'],
        'has_transcript': bool(recording['transcript_path']),
        'transcript_path': recording['transcript_path'],
        'file_path': recording['file_path'],
        'diarization_pyannote_path': recording.get('diarization_pyannote_path'),
        'diarization_gemini_path': recording.get('diarization_gemini_path'),
        'diarization_status': recording.get('diarization_status'),
        'pyannote_job_id': recording.get('pyannote_job_id')
    }

    # Get logs in reverse chronological order
    logs = db.get_recording_logs(recording_id, limit=200)

    return render_template(
        'recording_detail.html',
        recording=formatted_recording,
        logs=logs
    )


@app.route('/api/status')
def api_status() -> Response:
    """API endpoint for status information."""
    current_recording = get_current_recording()
    stats = db.get_recording_stats()
    meetings = db.get_upcoming_meetings(limit=5)

    return jsonify({
        'status': 'recording' if current_recording else 'monitoring',
        'current_recording': current_recording,
        'stats': stats,
        'upcoming_meetings': [
            {
                'title': m['title'],
                'datetime': m['datetime'].isoformat(),
                'raw_date': m['raw_date']
            }
            for m in meetings
        ]
    })


@app.route('/api/stop-recording', methods=['POST'])
def api_stop_recording() -> Union[Response, Tuple[Response, int]]:
    """API endpoint to stop the current recording."""
    global recording_service

    if recording_service is None:
        return jsonify({
            'success': False,
            'error': 'Recording service not available'
        }), 500

    if not recording_service.is_recording():
        return jsonify({
            'success': False,
            'error': 'No recording in progress'
        }), 400

    success = recording_service.stop_recording()

    if success:
        return jsonify({
            'success': True,
            'message': 'Recording stop requested'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to stop recording'
        }), 500


@app.route('/api/monitoring/start', methods=['POST'])
def api_start_monitoring() -> Response:
    """API endpoint to start monitoring."""
    monitoring_state.enable()
    return jsonify({
        'success': True,
        'message': 'Monitoring started'
    })


@app.route('/api/monitoring/stop', methods=['POST'])
def api_stop_monitoring() -> Response:
    """API endpoint to stop monitoring."""
    monitoring_state.disable()
    return jsonify({
        'success': True,
        'message': 'Monitoring stopped'
    })


@app.route('/api/monitoring/status', methods=['GET'])
def api_monitoring_status() -> Response:
    """API endpoint to get monitoring status."""
    return jsonify({
        'monitoring_enabled': monitoring_state.enabled
    })


@app.route('/api/refresh-agenda', methods=['POST'])
def api_refresh_agenda() -> Union[Response, Tuple[Response, int]]:
    """API endpoint to manually refresh the meeting agenda."""
    global recording_service

    if recording_service is None:
        return jsonify({
            'success': False,
            'error': 'Recording service not available'
        }), 500

    try:
        # Refresh the calendar
        if hasattr(recording_service, 'calendar_service'):
            meetings = recording_service.calendar_service.get_upcoming_meetings(force_refresh=True)
            return jsonify({
                'success': True,
                'message': f'Agenda refreshed. Found {len(meetings)} upcoming meetings.',
                'meeting_count': len(meetings)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Calendar service not available'
            }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to refresh agenda: {str(e)}'
        }), 500


@app.route('/download/transcript/<int:recording_id>')
def download_recording_transcript(recording_id: int) -> Union[Response, Tuple[str, int]]:
    """Download transcript for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording or not recording['transcript_path']:
        return "Transcript not found", 404

    if not os.path.exists(recording['transcript_path']):
        return "Transcript file not found", 404

    return send_file(recording['transcript_path'], as_attachment=True)


@app.route('/download/diarization/<int:recording_id>')
def download_recording_diarization(recording_id: int) -> Union[Response, Tuple[str, int]]:
    """Download diarization data (prefers Gemini-refined, falls back to pyannote)."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    # Try Gemini-refined first
    gemini_path = recording.get('diarization_gemini_path')
    if gemini_path and os.path.exists(gemini_path):
        logger.info(f"Serving gemini diarization for recording {recording_id}")
        return send_file(gemini_path, as_attachment=True)

    # Fall back to pyannote
    pyannote_path = recording.get('diarization_pyannote_path')
    if pyannote_path and os.path.exists(pyannote_path):
        logger.info(f"Serving pyannote diarization for recording {recording_id}")
        return send_file(pyannote_path, as_attachment=True)

    # Fall back to legacy path
    file_path = recording.get('file_path')
    if file_path:
        legacy_path = file_path + '.diarization.json'
        if os.path.exists(legacy_path):
            logger.info(f"Serving legacy diarization for recording {recording_id}")
            return send_file(legacy_path, as_attachment=True)

    logger.warning(f"Diarization file not found for recording {recording_id}")
    return "Diarization file not found", 404


@app.route('/download/diarization/pyannote/<int:recording_id>')
def download_recording_diarization_pyannote(recording_id: int) -> Union[Response, Tuple[str, int]]:
    """Download pyannote diarization data for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    pyannote_path = recording.get('diarization_pyannote_path')
    if pyannote_path and os.path.exists(pyannote_path):
        logger.info(f"Serving pyannote diarization for recording {recording_id}")
        return send_file(pyannote_path, as_attachment=True)

    # Fall back to trying file_path based path
    file_path = recording.get('file_path')
    if file_path:
        fallback_path = file_path + '.diarization.pyannote.json'
        if os.path.exists(fallback_path):
            return send_file(fallback_path, as_attachment=True)

    logger.warning(f"Pyannote diarization file not found for recording {recording_id}")
    return "Pyannote diarization file not found", 404


@app.route('/download/gemini-debug/<int:recording_id>')
def download_gemini_debug(recording_id: int) -> Union[Response, Tuple[str, int]]:
    """Download Gemini API response debug file."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    debug_path = recording['file_path'] + '.gemini_response_debug.txt'

    if not os.path.exists(debug_path):
        return "Gemini debug file not found. Run speaker refinement first.", 404

    return send_file(
        debug_path,
        as_attachment=True,
        download_name=f"gemini_debug_recording_{recording_id}.txt"
    )


@app.route('/download/diarization/gemini/<int:recording_id>')
def download_recording_diarization_gemini(recording_id: int) -> Union[Response, Tuple[str, int]]:
    """Download Gemini-refined diarization data for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    gemini_path = recording.get('diarization_gemini_path')
    if gemini_path and os.path.exists(gemini_path):
        logger.info(f"Serving gemini diarization for recording {recording_id}")
        return send_file(gemini_path, as_attachment=True)

    # Fall back to trying file_path based path
    file_path = recording.get('file_path')
    if file_path:
        fallback_path = file_path + '.diarization.gemini.json'
        if os.path.exists(fallback_path):
            return send_file(fallback_path, as_attachment=True)

    logger.warning(f"Gemini diarization file not found for recording {recording_id}")
    return "Gemini diarization file not found", 404


@app.route('/api/recordings/stale', methods=['GET'])
def api_get_stale_recordings() -> Response:
    """API endpoint to get all stale recordings."""
    stale_recordings = db.get_stale_recordings()

    formatted = []
    for rec in stale_recordings:
        start_time = db.parse_datetime_from_db(rec['start_time']) if rec['start_time'] else None
        formatted.append({
            'id': rec['id'],
            'meeting_title': rec['meeting_title'] or 'Unknown Meeting',
            'start_time': start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown',
            'file_path': rec['file_path'],
            'status': rec['status'],
            'file_exists': rec['file_exists'],
            'actual_file_size': rec['actual_file_size']
        })

    return jsonify({
        'success': True,
        'count': len(formatted),
        'stale_recordings': formatted
    })


@app.route('/api/recordings/<int:recording_id>', methods=['DELETE'])
def api_delete_recording(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to delete a recording."""
    success = db.delete_recording(recording_id)

    if success:
        return jsonify({
            'success': True,
            'message': f'Recording {recording_id} deleted successfully'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Recording not found or could not be deleted'
        }), 404


@app.route('/api/recordings/stale/cleanup', methods=['POST'])
def api_cleanup_stale_recordings() -> Response:
    """API endpoint to delete all stale recordings."""
    stale_recordings = db.get_stale_recordings()

    deleted_count = 0
    failed_count = 0
    deleted_ids = []

    for rec in stale_recordings:
        if db.delete_recording(rec['id']):
            deleted_count += 1
            deleted_ids.append(rec['id'])
        else:
            failed_count += 1

    return jsonify({
        'success': True,
        'deleted_count': deleted_count,
        'failed_count': failed_count,
        'deleted_ids': deleted_ids,
        'message': f'Deleted {deleted_count} stale recording(s)'
    })


@app.route('/api/recordings/import-vod', methods=['POST'])
def import_vod() -> Union[Response, Tuple[Response, int]]:
    """Import a video from a past council meeting (VOD).

    Request body:
        {
            "escriba_url": "https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=...",
            "override_title": "Optional custom title",
            "override_date": "Optional custom date (ISO format)"
        }

    Returns:
        {
            "success": true/false,
            "recording_id": int,
            "meeting_title": str,
            "message": str
        }
    """
    # Validate request has JSON body
    if not request.is_json:
        return jsonify({
            'success': False,
            'message': 'Request must be JSON'
        }), 400

    data = request.get_json()

    # Validate required fields
    escriba_url = data.get('escriba_url')
    if not escriba_url:
        return jsonify({
            'success': False,
            'message': 'escriba_url is required'
        }), 400

    # Get optional overrides
    override_title = data.get('override_title')
    override_date = data.get('override_date')

    # Parse override_date if provided
    override_datetime = None
    if override_date:
        try:
            override_datetime = datetime.fromisoformat(override_date.replace('Z', '+00:00'))
            # Convert to Calgary timezone if not already timezone-aware
            if override_datetime.tzinfo is None:
                override_datetime = CALGARY_TZ.localize(override_datetime)
            else:
                override_datetime = override_datetime.astimezone(CALGARY_TZ)
        except (ValueError, AttributeError) as e:
            return jsonify({
                'success': False,
                'message': f'Invalid date format. Use ISO format (e.g., 2024-04-22T11:08:00): {str(e)}'
            }), 400

    # Initialize VOD service
    vod_service = VodService()

    # Validate URL
    if not vod_service.validate_escriba_url(escriba_url):
        return jsonify({
            'success': False,
            'message': 'Invalid Escriba URL. Must be from pub-calgary.escribemeetings.com'
        }), 400

    # Extract meeting information
    try:
        meeting_info = vod_service.extract_meeting_info(escriba_url)
    except Exception as e:
        logger.error(f"Failed to extract meeting info from {escriba_url}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Failed to extract meeting information: {str(e)}'
        }), 500

    # Convert timestamp from integer to string format for folder naming
    timestamp_str = datetime.fromtimestamp(meeting_info['timestamp'], tz=CALGARY_TZ).strftime('%Y-%m-%d_%H-%M')

    # Apply overrides if provided
    if override_title:
        meeting_info['title'] = override_title
    if override_datetime:
        meeting_info['datetime'] = override_datetime
        # Update timestamp to match new datetime
        timestamp_str = override_datetime.strftime('%Y-%m-%d_%H-%M')

    # Add raw_date field required by save_meetings
    meeting_info['raw_date'] = meeting_info['datetime'].strftime('%Y-%m-%d %H:%M:%S')

    # Save meeting to database
    try:
        db.save_meetings([meeting_info])
        # Retrieve the meeting ID by finding the meeting we just saved
        saved_meeting = db.find_meeting_by_datetime(meeting_info['datetime'])
        if not saved_meeting:
            raise Exception("Failed to retrieve saved meeting from database")
        meeting_id = saved_meeting['id']
    except Exception as e:
        logger.error(f"Failed to save meeting to database: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Database error: {str(e)}'
        }), 500

    # Create output path
    output_path = os.path.join(OUTPUT_DIR, timestamp_str, 'recording.mkv')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Create recording record with 'downloading' status
    try:
        recording_id = db.create_recording(
            meeting_id=meeting_id,
            file_path=output_path,
            stream_url=escriba_url,
            start_time=meeting_info['datetime']
        )

        # Update status to 'downloading' (create_recording sets it to 'recording')
        db.update_recording(
            recording_id,
            meeting_info['datetime'],  # Use same time as end_time for now
            'downloading'
        )
    except Exception as e:
        logger.error(f"Failed to create recording record: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Database error: {str(e)}'
        }), 500

    # Download video in background thread using shared retry logic
    def download_video() -> None:
        """Background task to download the video."""
        download_vod_with_retry(recording_id, escriba_url, output_path, is_manual_retry=False)

    # Start background download thread
    thread = threading.Thread(target=download_video, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'recording_id': recording_id,
        'meeting_title': meeting_info['title'],
        'message': 'Video download started'
    })


@app.route('/api/recordings/<int:recording_id>/progress', methods=['GET'])
def get_recording_progress(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """Get download progress for a recording.

    Returns:
        {
            "success": true/false,
            "progress": int (0-100),
            "status": str,
            "message": str
        }
    """
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({
            'success': False,
            'message': 'Recording not found'
        }), 404

    return jsonify({
        'success': True,
        'progress': recording.get('download_progress', 0),
        'speed': recording.get('download_speed'),
        'status': recording['status']
    })


@app.route('/api/recordings/<int:recording_id>/retry-download', methods=['POST'])
def retry_vod_download(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """Retry downloading a failed VOD recording.

    Returns:
        {
            "success": true/false,
            "message": str
        }
    """
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({
            'success': False,
            'message': 'Recording not found'
        }), 404

    if recording['status'] not in ['failed', 'error']:
        return jsonify({
            'success': False,
            'message': f'Can only retry failed recordings. Current status: {recording["status"]}'
        }), 400

    # Get the Escriba URL from stream_url field
    escriba_url = recording.get('stream_url')
    if not escriba_url:
        return jsonify({
            'success': False,
            'message': 'No source URL found for this recording'
        }), 400

    # Initialize VOD service
    vod_service = VodService()

    # Validate URL
    if not vod_service.validate_escriba_url(escriba_url):
        return jsonify({
            'success': False,
            'message': 'Invalid Escriba URL'
        }), 400

    output_path = recording['file_path']

    # Update status to downloading
    db.update_recording(
        recording_id,
        datetime.now(CALGARY_TZ),
        'downloading',
        error_message=None
    )

    # Download video in background thread using shared retry logic
    def download_video() -> None:
        """Background task to download the video."""
        download_vod_with_retry(recording_id, escriba_url, output_path, is_manual_retry=True)

    # Start background download thread
    thread = threading.Thread(target=download_video, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Download retry started'
    })


@app.route('/api/recordings/<int:recording_id>', methods=['GET'])
def api_get_recording(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to get recording details."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    return jsonify({'success': True, 'recording': recording})


@app.route('/api/recordings/<int:recording_id>/logs', methods=['GET'])
def api_get_recording_logs(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to get recording logs."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    # Get 'since' parameter to only fetch new logs
    since_id = request.args.get('since', 0, type=int)

    # Fetch logs after the given ID
    all_logs = db.get_recording_logs(recording_id, limit=500)
    new_logs = [log for log in all_logs if log['id'] > since_id]

    return jsonify({'success': True, 'logs': new_logs})


@app.route('/api/recordings/<int:recording_id>/transcribe', methods=['POST'])
def api_transcribe_recording(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to trigger transcription for a recording or its segments."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed before transcription'}), 400

    if not os.path.exists(recording['file_path']):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    # Allow re-running transcription even if previously completed or processing
    # The transcription service will check individual step status and skip completed steps
    # This enables:
    # 1. Re-running failed steps
    # 2. Running missing steps (e.g., just diarization if Whisper already done)
    # 3. Parallel execution where steps don't depend on each other

    # Update status to 'processing' before starting thread
    db.update_transcription_status(recording_id, 'processing')

    # Run transcription in background thread
    def run_transcription() -> None:
        from transcription_service import TranscriptionService
        from config import PYANNOTE_API_TOKEN, PYANNOTE_SEGMENTATION_THRESHOLD, ENABLE_TRANSCRIPTION

        if not ENABLE_TRANSCRIPTION:
            db.update_transcription_status(recording_id, 'skipped', 'Transcription disabled in config')
            db.add_transcription_log(recording_id, 'Transcription disabled in config', 'warning')
            db.add_recording_log(recording_id, 'Transcription disabled in config', 'warning')
            return

        try:
            db.add_transcription_log(recording_id, 'Starting transcription process', 'info')
            db.add_recording_log(recording_id, 'Starting transcription process', 'info')

            transcription_service = TranscriptionService(
                pyannote_api_token=PYANNOTE_API_TOKEN,
                pyannote_segmentation_threshold=PYANNOTE_SEGMENTATION_THRESHOLD
            )

            # Transcribe the original recording
            db.add_transcription_log(recording_id, 'Transcribing original recording', 'info')
            db.add_recording_log(recording_id, 'Transcribing original recording', 'info')

            # Whisper transcription
            db.update_transcription_progress(recording_id, {'stage': 'whisper', 'step': 'loading_model'})
            db.add_transcription_log(recording_id, 'Loading Whisper model', 'info')
            db.add_recording_log(recording_id, 'Loading Whisper model', 'info')

            transcript_path = f"{recording['file_path']}.transcript.json"

            db.update_transcription_progress(recording_id, {'stage': 'whisper', 'step': 'transcribing'})
            db.add_transcription_log(recording_id, 'Running Whisper transcription', 'info')

            transcription_service.transcribe_with_speakers(
                recording['file_path'],
                output_path=transcript_path,
                save_to_file=True,
                recording_id=recording_id
            )

            db.update_recording_transcript(recording_id, transcript_path)
            db.update_transcription_status(recording_id, 'completed')
            db.add_transcription_log(recording_id, 'Transcription completed successfully', 'info')
            db.add_recording_log(recording_id, 'Transcription completed successfully', 'info')

            logger.info(f"Transcription completed for recording {recording_id}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Transcription failed for recording {recording_id}: {error_msg}", exc_info=True)
            db.update_transcription_status(recording_id, 'failed', error_msg)
            db.add_transcription_log(recording_id, f'Transcription failed: {error_msg}', 'error')
            db.add_recording_log(recording_id, f'Transcription failed: {error_msg}', 'error')

    thread = threading.Thread(target=run_transcription, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Transcription started'})


@app.route('/api/recordings/<int:recording_id>/extract-audio', methods=['POST'])
def api_extract_audio(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to extract WAV audio from recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed'}), 400

    video_path = recording['file_path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    def run_extraction() -> None:
        from transcription_service import TranscriptionService
        try:
            db.add_recording_log(recording_id, 'Starting audio extraction', 'info')
            db.update_transcription_step(recording_id, 'extraction', 'processing')

            service = TranscriptionService()
            wav_path = service.extract_audio_to_wav(video_path, recording_id=recording_id)

            db.update_wav_path(recording_id, wav_path)
            db.update_transcription_step(recording_id, 'extraction', 'completed', {'wav_path': wav_path})
            db.add_recording_log(recording_id, f'Audio extracted: {wav_path}', 'info')
            logger.info(f"Audio extraction completed for recording {recording_id}")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Audio extraction failed for recording {recording_id}: {error_msg}", exc_info=True)
            db.update_transcription_step(recording_id, 'extraction', 'failed', {'error': error_msg})
            db.add_recording_log(recording_id, f'Audio extraction failed: {error_msg}', 'error')

    thread = threading.Thread(target=run_extraction, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Audio extraction started'})


@app.route('/api/recordings/<int:recording_id>/run-diarization', methods=['POST'])
def api_run_diarization(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to run transcription + diarization (pyannote STT orchestration)."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed'}), 400

    video_path = recording['file_path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    def run_diarization() -> None:
        from transcription_service import TranscriptionService
        from config import PYANNOTE_API_TOKEN, PYANNOTE_SEGMENTATION_THRESHOLD
        try:
            db.add_recording_log(recording_id, 'Starting transcription + diarization', 'info')
            db.update_transcription_step(recording_id, 'diarization', 'processing')

            service = TranscriptionService(
                pyannote_api_token=PYANNOTE_API_TOKEN,
                pyannote_segmentation_threshold=PYANNOTE_SEGMENTATION_THRESHOLD
            )

            # Extract audio if not already done
            wav_path = recording.get('wav_path')
            if not wav_path or not os.path.exists(wav_path):
                db.add_recording_log(recording_id, 'Extracting audio first', 'info')
                wav_path = service.extract_audio_to_wav(video_path, recording_id=recording_id)
                db.update_wav_path(recording_id, wav_path)

            # Run pyannote for transcription + diarization
            diarization_segments = service.perform_diarization(wav_path, recording_id=recording_id)

            # Save diarization output
            pyannote_path = video_path + '.diarization.pyannote.json'
            pyannote_data = {
                'file': video_path,
                'segments': diarization_segments,
                'num_speakers': len(set(seg['speaker'] for seg in diarization_segments)) if diarization_segments else 0
            }
            with open(pyannote_path, 'w', encoding='utf-8') as f:
                json.dump(pyannote_data, f, indent=2, ensure_ascii=False)

            # Also save to database path
            db.update_diarization_path(recording_id, pyannote_path, source='pyannote')
            db.update_transcription_step(recording_id, 'diarization', 'completed', {'output_path': pyannote_path})
            db.add_recording_log(recording_id, f'Transcription + diarization completed: {pyannote_path}', 'info')
            logger.info(f"Transcription + diarization completed for recording {recording_id}")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Diarization failed for recording {recording_id}: {error_msg}", exc_info=True)
            db.update_transcription_step(recording_id, 'diarization', 'failed', {'error': error_msg})
            db.add_recording_log(recording_id, f'Diarization failed: {error_msg}', 'error')

    thread = threading.Thread(target=run_diarization, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Transcription + diarization started'})


@app.route('/api/recordings/<int:recording_id>/run-gemini-refinement', methods=['POST'])
def api_run_gemini_refinement(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to run only Gemini speaker refinement (requires prior diarization)."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed'}), 400

    video_path = recording['file_path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    # Verify diarization is completed (required for Gemini refinement)
    pyannote_path = video_path + '.diarization.pyannote.json'
    if not os.path.exists(pyannote_path):
        return jsonify({
            'success': False,
            'error': 'Diarization must be completed before running Gemini refinement. Run "Transcription + Diarization" step first.'
        }), 400

    def run_gemini_refinement() -> None:
        from transcription_service import TranscriptionService
        from config import ENABLE_GEMINI_REFINEMENT, GEMINI_API_KEY, GEMINI_MODEL

        # Create task ID and register with task manager
        task_id = f"gemini_refinement_{recording_id}_{int(time.time())}"
        task_manager.start_task(
            task_id=task_id,
            recording_id=recording_id,
            task_type='gemini_refinement',
            description=f'Speaker Refinement for Recording #{recording_id}'
        )

        try:
            if not ENABLE_GEMINI_REFINEMENT:
                db.add_recording_log(recording_id, 'Gemini refinement is disabled in config', 'warning')
                task_manager.complete_task(task_id, error='Gemini refinement is disabled in config')
                return

            db.add_recording_log(recording_id, 'Starting Gemini speaker refinement', 'info')
            db.update_transcription_step(recording_id, 'gemini', 'processing')
            task_manager.update_progress(task_id, 'Loading diarization data')

            # Load pyannote diarization
            with open(pyannote_path, 'r', encoding='utf-8') as f:
                pyannote_data = json.load(f)

            # Get meeting context
            meeting_link = None
            meeting_title = "Council Meeting"
            expected_speakers = []

            if recording.get('meeting_id'):
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT title, link FROM meetings WHERE id = ?",
                        (recording['meeting_id'],)
                    )
                    meeting_row = cursor.fetchone()
                    if meeting_row:
                        meeting_title = meeting_row['title'] or meeting_title
                        meeting_link = meeting_row['link']

                # Get expected speakers from database
                expected_speakers = db.get_recording_speakers(recording_id)

                # If no speakers in database, try extracting from agenda
                if not expected_speakers and meeting_link:
                    try:
                        import agenda_parser
                        expected_speakers = agenda_parser.extract_speakers(meeting_link)
                        if expected_speakers:
                            db.update_recording_speakers(recording_id, expected_speakers)
                            db.add_recording_log(recording_id, f'Extracted {len(expected_speakers)} speakers from agenda', 'info')
                    except Exception as e:
                        logger.warning(f"Could not extract speakers from agenda: {e}")

            # Call Gemini refinement
            task_manager.update_progress(task_id, f'Calling Gemini API to refine {len(pyannote_data.get("segments", []))} segments...')
            from gemini_service import refine_diarization
            gemini_transcript = refine_diarization(
                merged_transcript=pyannote_data,
                expected_speakers=expected_speakers,
                meeting_title=meeting_title,
                api_key=GEMINI_API_KEY,
                model=GEMINI_MODEL
            )

            # Check if Gemini actually refined the transcript
            if gemini_transcript.get('refined_by') != 'gemini':
                # Gemini did not refine (skipped or failed)
                error_msg = "Gemini refinement was skipped or failed to refine speakers"

                # Check for common reasons
                num_segments = len(pyannote_data.get('segments', []))
                if num_segments > 5000:
                    error_msg = f"Meeting too large for Gemini refinement ({num_segments} segments, limit is 5000). Consider implementing chunking for large meetings."
                elif not expected_speakers:
                    error_msg = "No speaker list available - Gemini needs context from meeting agenda. Fetch speakers first."

                db.add_recording_log(recording_id, error_msg, 'warning')
                db.update_transcription_step(recording_id, 'gemini', 'skipped', {'reason': error_msg})
                logger.warning(error_msg)
                task_manager.complete_task(task_id, error=error_msg)
                return  # Don't save gemini.json if not actually refined

            task_manager.update_progress(task_id, 'Saving refined transcript')

            # Save Gemini-refined transcript (only if actually refined)
            gemini_path = video_path + '.diarization.gemini.json'
            with open(gemini_path, 'w', encoding='utf-8') as f:
                json.dump(gemini_transcript, f, indent=2, ensure_ascii=False)

            # Extract unique speakers from refined transcript
            refined_speakers = set()
            for segment in gemini_transcript.get('segments', []):
                speaker = segment.get('speaker')
                if speaker and not speaker.startswith('SPEAKER_'):
                    # Only include refined speakers (not generic SPEAKER_XX)
                    refined_speakers.add(speaker)

            # Update database with refined speakers list
            if refined_speakers:
                refined_speakers_list = [
                    {
                        'name': speaker,
                        'role': speaker.split()[0] if ' ' in speaker else 'Unknown',  # Extract title (Mayor, Councillor, etc.)
                        'confidence': 'high'  # Gemini-refined speakers are high confidence
                    }
                    for speaker in sorted(refined_speakers)
                ]
                db.update_recording_speakers(recording_id, refined_speakers_list)
                db.add_recording_log(
                    recording_id,
                    f'Updated speaker list with {len(refined_speakers_list)} refined speakers: {", ".join(sorted(refined_speakers))}',
                    'info'
                )

            # Update database - set gemini path while preserving pyannote path
            db.update_recording_diarization_paths(recording_id, pyannote_path=pyannote_path, gemini_path=gemini_path)
            db.update_transcription_step(recording_id, 'gemini', 'completed', {'output_path': gemini_path})
            db.add_recording_log(recording_id, f'Gemini speaker refinement completed: {gemini_path}', 'info')
            logger.info(f"Gemini speaker refinement completed for recording {recording_id}")
            task_manager.complete_task(task_id)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Gemini refinement failed for recording {recording_id}: {error_msg}", exc_info=True)
            db.update_transcription_step(recording_id, 'gemini', 'failed', {'error': error_msg})
            db.add_recording_log(recording_id, f'Gemini refinement failed: {error_msg}', 'error')
            task_manager.complete_task(task_id, error=error_msg)

    # Generate task ID before starting thread
    task_id = f"gemini_refinement_{recording_id}_{int(time.time())}"

    # Store task_id in a way the thread can access it
    def run_with_task_id():
        nonlocal task_id
        task_manager.start_task(
            task_id=task_id,
            recording_id=recording_id,
            task_type='gemini_refinement',
            description=f'Speaker Refinement for Recording #{recording_id}'
        )
        # Move the run_gemini_refinement logic here with task_id in scope
        from transcription_service import TranscriptionService
        from config import ENABLE_GEMINI_REFINEMENT, GEMINI_API_KEY, GEMINI_MODEL

        try:
            if not ENABLE_GEMINI_REFINEMENT:
                db.add_recording_log(recording_id, 'Gemini refinement is disabled in config', 'warning')
                task_manager.complete_task(task_id, error='Gemini refinement is disabled in config')
                return

            db.add_recording_log(recording_id, 'Starting Gemini speaker refinement', 'info')
            db.update_transcription_step(recording_id, 'gemini', 'processing')
            task_manager.update_progress(task_id, 'Loading diarization data')

            # Load pyannote diarization
            with open(pyannote_path, 'r', encoding='utf-8') as f:
                pyannote_data = json.load(f)

            # Get meeting context
            meeting_link = None
            meeting_title = "Council Meeting"
            expected_speakers = []

            if recording.get('meeting_id'):
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT title, link FROM meetings WHERE id = ?",
                        (recording['meeting_id'],)
                    )
                    meeting_row = cursor.fetchone()
                    if meeting_row:
                        meeting_title = meeting_row['title'] or meeting_title
                        meeting_link = meeting_row['link']

                # Get expected speakers from database
                expected_speakers = db.get_recording_speakers(recording_id)

                # If no speakers in database, try extracting from agenda
                if not expected_speakers and meeting_link:
                    try:
                        import agenda_parser
                        expected_speakers = agenda_parser.extract_speakers(meeting_link)
                        if expected_speakers:
                            db.update_recording_speakers(recording_id, expected_speakers)
                            db.add_recording_log(recording_id, f'Extracted {len(expected_speakers)} speakers from agenda', 'info')
                    except Exception as e:
                        logger.warning(f"Could not extract speakers from agenda: {e}")

            # Call Gemini refinement
            task_manager.update_progress(task_id, f'Calling Gemini API to refine {len(pyannote_data.get("segments", []))} segments...')
            from gemini_service import refine_diarization
            gemini_transcript = refine_diarization(
                merged_transcript=pyannote_data,
                expected_speakers=expected_speakers,
                meeting_title=meeting_title,
                api_key=GEMINI_API_KEY,
                model=GEMINI_MODEL
            )

            # Check if Gemini actually refined the transcript
            if gemini_transcript.get('refined_by') != 'gemini':
                # Gemini did not refine (skipped or failed)
                error_msg = "Gemini refinement was skipped or failed to refine speakers"

                # Check for common reasons
                num_segments = len(pyannote_data.get('segments', []))
                if num_segments > 5000:
                    error_msg = f"Meeting too large for Gemini refinement ({num_segments} segments, limit is 5000). Consider implementing chunking for large meetings."
                elif not expected_speakers:
                    error_msg = "No speaker list available - Gemini needs context from meeting agenda. Fetch speakers first."

                db.add_recording_log(recording_id, error_msg, 'warning')
                db.update_transcription_step(recording_id, 'gemini', 'skipped', {'reason': error_msg})
                logger.warning(error_msg)
                task_manager.complete_task(task_id, error=error_msg)
                return  # Don't save gemini.json if not actually refined

            task_manager.update_progress(task_id, 'Saving refined transcript')

            # Save Gemini-refined transcript (only if actually refined)
            gemini_path = video_path + '.diarization.gemini.json'
            with open(gemini_path, 'w', encoding='utf-8') as f:
                json.dump(gemini_transcript, f, indent=2, ensure_ascii=False)

            # Extract unique speakers from refined transcript
            refined_speakers = set()
            for segment in gemini_transcript.get('segments', []):
                speaker = segment.get('speaker')
                if speaker and not speaker.startswith('SPEAKER_'):
                    # Only include refined speakers (not generic SPEAKER_XX)
                    refined_speakers.add(speaker)

            # Update database with refined speakers list
            if refined_speakers:
                refined_speakers_list = [
                    {
                        'name': speaker,
                        'role': speaker.split()[0] if ' ' in speaker else 'Unknown',  # Extract title (Mayor, Councillor, etc.)
                        'confidence': 'high'  # Gemini-refined speakers are high confidence
                    }
                    for speaker in sorted(refined_speakers)
                ]
                db.update_recording_speakers(recording_id, refined_speakers_list)
                db.add_recording_log(
                    recording_id,
                    f'Updated speaker list with {len(refined_speakers_list)} refined speakers: {", ".join(sorted(refined_speakers))}',
                    'info'
                )

            # Update database - set gemini path while preserving pyannote path
            db.update_recording_diarization_paths(recording_id, pyannote_path=pyannote_path, gemini_path=gemini_path)
            db.update_transcription_step(recording_id, 'gemini', 'completed', {'output_path': gemini_path})
            db.add_recording_log(recording_id, f'Gemini speaker refinement completed: {gemini_path}', 'info')
            logger.info(f"Gemini speaker refinement completed for recording {recording_id}")
            task_manager.complete_task(task_id)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Gemini refinement failed for recording {recording_id}: {error_msg}", exc_info=True)
            db.update_transcription_step(recording_id, 'gemini', 'failed', {'error': error_msg})
            db.add_recording_log(recording_id, f'Gemini refinement failed: {error_msg}', 'error')
            task_manager.complete_task(task_id, error=error_msg)

    thread = threading.Thread(target=run_with_task_id, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Gemini speaker refinement started',
        'task_id': task_id
    })


@app.route('/api/recordings/<int:recording_id>/gemini-prompt-preview', methods=['GET'])
def api_get_gemini_prompt_preview(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to preview the prompt that would be sent to Gemini for speaker refinement."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    video_path = recording['file_path']
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    # Verify diarization is completed (required for Gemini refinement)
    pyannote_path = video_path + '.diarization.pyannote.json'
    if not os.path.exists(pyannote_path):
        return jsonify({
            'success': False,
            'error': 'Diarization must be completed before previewing Gemini prompt. Run "Transcription + Diarization" step first.'
        }), 400

    try:
        # Load pyannote diarization
        with open(pyannote_path, 'r', encoding='utf-8') as f:
            pyannote_data = json.load(f)

        # Get meeting context
        meeting_link = None
        meeting_title = "Council Meeting"
        expected_speakers = []

        if recording.get('meeting_id'):
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT title, link FROM meetings WHERE id = ?",
                    (recording['meeting_id'],)
                )
                meeting_row = cursor.fetchone()
                if meeting_row:
                    meeting_title = meeting_row['title'] or meeting_title
                    meeting_link = meeting_row['link']

            # Get expected speakers from database
            expected_speakers = db.get_recording_speakers(recording_id)

            # If no speakers in database, try extracting from agenda
            if not expected_speakers and meeting_link:
                try:
                    import agenda_parser
                    expected_speakers = agenda_parser.extract_speakers(meeting_link)
                except Exception as e:
                    logger.warning(f"Could not extract speakers from agenda: {e}")

        # Construct the prompt using the same function Gemini service uses
        from gemini_service import _construct_prompt
        prompt = _construct_prompt(pyannote_data, expected_speakers, meeting_title)

        # Calculate some stats
        num_segments = len(pyannote_data.get('segments', []))
        prompt_length = len(prompt)
        estimated_tokens = prompt_length // 4  # Rough estimate

        return jsonify({
            'success': True,
            'prompt': prompt,
            'stats': {
                'num_segments': num_segments,
                'num_speakers': len(expected_speakers),
                'prompt_length_chars': prompt_length,
                'estimated_tokens': estimated_tokens
            }
        })

    except Exception as e:
        logger.error(f"Error generating prompt preview: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Failed to generate prompt preview: {str(e)}'
        }), 500


@app.route('/api/background-tasks', methods=['GET'])
def api_get_background_tasks() -> Response:
    """API endpoint to get all active and recent background tasks."""
    tasks = task_manager.get_all_tasks()
    return jsonify({
        'success': True,
        'tasks': tasks
    })


@app.route('/api/background-tasks/<task_id>', methods=['GET'])
def api_get_background_task(task_id: str) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to get a specific background task by ID."""
    tasks = task_manager.get_all_tasks()
    task = next((t for t in tasks if t['task_id'] == task_id), None)

    if not task:
        return jsonify({
            'success': False,
            'error': 'Task not found'
        }), 404

    return jsonify({
        'success': True,
        'task': task
    })


@app.route('/api/recordings/<int:recording_id>/background-tasks', methods=['GET'])
def api_get_recording_background_tasks(recording_id: int) -> Response:
    """API endpoint to get background tasks for a specific recording."""
    tasks = task_manager.get_recording_tasks(recording_id)
    return jsonify({
        'success': True,
        'tasks': tasks
    })


@app.route('/api/recordings/<int:recording_id>/transcription-status', methods=['GET'])
def api_get_transcription_status(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to get detailed transcription status with logs."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    import json

    progress = None
    if recording.get('transcription_progress'):
        try:
            progress = json.loads(recording['transcription_progress'])
        except:
            progress = None

    logs = []
    if recording.get('transcription_logs'):
        try:
            logs = json.loads(recording['transcription_logs'])
        except:
            logs = []

    # Get step-level status from file detection
    from transcription_progress import detect_transcription_progress, get_overall_status
    file_path = recording.get('file_path')
    steps = detect_transcription_progress(file_path) if file_path else {}

    # Use file-based overall status, but merge DB failure status
    # (files are the source of truth, but we need to preserve failure state)
    if steps:
        overall_status = get_overall_status(steps)
        # If no steps completed but DB shows failed, preserve the failure
        completed_count = sum(1 for step in steps.values() if step.get('status') == 'completed')
        if completed_count == 0 and recording.get('transcription_status') == 'failed':
            overall_status = 'failed'
    else:
        overall_status = recording.get('transcription_status', 'pending')

    return jsonify({
        'success': True,
        'status': overall_status,  # Use file-based status
        'error': recording.get('transcription_error'),
        'attempted_at': recording.get('transcription_attempted_at'),
        'progress': progress,
        'logs': logs,
        'steps': steps  # Add step-level information from file detection
    })


@app.route('/api/recordings/<int:recording_id>/transcription-status/reset', methods=['POST'])
def api_reset_transcription_status(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to reset transcription status to pending."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    try:
        db.update_transcription_status(recording_id, 'pending', None)
        db.add_transcription_log(recording_id, 'Transcription status manually reset to pending', 'info')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/recordings/<int:recording_id>/transcription/reset-step', methods=['POST'])
def api_reset_transcription_step(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to reset a specific transcription step.

    Only allows resetting the latest completed step to maintain consistency.
    """
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    file_path = recording.get('file_path')
    if not file_path:
        return jsonify({'success': False, 'error': 'Recording has no file path'}), 400

    import json
    data = request.get_json() or {}
    step_name = data.get('step')

    if not step_name:
        return jsonify({'success': False, 'error': 'Step name required'}), 400

    from transcription_progress import (
        get_latest_completed_step,
        reset_step,
        get_dependent_steps,
        detect_transcription_progress
    )

    # Only allow resetting the latest completed step
    latest_step = get_latest_completed_step(file_path)

    if not latest_step:
        return jsonify({'success': False, 'error': 'No completed steps to reset'}), 400

    if step_name != latest_step:
        return jsonify({
            'success': False,
            'error': f'Can only reset the latest completed step: {latest_step}'
        }), 400

    # Reset the step
    success = reset_step(file_path, step_name)

    if not success:
        return jsonify({'success': False, 'error': 'Failed to reset step'}), 500

    # Log the reset action
    db.add_transcription_log(
        recording_id,
        f'Step "{step_name}" reset by user - will be re-run on next transcription',
        'info'
    )
    db.add_recording_log(
        recording_id,
        f'Transcription step "{step_name}" reset',
        'info'
    )

    # Get updated status
    steps = detect_transcription_progress(file_path)
    dependent_steps = get_dependent_steps(step_name)

    return jsonify({
        'success': True,
        'message': f'Step "{step_name}" has been reset',
        'steps': steps,
        'dependent_steps': dependent_steps
    })


@app.route('/api/recordings/<int:recording_id>/transcription/run-step', methods=['POST'])
def api_run_transcription_step(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to run a specific transcription step.

    Validates dependencies are met before running the step.
    """
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    file_path = recording.get('file_path')
    if not file_path:
        return jsonify({'success': False, 'error': 'Recording has no file path'}), 400

    import json
    data = request.get_json() or {}
    step_name = data.get('step')

    if not step_name:
        return jsonify({'success': False, 'error': 'Step name required'}), 400

    from transcription_progress import can_run_step, get_step_dependencies

    # Check if step can be run
    can_run, reason = can_run_step(file_path, step_name)

    if not can_run:
        return jsonify({
            'success': False,
            'error': reason,
            'dependencies': get_step_dependencies(step_name)
        }), 400

    # Log the action
    db.add_transcription_log(
        recording_id,
        f'User requested to run step: {step_name}',
        'info'
    )

    # Run transcription (it will execute only the requested step since others are complete)
    # This reuses the existing transcription endpoint
    return jsonify({
        'success': True,
        'message': f'Starting step: {step_name}',
        'redirect': f'/api/recordings/{recording_id}/transcribe'
    })


@app.route('/api/recordings/<int:recording_id>/speakers', methods=['GET'])
def api_get_recording_speakers(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to get speaker list for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    speakers = db.get_recording_speakers(recording_id)

    return jsonify({
        'success': True,
        'speakers': speakers
    })


@app.route('/api/recordings/<int:recording_id>/speakers/fetch', methods=['POST'])
def api_fetch_recording_speakers(recording_id: int) -> Union[Response, Tuple[Response, int]]:
    """API endpoint to fetch speaker list from meeting agenda."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    # Get the meeting link
    meeting_id = recording.get('meeting_id')
    if not meeting_id:
        return jsonify({'success': False, 'error': 'No meeting associated with this recording'}), 400

    # Get meeting details
    meeting = db.get_upcoming_meetings(limit=1000)  # Get all meetings
    meeting_link = None
    for m in meeting:
        if m['id'] == meeting_id:
            meeting_link = m.get('link')
            break

    # Also check past meetings
    if not meeting_link:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT link FROM meetings WHERE id = ?", (meeting_id,))
            row = cursor.fetchone()
            if row:
                meeting_link = row['link']

    if not meeting_link:
        return jsonify({'success': False, 'error': 'No meeting agenda link available'}), 400

    try:
        # Extract speakers from agenda
        import agenda_parser
        speakers = agenda_parser.extract_speakers(meeting_link)

        if speakers:
            # Save to database
            db.update_recording_speakers(recording_id, speakers)
            return jsonify({
                'success': True,
                'message': f'Found {len(speakers)} speakers from meeting agenda',
                'speakers': speakers
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No speakers found in the meeting agenda'
            }), 404

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to fetch speakers: {str(e)}'
        }), 500


# Error handlers for custom exceptions
@app.errorhandler(RecordingStorageError)
def handle_storage_error(error: RecordingStorageError) -> Tuple[Response, int]:
    """Handle recording storage errors."""
    logger.error(f"Storage error: {error.message}", exc_info=True)
    return jsonify({
        'success': False,
        'error': error.message,
        'type': 'storage_error'
    }), 500


@app.errorhandler(TranscriptionError)
def handle_transcription_error(error: TranscriptionError) -> Tuple[Response, int]:
    """Handle transcription errors."""
    logger.error(f"Transcription error: {error.message}", exc_info=True)
    return jsonify({
        'success': False,
        'error': error.message,
        'type': 'transcription_error'
    }), 500


@app.errorhandler(DatabaseError)
def handle_database_error(error: DatabaseError) -> Tuple[Response, int]:
    """Handle database errors."""
    logger.error(f"Database error: {error.message}", exc_info=True)
    return jsonify({
        'success': False,
        'error': error.message,
        'type': 'database_error'
    }), 500


@app.errorhandler(CouncilRecorderError)
def handle_council_recorder_error(error: CouncilRecorderError) -> Tuple[Response, int]:
    """Handle all other council recorder errors."""
    logger.error(f"Council recorder error: {error.message}", exc_info=True)
    return jsonify({
        'success': False,
        'error': error.message,
        'type': 'application_error'
    }), 500


def run_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Run the Flask web server."""
    host = host or WEB_HOST
    port = port or WEB_PORT
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    # Initialize post-processor if running standalone
    if post_processor_service is None:
        from config import POST_PROCESS_SILENCE_THRESHOLD_DB, POST_PROCESS_MIN_SILENCE_DURATION
        post_processor_service = PostProcessor(
            silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
            min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION
        )
        logger.info("Initialized post-processor service")

    logger.info(f"Starting web server on http://{WEB_HOST}:{WEB_PORT}")
    run_server()
