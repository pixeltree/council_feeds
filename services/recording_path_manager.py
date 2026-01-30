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

        if ENABLE_SEGMENTED_RECORDING:
            output_pattern = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}_segment_%03d.{format_ext}"
            )
            output_file = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}.{format_ext}"
            )
        else:
            output_file = os.path.join(
                self.output_dir,
                f"council_meeting_{timestamp}.{format_ext}"
            )
            output_pattern = None

        return output_file, output_pattern, format_ext

    def ensure_output_directory(self) -> None:
        """Ensure the output directory exists."""
        os.makedirs(self.output_dir, exist_ok=True)
