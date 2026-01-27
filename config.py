#!/usr/bin/env python3
"""
Configuration module for Calgary Council Stream Recorder.
Centralizes all configuration values for easier testing and maintenance.
"""

import os
import pytz

# Timezone
CALGARY_TZ = pytz.timezone('America/Edmonton')

# API endpoints
STREAM_PAGE_URL = "https://video.isilive.ca/play/calgarycc/live"
COUNCIL_CALENDAR_API = "https://data.calgary.ca/resource/23m4-i42g.json"

# Polling intervals (in seconds)
ACTIVE_CHECK_INTERVAL = 30  # Check every 30 seconds during meeting windows
IDLE_CHECK_INTERVAL = 1800  # Check every 30 minutes outside meeting windows

# Directory paths
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./recordings")
DB_DIR = os.getenv("DB_DIR", "./data")
DB_PATH = os.path.join(DB_DIR, "council_feeds.db")

# Recording settings
MAX_RETRIES = 3

# Meeting window settings
from datetime import timedelta
MEETING_BUFFER_BEFORE = timedelta(minutes=5)
MEETING_BUFFER_AFTER = timedelta(hours=6)

# Stream URL patterns to try
STREAM_URL_PATTERNS = [
    "https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8",
    "https://lin12.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/_definst_/calgarycc/live/playlist.m3u8",
]

# Web server settings
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

# External command settings
FFMPEG_COMMAND = os.getenv("FFMPEG_COMMAND", "ffmpeg")
YTDLP_COMMAND = os.getenv("YTDLP_COMMAND", "yt-dlp")

# Post-processing settings (experimental)
ENABLE_POST_PROCESSING = os.getenv("ENABLE_POST_PROCESSING", "false").lower() == "true"
POST_PROCESS_SILENCE_THRESHOLD_DB = int(os.getenv("POST_PROCESS_SILENCE_THRESHOLD_DB", "-40"))
POST_PROCESS_MIN_SILENCE_DURATION = int(os.getenv("POST_PROCESS_MIN_SILENCE_DURATION", "120"))  # seconds

# Transcription settings
ENABLE_TRANSCRIPTION = os.getenv("ENABLE_TRANSCRIPTION", "false").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # tiny, base, small, medium, large
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN", None)  # Required for speaker diarization

# Recording resilience settings
RECORDING_FORMAT = os.getenv("RECORDING_FORMAT", "mkv")  # mkv (safest), mp4, or ts
ENABLE_SEGMENTED_RECORDING = os.getenv("ENABLE_SEGMENTED_RECORDING", "true").lower() == "true"
SEGMENT_DURATION = int(os.getenv("SEGMENT_DURATION", "900"))  # 15 minutes in seconds
RECORDING_RECONNECT = os.getenv("RECORDING_RECONNECT", "true").lower() == "true"  # Auto-reconnect on stream issues
