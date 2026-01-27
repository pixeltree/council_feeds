#!/usr/bin/env python3
"""
Web server module for Calgary Council Stream Recorder.
Provides a simple web interface to view recording status and upcoming meetings.
"""

from flask import Flask, render_template_string, jsonify
import database as db
from datetime import datetime
import pytz
import os

app = Flask(__name__)

CALGARY_TZ = pytz.timezone('America/Edmonton')

# HTML template for the status page
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Calgary Council Stream Recorder</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        .header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .header h1 {
            color: #2d3748;
            font-size: 2em;
            margin-bottom: 10px;
        }

        .header p {
            color: #718096;
            font-size: 1.1em;
        }

        .card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        .card h2 {
            color: #2d3748;
            font-size: 1.5em;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e2e8f0;
        }

        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9em;
        }

        .status-recording {
            background: #fed7d7;
            color: #c53030;
        }

        .status-idle {
            background: #c6f6d5;
            color: #2f855a;
        }

        .pulse {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }

        .pulse-red {
            background: #c53030;
        }

        .pulse-green {
            background: #2f855a;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }

        .stat-box {
            background: #f7fafc;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }

        .stat-label {
            color: #718096;
            font-size: 0.85em;
            margin-bottom: 5px;
        }

        .stat-value {
            color: #2d3748;
            font-size: 1.8em;
            font-weight: 700;
        }

        .meeting-list {
            list-style: none;
        }

        .meeting-item {
            padding: 15px;
            margin-bottom: 10px;
            background: #f7fafc;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }

        .meeting-title {
            color: #2d3748;
            font-weight: 600;
            margin-bottom: 5px;
        }

        .meeting-time {
            color: #718096;
            font-size: 0.9em;
        }

        .recording-item {
            padding: 15px;
            margin-bottom: 10px;
            background: #f7fafc;
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .recording-info {
            flex: 1;
        }

        .recording-title {
            color: #2d3748;
            font-weight: 600;
            margin-bottom: 5px;
        }

        .recording-details {
            color: #718096;
            font-size: 0.85em;
        }

        .recording-status {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }

        .status-completed {
            background: #c6f6d5;
            color: #2f855a;
        }

        .status-failed {
            background: #fed7d7;
            color: #c53030;
        }

        .status-recording-item {
            background: #feebc8;
            color: #c05621;
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #718096;
        }

        .refresh-info {
            text-align: right;
            color: #718096;
            font-size: 0.85em;
            margin-top: 10px;
        }

        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.5em;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
    <script>
        // Auto-refresh every 10 seconds
        setTimeout(() => location.reload(), 10000);
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Calgary Council Stream Recorder</h1>
            <p>Real-time monitoring and recording of Calgary City Council meetings</p>
        </div>

        <div class="card">
            <h2>Current Status</h2>
            {% if current_recording %}
                <div class="status-indicator status-recording">
                    <span class="pulse pulse-red"></span>
                    RECORDING IN PROGRESS
                </div>
                <div class="stats-grid">
                    <div class="stat-box">
                        <div class="stat-label">Recording Since</div>
                        <div class="stat-value" style="font-size: 1.2em;">{{ current_recording.start_time }}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Meeting</div>
                        <div class="stat-value" style="font-size: 1em;">{{ current_recording.meeting_title or 'Unscheduled' }}</div>
                    </div>
                </div>
            {% else %}
                <div class="status-indicator status-idle">
                    <span class="pulse pulse-green"></span>
                    MONITORING
                </div>
                <p style="margin-top: 15px; color: #718096;">System is actively monitoring for live streams</p>
            {% endif %}
        </div>

        <div class="card">
            <h2>Recording Statistics</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">Total Recordings</div>
                    <div class="stat-value">{{ stats.total_recordings }}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Completed</div>
                    <div class="stat-value">{{ stats.completed }}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value">{{ stats.failed }}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Total Size</div>
                    <div class="stat-value">{{ stats.total_size_gb }} GB</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Upcoming Meetings</h2>
            {% if meetings %}
                <ul class="meeting-list">
                    {% for meeting in meetings %}
                    <li class="meeting-item">
                        <div class="meeting-title">{{ meeting.title }}</div>
                        <div class="meeting-time">{{ meeting.raw_date }}</div>
                    </li>
                    {% endfor %}
                </ul>
            {% else %}
                <div class="empty-state">
                    <p>No upcoming meetings scheduled</p>
                </div>
            {% endif %}
        </div>

        <div class="card">
            <h2>Recent Recordings</h2>
            {% if recordings %}
                {% for recording in recordings %}
                <div class="recording-item">
                    <div class="recording-info">
                        <div class="recording-title">{{ recording.meeting_title or 'Council Meeting' }}</div>
                        <div class="recording-details">
                            {{ recording.start_time }}
                            {% if recording.duration_seconds %}
                                • Duration: {{ recording.duration_minutes }} min
                            {% endif %}
                            {% if recording.file_size_mb %}
                                • Size: {{ recording.file_size_mb }} MB
                            {% endif %}
                        </div>
                    </div>
                    <span class="recording-status status-{{ recording.status }}">
                        {{ recording.status.upper() }}
                    </span>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state">
                    <p>No recordings yet</p>
                </div>
            {% endif %}
        </div>

        <div class="refresh-info">
            Page auto-refreshes every 10 seconds • Last updated: {{ now }}
        </div>
    </div>
</body>
</html>
"""


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
            'status': rec['status']
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

    return render_template_string(
        HTML_TEMPLATE,
        current_recording=current_recording,
        stats=stats,
        meetings=meetings,
        recordings=formatted_recordings,
        now=now
    )


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


def run_server(host='0.0.0.0', port=5000):
    """Run the Flask web server."""
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    print("Starting web server on http://0.0.0.0:5000")
    run_server()
