#!/usr/bin/env python3
"""
Audio processing utilities for transcription.
Handles extraction of audio from video files.
"""

import os
import subprocess
import logging
from typing import Optional
from exceptions import WhisperError


class AudioProcessor:
    """Handles audio extraction from video files."""

    def __init__(self):
        """Initialize audio processor."""
        self.logger = logging.getLogger(__name__)

    def extract_audio_to_wav(
        self,
        video_path: str,
        output_wav_path: Optional[str] = None,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> str:
        """
        Extract audio from video to WAV format suitable for transcription.

        Args:
            video_path: Path to video file
            output_wav_path: Optional output path (defaults to video_path with .wav extension)
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            Path to extracted WAV file
        """
        if recording_id:
            import database as db

        prefix = f"Segment {segment_number}: " if segment_number else ""

        # Default to saving WAV next to video file for persistence and resume capability
        if output_wav_path is None:
            output_wav_path = os.path.splitext(video_path)[0] + '.wav'

        # Check if WAV already exists (resume scenario)
        if os.path.exists(output_wav_path):
            msg = f"Using existing audio file: {output_wav_path}"
            self.logger.info(msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
                db.add_recording_log(recording_id, f'{prefix}{msg}', 'info')
            return output_wav_path

        msg = "Extracting audio to WAV format"
        self.logger.info(f"{msg}...")
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
            db.add_recording_log(recording_id, f'{prefix}{msg}', 'info')

        # Use ffmpeg to extract audio to WAV
        # pyannote requires: 16-bit PCM, 16kHz, mono
        try:
            subprocess.run([
                'ffmpeg', '-i', video_path,
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                output_wav_path
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            error_msg = f"ffmpeg failed with return code {e.returncode} when processing '{video_path}'"
            stderr_output = e.stderr if e.stderr else ""
            self.logger.error(f"{error_msg}", exc_info=True)
            if stderr_output:
                self.logger.error(f"ffmpeg stderr:\n{stderr_output}")
            if recording_id:
                db.add_transcription_log(
                    recording_id,
                    f"{prefix}{error_msg}. ffmpeg stderr: {stderr_output}",
                    'error'
                )
                db.add_recording_log(
                    recording_id,
                    f"{prefix}{error_msg}",
                    'error'
                )
            raise WhisperError(video_path, f"{error_msg}. stderr: {stderr_output}")

        msg = f"Audio extracted to {output_wav_path}"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        return output_wav_path
