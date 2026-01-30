#!/usr/bin/env python3
"""
Segment merger for combining recording segments into single files.
"""

import os
import glob
import logging
import subprocess
from typing import Optional

from exceptions import RecordingStorageError
from config import FFMPEG_COMMAND


class SegmentMerger:
    """Merges recording segments into single files."""

    def __init__(self, output_dir: str, ffmpeg_command: str = FFMPEG_COMMAND):
        self.output_dir = output_dir
        self.ffmpeg_command = ffmpeg_command
        self.logger = logging.getLogger(__name__)

    def merge_segments(
        self,
        pattern: str,
        output_file: str,
        timestamp: str,
        format_ext: str
    ) -> Optional[str]:
        """Merge recording segments into a single file.

        Args:
            pattern: Glob pattern for segment files
            output_file: Output file path for merged recording
            timestamp: Timestamp for temporary files
            format_ext: File format extension

        Returns:
            Path to merged file, or None if merge failed
        """
        # Find all segment files
        segment_dir = os.path.dirname(pattern)
        segment_pattern = os.path.basename(pattern).replace('%03d', '*')
        segments = sorted(glob.glob(os.path.join(segment_dir, segment_pattern)))

        if not segments:
            self.logger.warning("No segments found to merge")
            return None

        if len(segments) == 1:
            # Only one segment, just rename it
            try:
                os.rename(segments[0], output_file)
                return output_file
            except Exception as e:
                self.logger.error(f"Error renaming single segment: {e}", exc_info=True)
                raise RecordingStorageError(segments[0], 'rename', str(e))

        # Create concat file list for ffmpeg
        concat_file = os.path.join(self.output_dir, f"concat_{timestamp}.txt")
        try:
            with open(concat_file, 'w') as f:
                for segment in segments:
                    f.write(f"file '{os.path.abspath(segment)}'\n")

            # Merge using ffmpeg concat
            merge_cmd = [
                self.ffmpeg_command,
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                output_file
            ]

            result = subprocess.run(merge_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # Successfully merged, delete segments and concat file
                for segment in segments:
                    try:
                        os.remove(segment)
                    except OSError:
                        # Best-effort cleanup; ignore if file cannot be removed
                        pass
                try:
                    os.remove(concat_file)
                except OSError:
                    # Best-effort cleanup; ignore if file cannot be removed
                    pass
                return output_file
            else:
                self.logger.error(f"Merge failed: {result.stderr}")
                return None

        except Exception as e:
            self.logger.error(f"Error merging segments: {e}", exc_info=True)
            raise RecordingStorageError(output_file, 'merge', str(e))
        finally:
            # Clean up concat file on both success and failure
            try:
                if os.path.exists(concat_file):
                    os.remove(concat_file)
            except OSError:
                # Best-effort cleanup; ignore if file cannot be removed
                pass
