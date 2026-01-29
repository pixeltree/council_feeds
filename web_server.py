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
from shared_state import monitoring_state

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


@app.route('/recording/<int:recording_id>')
def recording_detail(recording_id):
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
        'is_segmented': recording['is_segmented'],
        'has_transcript': bool(recording['transcript_path']),
        'transcript_path': recording['transcript_path'],
        'file_path': recording['file_path'],
        'post_process_status': recording.get('post_process_status'),
        'post_process_error': recording.get('post_process_error'),
        'diarization_pyannote_path': recording.get('diarization_pyannote_path'),
        'diarization_gemini_path': recording.get('diarization_gemini_path')
    }

    # Get segments
    segments = db.get_segments_by_recording(recording_id)

    # Add diarization file existence checks for each segment
    for segment in segments:
        if segment.get('file_path'):
            file_path = segment['file_path']
            segment['has_diarization_pyannote'] = os.path.exists(file_path + '.diarization.pyannote.json')
            segment['has_diarization_gemini'] = os.path.exists(file_path + '.diarization.gemini.json')
            # Check legacy format too
            segment['has_diarization_legacy'] = os.path.exists(file_path + '.diarization.json')
            segment['has_any_diarization'] = (
                segment['has_diarization_pyannote'] or
                segment['has_diarization_gemini'] or
                segment['has_diarization_legacy']
            )
        else:
            segment['has_diarization_pyannote'] = False
            segment['has_diarization_gemini'] = False
            segment['has_diarization_legacy'] = False
            segment['has_any_diarization'] = False

    # Get logs in reverse chronological order
    logs = db.get_recording_logs(recording_id, limit=200)

    return render_template('recording_detail.html', recording=formatted_recording, segments=segments, logs=logs)


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


@app.route('/api/monitoring/start', methods=['POST'])
def api_start_monitoring():
    """API endpoint to start monitoring."""
    monitoring_state.enable()
    return jsonify({
        'success': True,
        'message': 'Monitoring started'
    })


@app.route('/api/monitoring/stop', methods=['POST'])
def api_stop_monitoring():
    """API endpoint to stop monitoring."""
    monitoring_state.disable()
    return jsonify({
        'success': True,
        'message': 'Monitoring stopped'
    })


@app.route('/api/monitoring/status', methods=['GET'])
def api_monitoring_status():
    """API endpoint to get monitoring status."""
    return jsonify({
        'monitoring_enabled': monitoring_state.enabled
    })


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

    # Update status to 'processing' before starting thread to prevent race condition
    db.update_post_process_status(recording_id, 'processing', None)

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


@app.route('/download/diarization/<int:recording_id>')
def download_recording_diarization(recording_id):
    """Download diarization data (prefers Gemini-refined, falls back to pyannote)."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    # Try Gemini-refined first
    gemini_path = recording.get('diarization_gemini_path')
    if gemini_path and os.path.exists(gemini_path):
        print(f"[WEB] Serving gemini diarization for recording {recording_id}")
        return send_file(gemini_path, as_attachment=True)

    # Fall back to pyannote
    pyannote_path = recording.get('diarization_pyannote_path')
    if pyannote_path and os.path.exists(pyannote_path):
        print(f"[WEB] Serving pyannote diarization for recording {recording_id}")
        return send_file(pyannote_path, as_attachment=True)

    # Fall back to legacy path
    file_path = recording.get('file_path')
    if file_path:
        legacy_path = file_path + '.diarization.json'
        if os.path.exists(legacy_path):
            print(f"[WEB] Serving legacy diarization for recording {recording_id}")
            return send_file(legacy_path, as_attachment=True)

    print(f"[WEB] Diarization file not found for recording {recording_id}")
    return "Diarization file not found", 404


@app.route('/download/diarization/pyannote/<int:recording_id>')
def download_recording_diarization_pyannote(recording_id):
    """Download pyannote diarization data for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    pyannote_path = recording.get('diarization_pyannote_path')
    if pyannote_path and os.path.exists(pyannote_path):
        print(f"[WEB] Serving pyannote diarization for recording {recording_id}")
        return send_file(pyannote_path, as_attachment=True)

    # Fall back to trying file_path based path
    file_path = recording.get('file_path')
    if file_path:
        fallback_path = file_path + '.diarization.pyannote.json'
        if os.path.exists(fallback_path):
            return send_file(fallback_path, as_attachment=True)

    print(f"[WEB] Pyannote diarization file not found for recording {recording_id}")
    return "Pyannote diarization file not found", 404


@app.route('/download/diarization/gemini/<int:recording_id>')
def download_recording_diarization_gemini(recording_id):
    """Download Gemini-refined diarization data for a recording."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return "Recording not found", 404

    gemini_path = recording.get('diarization_gemini_path')
    if gemini_path and os.path.exists(gemini_path):
        print(f"[WEB] Serving gemini diarization for recording {recording_id}")
        return send_file(gemini_path, as_attachment=True)

    # Fall back to trying file_path based path
    file_path = recording.get('file_path')
    if file_path:
        fallback_path = file_path + '.diarization.gemini.json'
        if os.path.exists(fallback_path):
            return send_file(fallback_path, as_attachment=True)

    print(f"[WEB] Gemini diarization file not found for recording {recording_id}")
    return "Gemini diarization file not found", 404


@app.route('/download/diarization/segment/<int:segment_id>')
def download_segment_diarization(segment_id):
    """Download diarization data for a segment (prefers Gemini, falls back to pyannote)."""
    conn = db.get_db_connection()

    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM segments WHERE id = ?", (segment_id,))
        row = cursor.fetchone()

        if not row or not row['file_path']:
            return "Segment not found", 404

        file_path = row['file_path']

        # Try Gemini first
        gemini_path = file_path + '.diarization.gemini.json'
        if os.path.exists(gemini_path):
            return send_file(gemini_path, as_attachment=True)

        # Try pyannote
        pyannote_path = file_path + '.diarization.pyannote.json'
        if os.path.exists(pyannote_path):
            return send_file(pyannote_path, as_attachment=True)

        # Fall back to legacy
        legacy_path = file_path + '.diarization.json'
        if os.path.exists(legacy_path):
            return send_file(legacy_path, as_attachment=True)

        return "Diarization file not found", 404


@app.route('/download/diarization/pyannote/segment/<int:segment_id>')
def download_segment_diarization_pyannote(segment_id):
    """Download pyannote diarization data for a segment."""
    conn = db.get_db_connection()

    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM segments WHERE id = ?", (segment_id,))
        row = cursor.fetchone()

        if not row or not row['file_path']:
            return "Segment not found", 404

        file_path = row['file_path']
        pyannote_path = file_path + '.diarization.pyannote.json'

        if os.path.exists(pyannote_path):
            return send_file(pyannote_path, as_attachment=True)

        return "Pyannote diarization file not found", 404


@app.route('/download/diarization/gemini/segment/<int:segment_id>')
def download_segment_diarization_gemini(segment_id):
    """Download Gemini-refined diarization data for a segment."""
    conn = db.get_db_connection()

    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM segments WHERE id = ?", (segment_id,))
        row = cursor.fetchone()

        if not row or not row['file_path']:
            return "Segment not found", 404

        file_path = row['file_path']
        gemini_path = file_path + '.diarization.gemini.json'

        if os.path.exists(gemini_path):
            return send_file(gemini_path, as_attachment=True)

        return "Gemini diarization file not found", 404


@app.route('/api/recordings/stale', methods=['GET'])
def api_get_stale_recordings():
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
def api_delete_recording(recording_id):
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
def api_cleanup_stale_recordings():
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


@app.route('/api/recordings/<int:recording_id>/transcribe', methods=['POST'])
def api_transcribe_recording(recording_id):
    """API endpoint to trigger transcription for a recording or its segments."""
    recording = db.get_recording_by_id(recording_id)

    if not recording:
        return jsonify({'success': False, 'error': 'Recording not found'}), 404

    if recording['status'] != 'completed':
        return jsonify({'success': False, 'error': 'Recording must be completed before transcription'}), 400

    # Check if already transcribing
    if recording.get('transcription_status') == 'processing':
        return jsonify({'success': False, 'error': 'Recording is already being transcribed'}), 400

    if not os.path.exists(recording['file_path']):
        return jsonify({'success': False, 'error': 'Recording file not found'}), 404

    # Update status to 'processing' before starting thread to prevent race condition
    db.update_transcription_status(recording_id, 'processing')

    # Run transcription in background thread
    def run_transcription():
        from transcription_service import TranscriptionService
        from config import PYANNOTE_API_TOKEN, ENABLE_TRANSCRIPTION

        if not ENABLE_TRANSCRIPTION:
            db.update_transcription_status(recording_id, 'skipped', 'Transcription disabled in config')
            db.add_transcription_log(recording_id, 'Transcription disabled in config', 'warning')
            db.add_recording_log(recording_id, 'Transcription disabled in config', 'warning')
            return

        try:
            db.add_transcription_log(recording_id, 'Starting transcription process', 'info')
            db.add_recording_log(recording_id, 'Starting transcription process', 'info')

            transcription_service = TranscriptionService(pyannote_api_token=PYANNOTE_API_TOKEN)

            # Check if recording has segments
            segments = db.get_segments_by_recording(recording_id)

            if segments and recording['is_segmented']:
                # Transcribe each segment
                db.add_transcription_log(recording_id, f'Found {len(segments)} segments to transcribe', 'info')
                db.add_recording_log(recording_id, f'Found {len(segments)} segments to transcribe', 'info')
                db.update_transcription_progress(recording_id, {'stage': 'segments', 'total': len(segments), 'current': 0})

                for idx, segment in enumerate(segments, 1):
                    if not os.path.exists(segment['file_path']):
                        db.add_transcription_log(recording_id, f"Segment file not found: {segment['file_path']}", 'error')
                        db.add_recording_log(recording_id, f"Segment file not found: {segment['file_path']}", 'error')
                        continue

                    db.add_transcription_log(recording_id, f"Transcribing segment {idx}/{len(segments)}", 'info')
                    db.add_recording_log(recording_id, f"Transcribing segment {idx}/{len(segments)}", 'info')
                    db.update_transcription_progress(recording_id, {'stage': 'segments', 'total': len(segments), 'current': idx})

                    try:
                        # Whisper transcription
                        db.update_transcription_progress(recording_id, {'stage': 'whisper', 'segment': idx, 'total': len(segments)})
                        db.add_transcription_log(recording_id, f"Segment {idx}: Running Whisper transcription", 'info')

                        transcript_path = f"{segment['file_path']}.transcript.json"
                        transcription_service.transcribe_with_speakers(
                            segment['file_path'],
                            output_path=transcript_path,
                            save_to_file=True,
                            recording_id=recording_id,
                            segment_number=idx
                        )
                        db.update_segment_transcript(segment['id'], transcript_path)
                        db.add_transcription_log(recording_id, f"Segment {idx}: Completed successfully", 'info')
                        db.add_recording_log(recording_id, f"Segment {idx}: Completed successfully", 'info')
                    except Exception as seg_error:
                        db.add_transcription_log(recording_id, f"Segment {idx} failed: {str(seg_error)}", 'error')
                        db.add_recording_log(recording_id, f"Segment {idx} failed: {str(seg_error)}", 'error')

                db.update_transcription_status(recording_id, 'completed')
                db.add_transcription_log(recording_id, 'All segments transcribed successfully', 'info')
                db.add_recording_log(recording_id, 'All segments transcribed successfully', 'info')
            else:
                # Transcribe the original recording
                db.add_transcription_log(recording_id, 'Transcribing original recording (no segments)', 'info')
                db.add_recording_log(recording_id, 'Transcribing original recording (no segments)', 'info')

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

            print(f"Transcription completed for recording {recording_id}")

        except Exception as e:
            error_msg = str(e)
            print(f"Transcription failed for recording {recording_id}: {error_msg}")
            db.update_transcription_status(recording_id, 'failed', error_msg)
            db.add_transcription_log(recording_id, f'Transcription failed: {error_msg}', 'error')
            db.add_recording_log(recording_id, f'Transcription failed: {error_msg}', 'error')

    thread = threading.Thread(target=run_transcription, daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': 'Transcription started'})


@app.route('/api/recordings/<int:recording_id>/transcription-status', methods=['GET'])
def api_get_transcription_status(recording_id):
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

    # Use file-based overall status instead of database status
    # (files are the source of truth)
    overall_status = get_overall_status(steps) if steps else recording.get('transcription_status', 'pending')

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
def api_reset_transcription_status(recording_id):
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
def api_reset_transcription_step(recording_id):
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
def api_run_transcription_step(recording_id):
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
def api_get_recording_speakers(recording_id):
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
def api_fetch_recording_speakers(recording_id):
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


def run_server(host=None, port=None):
    """Run the Flask web server."""
    host = host or WEB_HOST
    port = port or WEB_PORT
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    print(f"Starting web server on http://{WEB_HOST}:{WEB_PORT}")
    run_server()
