#!/usr/bin/env python3
"""
Whisper-based speech-to-text transcription service.
"""

import logging
from faster_whisper import WhisperModel
from typing import Dict, Optional, Any
from tqdm import tqdm
import wave


class WhisperService:
    """Service for Whisper-based transcription."""

    def __init__(self, model: str = "base", device: Optional[str] = None):
        """
        Initialize Whisper service.

        Args:
            model: Whisper model size (tiny, base, small, medium, large)
            device: Device to use ('cpu', 'cuda', or None for auto-detect)
        """
        self.logger = logging.getLogger(__name__)
        self.model_name = model

        # Determine device
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        # Lazy load model
        self._model = None

    def _load_model(self) -> Any:
        """Lazy load Whisper model."""
        if self._model is None:
            self.logger.info(f"Using device for Whisper: {self.device}")
            self.logger.info(f"Loading Whisper model '{self.model_name}'...")
            # faster-whisper uses compute_type instead of device parameter
            compute_type = "int8" if self.device == "cpu" else "float16"
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=compute_type
            )
        return self._model

    def _get_audio_duration(self, audio_path: str) -> Optional[float]:
        """
        Get audio duration in seconds for progress monitoring.

        Args:
            audio_path: Path to audio file

        Returns:
            Duration in seconds, or None if unable to determine
        """
        try:
            with wave.open(audio_path, 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration = frames / float(rate)
                return duration
        except Exception as e:
            self.logger.warning(f"Could not determine audio duration: {e}")
            return None

    def transcribe_audio(
        self,
        audio_path: str,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> Dict:
        """
        Transcribe audio file using Whisper.

        Args:
            audio_path: Path to audio/video file
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            Dictionary with transcription results including segments
        """
        model = self._load_model()

        msg = f"Transcribing audio: {audio_path}"
        self.logger.info(msg)

        # Prepare log prefix for segment logging
        prefix = f"Segment {segment_number}: " if segment_number else ""

        if recording_id:
            import database as db
            db.add_transcription_log(recording_id, f'{prefix}Starting Whisper transcription (this may take 1-2 minutes)', 'info')
            db.add_recording_log(recording_id, f'{prefix}Starting Whisper transcription', 'info')
            # Mark step as in_progress
            db.update_transcription_step(recording_id, 'whisper', 'in_progress')

        # Get audio duration for progress bar
        audio_duration = self._get_audio_duration(audio_path)

        # faster-whisper returns segments as generator, we need to convert to list
        segments, info = model.transcribe(
            audio_path,
            language="en"
        )

        # Convert generator to list and build result dict with progress bar
        segments_list = []
        full_text = []

        # Create progress bar based on audio duration
        if audio_duration:
            pbar = tqdm(
                total=audio_duration,
                desc="Transcribing",
                unit="s",
                bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.1f}/{total:.1f}s [{elapsed}<{remaining}]"
            )
        else:
            # If duration unknown, use indeterminate progress bar
            pbar = tqdm(
                desc="Transcribing",
                unit=" segments",
                bar_format="{desc}: {n} segments [{elapsed}]"
            )

        try:
            last_end_time = 0
            last_db_update = 0
            for segment in segments:
                segments_list.append({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text
                })
                full_text.append(segment.text)

                # Update progress bar
                if audio_duration:
                    # Update to the end time of current segment
                    progress = segment.end - last_end_time
                    pbar.update(progress)
                    last_end_time = segment.end

                    # Update database every 5 seconds of audio processed (or 5% progress)
                    if recording_id and (segment.end - last_db_update >= 5.0 or
                                        segment.end / audio_duration - last_db_update / audio_duration >= 0.05):
                        try:
                            percentage = int((segment.end / audio_duration) * 100)
                            db.update_transcription_progress(recording_id, {
                                'stage': 'whisper',
                                'step': 'transcribing',
                                'percent': min(percentage, 99),  # Never show 100% until complete
                                'current': round(segment.end, 1),
                                'total': round(audio_duration, 1)
                            })
                            last_db_update = segment.end
                        except Exception as e:
                            # Don't fail transcription if progress update fails
                            self.logger.warning(f"Failed to update progress: {e}")
                else:
                    # Just count segments
                    pbar.update(1)
        finally:
            pbar.close()

        result = {
            'language': info.language,
            'segments': segments_list,
            'text': ' '.join(full_text)
        }

        if recording_id:
            # Clear progress on completion
            db.update_transcription_progress(recording_id, {
                'stage': 'whisper',
                'step': 'completed',
                'percent': 100
            })
            # Mark step as completed
            db.update_transcription_step(recording_id, 'whisper', 'completed')
            db.add_transcription_log(recording_id, f'{prefix}Whisper transcription completed', 'info')
            db.add_recording_log(recording_id, f'{prefix}Whisper transcription completed', 'info')

        return result
