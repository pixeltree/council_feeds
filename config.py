#!/usr/bin/env python3
"""
Configuration module for Calgary Council Stream Recorder.
Centralizes all configuration values for easier testing and maintenance.
"""

import os
import logging
import pytz
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

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

# Room definitions
COUNCIL_CHAMBER = "Council Chamber"
ENGINEERING_TRADITIONS_ROOM = "Engineering Traditions Room"

# Stream URL patterns by room
STREAM_URLS_BY_ROOM = {
    COUNCIL_CHAMBER: [
        "https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8",
        "https://lin12.isilive.ca/live/calgarycc/live/playlist.m3u8",
        "https://video.isilive.ca/live/calgarycc/live/playlist.m3u8",
        "https://video.isilive.ca/live/_definst_/calgarycc/live/playlist.m3u8",
    ],
    ENGINEERING_TRADITIONS_ROOM: [
        "https://temp2.isilive.ca/live/calgary/legislative/chunklist.m3u8",
        "https://temp2.isilive.ca/live/calgary/legislative/index.m3u8",
    ]
}

# Legacy stream URL patterns (for backward compatibility)
STREAM_URL_PATTERNS = [
    "https://temp2.isilive.ca/live/calgary/legislative/chunklist.m3u8",
    "https://temp2.isilive.ca/live/calgary/legislative/index.m3u8",
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

# Audio detection thresholds (used for static detection)
AUDIO_DETECTION_MEAN_THRESHOLD_DB = -50  # Mean volume threshold for detecting silence
AUDIO_DETECTION_MAX_THRESHOLD_DB = -30  # Max volume threshold for detecting silence

# Transcription settings
ENABLE_TRANSCRIPTION = os.getenv("ENABLE_TRANSCRIPTION", "false").lower() == "true"
PYANNOTE_API_TOKEN = os.getenv("PYANNOTE_API_TOKEN", None)  # Required for transcription + diarization
PYANNOTE_SEGMENTATION_THRESHOLD = float(os.getenv("PYANNOTE_SEGMENTATION_THRESHOLD", "0.3"))  # Lower = more speakers (0.1-0.9)
TRANSCRIPTION_LANGUAGE = os.getenv("TRANSCRIPTION_LANGUAGE", "en")  # Language code for transcription (default: English)
# TODO: When pyannote.ai adds multi-language support, pass this to the API

# Recording resilience settings
RECORDING_FORMAT = os.getenv("RECORDING_FORMAT", "mkv")  # mkv (safest), mp4, or ts
ENABLE_SEGMENTED_RECORDING = os.getenv("ENABLE_SEGMENTED_RECORDING", "true").lower() == "true"
SEGMENT_DURATION = int(os.getenv("SEGMENT_DURATION", "900"))  # 15 minutes in seconds
RECORDING_RECONNECT = os.getenv("RECORDING_RECONNECT", "true").lower() == "true"  # Auto-reconnect on stream issues

# Static stream detection settings (prevents recording placeholder/static images)
ENABLE_STATIC_DETECTION = os.getenv("ENABLE_STATIC_DETECTION", "true").lower() == "true"
STATIC_MIN_GROWTH_KB = int(os.getenv("STATIC_MIN_GROWTH_KB", "10"))  # Minimum KB growth per check
STATIC_CHECK_INTERVAL = int(os.getenv("STATIC_CHECK_INTERVAL", "30"))  # Seconds between checks
STATIC_MAX_FAILURES = int(os.getenv("STATIC_MAX_FAILURES", "3"))  # Consecutive failures before stopping
STATIC_SCENE_THRESHOLD = int(os.getenv("STATIC_SCENE_THRESHOLD", "200"))  # Minimum scene changes for active content

# Gemini API settings (for speaker diarization refinement)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", None)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
ENABLE_GEMINI_REFINEMENT = (
    os.getenv("ENABLE_GEMINI_REFINEMENT", "true").lower() == "true"
    and GEMINI_API_KEY is not None
)


@dataclass
class AppConfig:
    """
    Type-safe configuration with validation.

    This dataclass provides a validated, type-safe interface to the application
    configuration. It ensures all required settings are present and valid before
    the application starts.
    """

    # API endpoints
    stream_page_url: str
    council_calendar_api: str

    # Polling intervals (in seconds)
    active_check_interval: int
    idle_check_interval: int

    # Directory paths
    output_dir: str
    db_dir: str
    db_path: str

    # Recording settings
    max_retries: int

    # Web server settings
    web_host: str
    web_port: int

    # External command settings
    ffmpeg_command: str
    ytdlp_command: str

    # Audio detection thresholds
    audio_detection_mean_threshold_db: int
    audio_detection_max_threshold_db: int

    # Transcription settings
    enable_transcription: bool
    pyannote_api_token: Optional[str]
    pyannote_segmentation_threshold: float

    # Recording resilience settings
    recording_format: str
    enable_segmented_recording: bool
    segment_duration: int
    recording_reconnect: bool

    # Static stream detection settings
    enable_static_detection: bool
    static_min_growth_kb: int
    static_check_interval: int
    static_max_failures: int
    static_scene_threshold: int

    # Gemini API settings
    gemini_api_key: Optional[str]
    gemini_model: str
    enable_gemini_refinement: bool

    # Timezone
    timezone: pytz.tzinfo.BaseTzInfo = field(default_factory=lambda: CALGARY_TZ)

    @classmethod
    def from_env(cls) -> 'AppConfig':
        """
        Create an AppConfig instance from environment variables.

        Returns:
            AppConfig: Validated configuration instance

        Raises:
            ValueError: If any configuration validation fails
        """
        # Load all configuration from environment
        config = cls(
            stream_page_url=STREAM_PAGE_URL,
            council_calendar_api=COUNCIL_CALENDAR_API,
            active_check_interval=ACTIVE_CHECK_INTERVAL,
            idle_check_interval=IDLE_CHECK_INTERVAL,
            output_dir=OUTPUT_DIR,
            db_dir=DB_DIR,
            db_path=DB_PATH,
            max_retries=MAX_RETRIES,
            web_host=WEB_HOST,
            web_port=WEB_PORT,
            ffmpeg_command=FFMPEG_COMMAND,
            ytdlp_command=YTDLP_COMMAND,
            audio_detection_mean_threshold_db=AUDIO_DETECTION_MEAN_THRESHOLD_DB,
            audio_detection_max_threshold_db=AUDIO_DETECTION_MAX_THRESHOLD_DB,
            enable_transcription=ENABLE_TRANSCRIPTION,
            pyannote_api_token=PYANNOTE_API_TOKEN,
            pyannote_segmentation_threshold=PYANNOTE_SEGMENTATION_THRESHOLD,
            recording_format=RECORDING_FORMAT,
            enable_segmented_recording=ENABLE_SEGMENTED_RECORDING,
            segment_duration=SEGMENT_DURATION,
            recording_reconnect=RECORDING_RECONNECT,
            enable_static_detection=ENABLE_STATIC_DETECTION,
            static_min_growth_kb=STATIC_MIN_GROWTH_KB,
            static_check_interval=STATIC_CHECK_INTERVAL,
            static_max_failures=STATIC_MAX_FAILURES,
            static_scene_threshold=STATIC_SCENE_THRESHOLD,
            gemini_api_key=GEMINI_API_KEY,
            gemini_model=GEMINI_MODEL,
            enable_gemini_refinement=ENABLE_GEMINI_REFINEMENT,
            timezone=CALGARY_TZ,
        )

        # Validate the configuration
        config.validate()

        return config

    def validate(self) -> None:
        """
        Validate the configuration.

        Raises:
            ValueError: If any validation check fails with a descriptive message
        """
        errors = []

        # Validate polling intervals
        if self.active_check_interval <= 0:
            errors.append(
                f"ACTIVE_CHECK_INTERVAL must be positive (got {self.active_check_interval})"
            )

        if self.idle_check_interval <= self.active_check_interval:
            errors.append(
                f"IDLE_CHECK_INTERVAL ({self.idle_check_interval}) must be greater than "
                f"ACTIVE_CHECK_INTERVAL ({self.active_check_interval})"
            )

        # Validate directory paths
        if not self.output_dir:
            errors.append("OUTPUT_DIR must not be empty")
        else:
            output_path = Path(self.output_dir)
            # Create the directory if it doesn't exist
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                # Check if it's writable
                test_file = output_path / ".write_test"
                try:
                    test_file.touch()
                    test_file.unlink()
                except (OSError, PermissionError) as e:
                    errors.append(f"OUTPUT_DIR '{self.output_dir}' is not writable: {e}")
            except (OSError, PermissionError) as e:
                errors.append(f"Cannot create OUTPUT_DIR '{self.output_dir}': {e}")

        if not self.db_dir:
            errors.append("DB_DIR must not be empty")
        else:
            db_path = Path(self.db_dir)
            # Create the directory if it doesn't exist
            try:
                db_path.mkdir(parents=True, exist_ok=True)
                # Check if it's writable
                test_file = db_path / ".write_test"
                try:
                    test_file.touch()
                    test_file.unlink()
                except (OSError, PermissionError) as e:
                    errors.append(f"DB_DIR '{self.db_dir}' is not writable: {e}")
            except (OSError, PermissionError) as e:
                errors.append(f"Cannot create DB_DIR '{self.db_dir}': {e}")

        # Validate transcription settings
        if self.enable_transcription and not self.pyannote_api_token:
            errors.append(
                "PYANNOTE_API_TOKEN is required when ENABLE_TRANSCRIPTION=true. "
                "Get a token from https://huggingface.co/pyannote/speaker-diarization"
            )

        # Validate pyannote segmentation threshold
        if not (0.0 <= self.pyannote_segmentation_threshold <= 1.0):
            errors.append(
                f"PYANNOTE_SEGMENTATION_THRESHOLD must be between 0.0 and 1.0 "
                f"(got {self.pyannote_segmentation_threshold})"
            )

        # Validate Gemini settings
        if self.enable_gemini_refinement and not self.gemini_api_key:
            errors.append(
                "GEMINI_API_KEY is required when ENABLE_GEMINI_REFINEMENT=true"
            )

        # Validate recording format
        valid_formats = ["mkv", "mp4", "ts"]
        if self.recording_format not in valid_formats:
            errors.append(
                f"RECORDING_FORMAT must be one of {valid_formats} "
                f"(got '{self.recording_format}')"
            )

        # Validate segment duration
        if self.enable_segmented_recording and self.segment_duration <= 0:
            errors.append(
                f"SEGMENT_DURATION must be positive when segmented recording is enabled "
                f"(got {self.segment_duration})"
            )

        # Validate static detection settings
        if self.enable_static_detection:
            if self.static_min_growth_kb < 0:
                errors.append(
                    f"STATIC_MIN_GROWTH_KB must be non-negative "
                    f"(got {self.static_min_growth_kb})"
                )
            if self.static_check_interval <= 0:
                errors.append(
                    f"STATIC_CHECK_INTERVAL must be positive "
                    f"(got {self.static_check_interval})"
                )
            if self.static_max_failures <= 0:
                errors.append(
                    f"STATIC_MAX_FAILURES must be positive "
                    f"(got {self.static_max_failures})"
                )
            if self.static_scene_threshold < 0:
                errors.append(
                    f"STATIC_SCENE_THRESHOLD must be non-negative "
                    f"(got {self.static_scene_threshold})"
                )

        # Validate web server settings
        if self.web_port < 1 or self.web_port > 65535:
            errors.append(
                f"WEB_PORT must be between 1 and 65535 (got {self.web_port})"
            )

        # Validate max retries
        if self.max_retries < 0:
            errors.append(f"MAX_RETRIES must be non-negative (got {self.max_retries})")

        # If there are any errors, raise a ValueError with all error messages
        if errors:
            error_message = "Configuration validation failed:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            logger.error(error_message)
            raise ValueError(error_message)

        logger.info("Configuration validation passed")


def validate_config() -> AppConfig:
    """
    Convenience function to validate configuration from environment.

    Returns:
        AppConfig: Validated configuration instance

    Raises:
        ValueError: If any configuration validation fails
    """
    return AppConfig.from_env()
