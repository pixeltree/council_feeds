#!/usr/bin/env python3
"""
FFmpeg command builder for constructing recording commands.
"""

from typing import Optional

from config import (
    FFMPEG_COMMAND,
    RECORDING_RECONNECT,
    ENABLE_SEGMENTED_RECORDING,
    SEGMENT_DURATION,
)


class FFmpegCommandBuilder:
    """Builds ffmpeg commands for stream recording."""

    def __init__(self, ffmpeg_command: str = FFMPEG_COMMAND):
        self.ffmpeg_command = ffmpeg_command

    def build_command(
        self,
        stream_url: str,
        output_file: str,
        output_pattern: Optional[str],
        format_ext: str
    ) -> list[str]:
        """Build ffmpeg command with resilient options.

        Args:
            stream_url: URL of the stream to record
            output_file: Path to output file
            output_pattern: Pattern for segmented recording (if enabled)
            format_ext: File format extension

        Returns:
            List of command arguments for ffmpeg
        """
        cmd = [self.ffmpeg_command]

        # Add reconnect options if enabled
        if RECORDING_RECONNECT:
            cmd.extend([
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_delay_max', '5'
            ])

        if not stream_url:
            raise ValueError("stream_url cannot be empty")
        cmd.extend(['-i', stream_url])

        # Copy streams without re-encoding
        cmd.extend(['-c', 'copy'])

        # Fix AAC stream
        if format_ext != 'ts':  # TS doesn't need this
            cmd.extend(['-bsf:a', 'aac_adtstoasc'])

        # Add format-specific options
        if ENABLE_SEGMENTED_RECORDING:
            # Segmented recording for resilience
            if not output_pattern:
                raise ValueError("output_pattern is required when ENABLE_SEGMENTED_RECORDING is True")
            cmd.extend([
                '-f', 'segment',
                '-segment_time', str(SEGMENT_DURATION),
                '-segment_format', format_ext if format_ext == 'mkv' else 'matroska',
                '-reset_timestamps', '1',
                '-strftime', '1',  # Allow time formatting in segment names
                output_pattern
            ])
        else:
            # Single file recording
            if format_ext == 'mp4':
                # Use fragmented MP4 for better resilience
                cmd.extend([
                    '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
                    '-f', 'mp4'
                ])
            elif format_ext == 'ts':
                cmd.extend(['-f', 'mpegts'])
            else:  # mkv
                cmd.extend(['-f', 'matroska'])

            cmd.append(output_file)

        return cmd
