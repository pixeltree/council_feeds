#!/usr/bin/env python3
"""
Whisper-based speech-to-text transcription service.
"""

import logging
from faster_whisper import WhisperModel
from typing import Dict, Optional, Any


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

        if recording_id:
            import database as db
            prefix = f"Segment {segment_number}: " if segment_number else ""
            db.add_transcription_log(recording_id, f'{prefix}Starting Whisper transcription (this may take 1-2 minutes)', 'info')
            db.add_recording_log(recording_id, f'{prefix}Starting Whisper transcription', 'info')

        # faster-whisper returns segments as generator, we need to convert to list
        segments, info = model.transcribe(
            audio_path,
            language="en"
        )

        # Convert generator to list and build result dict
        segments_list = []
        full_text = []
        for segment in segments:
            segments_list.append({
                'start': segment.start,
                'end': segment.end,
                'text': segment.text
            })
            full_text.append(segment.text)

        result = {
            'language': info.language,
            'segments': segments_list,
            'text': ' '.join(full_text)
        }

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Whisper transcription completed', 'info')
            db.add_recording_log(recording_id, f'{prefix}Whisper transcription completed', 'info')

        return result
