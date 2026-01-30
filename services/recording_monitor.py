#!/usr/bin/env python3
"""
Recording monitor for tracking recording process and detecting static content.
"""

import os
import glob
import time
import logging
import subprocess
from typing import Optional

import database as db
from config import (
    ENABLE_STATIC_DETECTION,
    STATIC_CHECK_INTERVAL,
    STATIC_MAX_FAILURES,
    ENABLE_SEGMENTED_RECORDING,
)


class RecordingMonitor:
    """Monitors recording process and detects static/placeholder content."""

    def __init__(self, stream_service, validator):
        self.stream_service = stream_service
        self.validator = validator
        self.logger = logging.getLogger(__name__)
        self.stop_requested = False
        self.stop_reason = None  # Track reason for stopping ('user' or 'static')

    def request_stop(self) -> None:
        """Request monitoring to stop."""
        self.stop_requested = True
        self.stop_reason = 'user'

    def reset_stop(self) -> None:
        """Reset stop request flag."""
        self.stop_requested = False
        self.stop_reason = None

    def monitor_recording(
        self,
        process: subprocess.Popen,
        stream_url: str,
        output_file: str,
        output_pattern: Optional[str],
        meeting_id: Optional[int]
    ) -> None:
        """Monitor recording process and check for issues.

        Args:
            process: The recording process to monitor
            stream_url: URL of the stream being recorded
            output_file: Path to output file
            output_pattern: Pattern for segmented files (if enabled)
            meeting_id: Database ID of associated meeting
        """
        static_checks = 0

        while True:
            # Wait before checking again
            time.sleep(STATIC_CHECK_INTERVAL)

            # Check for static content using audio detection
            if ENABLE_STATIC_DETECTION:
                file_to_check = self._get_file_to_check(output_file, output_pattern)

                if file_to_check and os.path.exists(file_to_check):
                    mean_volume, max_volume = self.validator.check_audio_levels(file_to_check)

                    self.logger.debug(f"[STATIC CHECK] Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB")

                    # If audio is very quiet, likely static placeholder
                    if mean_volume is not None and max_volume is not None:
                        if self.validator.is_static_content(mean_volume, max_volume):
                            static_checks += 1
                            self.logger.warning(
                                f"Low audio levels detected. Static check {static_checks}/{STATIC_MAX_FAILURES}"
                            )

                            if static_checks >= STATIC_MAX_FAILURES:
                                self.logger.warning("Stream appears to be static (no audio/placeholder). Stopping recording...")
                                db.log_stream_status(stream_url, 'static', meeting_id, 'Static content detected (silence)')
                                self.stop_requested = True
                                self.stop_reason = 'static'
                        else:
                            if static_checks > 0:
                                self.logger.info("[STATIC CHECK] Audio detected, resetting counter")
                            static_checks = 0  # Reset counter if audio detected
                    else:
                        self.logger.warning("[STATIC CHECK] Could not parse audio levels")

            # Check if stop was requested
            if self.stop_requested:
                if self.stop_reason == 'static':
                    self.logger.info("Stop requested (static content detected). Stopping recording...")
                    # Status already logged when static was detected
                else:
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

    def _get_file_to_check(self, output_file: str, output_pattern: Optional[str]) -> Optional[str]:
        """Get the most recent file to check for static content.

        Args:
            output_file: Single output file path
            output_pattern: Pattern for segmented files

        Returns:
            Path to file to check, or None
        """
        if ENABLE_SEGMENTED_RECORDING and output_pattern:
            base_pattern = output_pattern.replace('%03d', '*')
            segment_files = sorted(glob.glob(base_pattern))
            if segment_files:
                return segment_files[-1]  # Most recent segment
        elif os.path.exists(output_file):
            return output_file
        return None
