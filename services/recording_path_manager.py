#!/usr/bin/env python3
"""
Recording path manager for handling output file paths and formats.
"""

import os
from typing import Optional

from config import (
    OUTPUT_DIR,
    RECORDING_FORMAT,
    ENABLE_SEGMENTED_RECORDING,
)


class RecordingPathManager:
    """Manages output file paths and formats for recordings."""

    def __init__(self, output_dir: str = OUTPUT_DIR):
        self.output_dir = output_dir

    def determine_output_paths(self, timestamp: str) -> tuple[str, Optional[str], str]:
        """Determine output file paths and format for recording.

        Args:
            timestamp: Timestamp string for file naming

        Returns:
            Tuple of (output_file, output_pattern, format_ext)
        """
        format_ext = RECORDING_FORMAT if RECORDING_FORMAT in ['mkv', 'mp4', 'ts'] else 'mkv'

        # Create subfolder for this recording
        recording_folder = os.path.join(self.output_dir, f"council_meeting_{timestamp}")

        if ENABLE_SEGMENTED_RECORDING:
            output_pattern = os.path.join(
                recording_folder,
                f"council_meeting_{timestamp}_segment_%03d.{format_ext}"
            )
            output_file = os.path.join(
                recording_folder,
                f"council_meeting_{timestamp}.{format_ext}"
            )
        else:
            output_file = os.path.join(
                recording_folder,
                f"council_meeting_{timestamp}.{format_ext}"
            )
            output_pattern = None

        return output_file, output_pattern, format_ext

    def ensure_output_directory(self, recording_path: Optional[str] = None) -> None:
        """Ensure the output directory exists.

        Args:
            recording_path: Optional specific recording path to ensure directory for
        """
        if recording_path:
            # Create the parent directory for the specific recording
            os.makedirs(os.path.dirname(recording_path), exist_ok=True)
        else:
            # Create the base output directory
            os.makedirs(self.output_dir, exist_ok=True)
