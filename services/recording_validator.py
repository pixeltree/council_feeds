#!/usr/bin/env python3
"""
Recording validator for checking audio content and validation.
"""

import os
import logging
import subprocess
from datetime import datetime
from typing import Optional

import database as db
from config import (
    FFMPEG_COMMAND,
    AUDIO_DETECTION_MEAN_THRESHOLD_DB,
    AUDIO_DETECTION_MAX_THRESHOLD_DB,
)

# Constants for audio level validation
MIN_MEAN_VOLUME_DB = -50.0
MIN_MAX_VOLUME_DB = -30.0


class RecordingValidator:
    """Validates recording content and audio levels."""

    def __init__(self, ffmpeg_command: str = FFMPEG_COMMAND):
        self.ffmpeg_command = ffmpeg_command
        self.logger = logging.getLogger(__name__)

    def check_audio_levels(self, file_path: str) -> tuple[Optional[float], Optional[float]]:
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

    def has_audio_content(self, mean_volume: Optional[float], max_volume: Optional[float]) -> bool:
        """Determine if audio levels indicate real content.

        Args:
            mean_volume: Mean volume in dB
            max_volume: Max volume in dB

        Returns:
            True if audio content is detected
        """
        if mean_volume is None or max_volume is None:
            # Default to keeping if check fails
            return True

        # If audio is reasonably loud, it has content
        return mean_volume > MIN_MEAN_VOLUME_DB or max_volume > MIN_MAX_VOLUME_DB

    def validate_recording_content(
        self,
        output_file: str,
        recording_id: int,
        end_time: datetime
    ) -> bool:
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
            mean_volume, max_volume = self.check_audio_levels(output_file)

            if mean_volume is not None and max_volume is not None:
                self.logger.info(f"Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB")
                has_content = self.has_audio_content(mean_volume, max_volume)
                if not has_content:
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

    def is_static_content(self, mean_volume: Optional[float], max_volume: Optional[float]) -> bool:
        """Check if audio levels indicate static/placeholder content.

        Args:
            mean_volume: Mean volume in dB
            max_volume: Max volume in dB

        Returns:
            True if content appears to be static
        """
        if mean_volume is None or max_volume is None:
            return False

        return (mean_volume < AUDIO_DETECTION_MEAN_THRESHOLD_DB or
                max_volume < AUDIO_DETECTION_MAX_THRESHOLD_DB)
