#!/usr/bin/env python3
"""
Transcription package for Calgary Council Stream Recorder.

This package provides modular transcription services:
- Audio extraction from video files
- Whisper-based speech-to-text transcription
- Pyannote.ai speaker diarization
- Transcript merging and formatting
"""

from .audio_processor import AudioProcessor
from .whisper_service import WhisperService
from .diarization_service import DiarizationService
from .merger import TranscriptMerger

__all__ = [
    'AudioProcessor',
    'WhisperService',
    'DiarizationService',
    'TranscriptMerger',
]
