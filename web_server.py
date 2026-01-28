#!/usr/bin/env python3
"""
Web server module for Calgary Council Stream Recorder.
Provides a simple web interface to view recording status and upcoming meetings.
"""

from flask import Flask, render_template, jsonify, send_file, request
import database as db
from datetime import datetime
from config import CALGARY_TZ, WEB_HOST, WEB_PORT
import os
from post_processor import PostProcessor
import threading

app = Flask(__name__)

# Global reference to recording service (set by main.py)
recording_service = None

def set_recording_service(service):
    """Set the recording service instance for the web server to use."""
    global recording_service
    recording_service = service


def get_current_recording():
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


def format_recordings(recordings):
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
def index():
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

    # Current time
    now = datetime.now(CALGARY_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')

    return render_template(
        'index.html',
        current_recording=current_recording,
        stats=stats,
        meetings=meetings,
        recordings=formatted_recordings,
        now=now
    )


@app.route('/recordings')
def recordings_list():
    """Recordings list page with segments."""
    recordings = db.get_recent_recordings(limit=50)

    # Format recordings with segment info
    formatted_recordings = []
    for rec in recordings:
        start_time = db.parse_datetime_from_db(rec['start_time']) if rec['start_time'] else None

        # Get segments for this recording
        segments = db.get_segments_by_recording(rec['id'])

        formatted_recordings.append({
            'id': rec['id'],
            'meeting_title': rec['meeting_title'] or 'Council Meeting',
            'start_time': start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'Unknown',
            'duration_minutes': round(rec['duration_seconds'] / 60) if rec['duration_seconds'] else None,
            'file_size_mb': round(rec['file_size_bytes'] / (1024**2), 1) if rec['file_size_bytes'] else None,
            'status': rec['status'],
            'is_segmented': rec['is_segmented'],
            'has_transcript': bool(rec['transcript_path']),
            'transcript_path': rec['transcript_path'],
            'file_path': rec['file_path'],
            'post_process_status': rec.get('post_process_status'),
            'post_process_error': rec.get('post_process_error'),
            'segments': segments
        })

    return render_template('recordings.html', recordings=formatted_recordings)


@app.route('/api/status')
def api_status():
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
def api_stop_recording():
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


@app.route('/api/refresh-agenda', methods=['POST'])
def api_refresh_agenda():
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


@app.route('/api/recordings/<int:recording_id>/process', methods=['POST'])
def process_recording(recording_id):
    """Trigger post-processing for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed before processing'}), 400

    # Check if already processing
    if recording.get('post_process_status') == 'processing':
        return jsonify({'success': False, 'error': 'Recording is already being processed'}), 400

    if not os.path.exists(recording['file_path']):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    # Run post-processing in background thread
    def run_processing():
        processor = PostProcessor()
        result = processor.process_recording(recording['file_path'], recording_id)
        print(f"Post-processing result for recording {recording_id}: {result}")

    thread = threading.Thread(target=run_processing, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Post-processing started'})


@app.route('/api/recordings/<int:recording_id>/segment', methods=['POST'])
def segment_recording(recording_id):
    """Trigger segmentation for a recording (legacy endpoint - use /process instead)."""
    # Redirect to the new process endpoint
    return process_recording(recording_id)


@app.route('/download/transcript/<int:recording_id>')
def download_recording_transcript(recording_id):
    """Download transcript for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording or not recording['transcript_path']:
        return "Transcript not found", 404

    if not os.path.exists(recording['transcript_path']):
        return "Transcript file not found", 404

    return send_file(recording['transcript_path'], as_attachment=True)


@app.route('/download/transcript/segment/<int:segment_id>')
def download_segment_transcript(segment_id):
    """Download transcript for a segment."""
    segments = db.get_db_connection()

    with segments as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT transcript_path FROM segments WHERE id = ?", (segment_id,))
        row = cursor.fetchone()

        if not row or not row['transcript_path']:
            return "Transcript not found", 404

        transcript_path = row['transcript_path']

        if not os.path.exists(transcript_path):
            return "Transcript file not found", 404

        return send_file(transcript_path, as_attachment=True)


def run_server(host=None, port=None):
    """Run the Flask web server."""
    host = host or WEB_HOST
    port = port or WEB_PORT
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    print(f"Starting web server on http://{WEB_HOST}:{WEB_PORT}")
    run_server()
