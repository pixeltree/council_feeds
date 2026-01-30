#!/usr/bin/env python3
"""
Utilities for merging transcription and diarization results.
"""

import logging
from typing import Dict, List
from datetime import timedelta


class TranscriptMerger:
    """Handles merging of transcription and diarization data."""

    def __init__(self):
        """Initialize transcript merger."""
        self.logger = logging.getLogger(__name__)

    def merge_transcription_and_diarization(
        self,
        transcription: Dict,
        diarization_segments: List[Dict]
    ) -> List[Dict]:
        """
        Merge Whisper transcription with speaker diarization.

        Args:
            transcription: Whisper transcription result
            diarization_segments: Speaker diarization segments

        Returns:
            List of segments with text and speaker labels
        """
        merged_segments = []

        for segment in transcription['segments']:
            seg_start = segment['start']
            seg_end = segment['end']
            seg_text = segment['text'].strip()

            # Find overlapping speaker (now returns tuple with confidence)
            speaker_info = self._find_speaker_for_segment(
                seg_start, seg_end, diarization_segments
            )

            merged_segment = {
                'start': seg_start,
                'end': seg_end,
                'text': seg_text,
                'speaker': speaker_info['speaker']
            }
            # Include confidence if available
            if 'confidence' in speaker_info:
                merged_segment['speaker_confidence'] = speaker_info['confidence']

            merged_segments.append(merged_segment)

        return merged_segments

    def _find_speaker_for_segment(
        self,
        start: float,
        end: float,
        diarization_segments: List[Dict]
    ) -> Dict:
        """
        Find the speaker with the most overlap for a given time segment.

        Args:
            start: Segment start time
            end: Segment end time
            diarization_segments: List of speaker segments

        Returns:
            Dictionary with speaker label and confidence (if available)
        """
        max_overlap = 0
        best_speaker_info = {"speaker": "UNKNOWN"}

        for dia_seg in diarization_segments:
            # Calculate overlap
            overlap_start = max(start, dia_seg['start'])
            overlap_end = min(end, dia_seg['end'])
            overlap = max(0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker_info = {"speaker": dia_seg['speaker']}
                # Include confidence if available
                if 'confidence' in dia_seg:
                    best_speaker_info['confidence'] = dia_seg['confidence']

        return best_speaker_info

    def format_transcript_as_text(self, segments: List[Dict]) -> str:
        """
        Format transcript segments as readable text.

        Args:
            segments: List of transcript segments with speaker labels

        Returns:
            Formatted transcript string
        """
        lines = []
        current_speaker = None

        for segment in segments:
            speaker = segment['speaker']
            text = segment['text']
            timestamp = str(timedelta(seconds=int(segment['start'])))

            # Add speaker label if changed
            if speaker != current_speaker:
                lines.append(f"\n[{speaker}] ({timestamp})")
                current_speaker = speaker

            lines.append(text)

        return '\n'.join(lines)
