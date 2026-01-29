#!/usr/bin/env python3
"""
Transcription service for Calgary Council Stream Recorder.
Uses Whisper for speech-to-text and pyannote.audio for speaker diarization.
"""

import os
from faster_whisper import WhisperModel
import torch
from pyannote.audio import Pipeline
from typing import Dict, List, Optional
from datetime import timedelta
import json


class TranscriptionService:
    """Service for transcribing recorded videos with speaker diarization."""

    def __init__(
        self,
        whisper_model: str = "base",
        hf_token: Optional[str] = None,
        device: Optional[str] = None
    ):
        """
        Initialize transcription service.

        Args:
            whisper_model: Whisper model size (tiny, base, small, medium, large)
            hf_token: HuggingFace token for pyannote.audio (required for diarization)
            device: Device to use ('cpu', 'cuda', or None for auto-detect)
        """
        self.whisper_model_name = whisper_model
        self.hf_token = hf_token

        # Determine device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        print(f"[TRANSCRIPTION] Using device: {self.device}")
        self._last_recording_id = None  # Track last recording ID for logging

        # Lazy load models (only when needed)
        self._whisper_model = None
        self._diarization_pipeline = None

    def _load_whisper_model(self):
        """Lazy load Whisper model."""
        if self._whisper_model is None:
            print(f"[TRANSCRIPTION] Loading Whisper model '{self.whisper_model_name}'...")
            # faster-whisper uses compute_type instead of device parameter
            compute_type = "int8" if self.device == "cpu" else "float16"
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device=self.device,
                compute_type=compute_type
            )
        return self._whisper_model

    def _load_diarization_pipeline(self):
        """Lazy load pyannote diarization pipeline."""
        if self._diarization_pipeline is None:
            if not self.hf_token:
                raise ValueError(
                    "HuggingFace token required for speaker diarization. "
                    "Get one at https://huggingface.co/settings/tokens and "
                    "accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1"
                )

            print("[TRANSCRIPTION] Loading speaker diarization pipeline...")
            # Set HF_TOKEN environment variable - newer huggingface_hub reads this automatically
            # This avoids parameter name conflicts between pyannote and huggingface_hub versions
            os.environ['HF_TOKEN'] = self.hf_token
            self._diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1"
            )

            # Move to appropriate device
            if self.device == "cuda":
                self._diarization_pipeline.to(torch.device("cuda"))

        return self._diarization_pipeline

    def transcribe_audio(self, audio_path: str, recording_id: Optional[int] = None, segment_number: Optional[int] = None) -> Dict:
        """
        Transcribe audio file using Whisper.

        Args:
            audio_path: Path to audio/video file
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            Dictionary with transcription results including segments
        """
        model = self._load_whisper_model()

        msg = f"Transcribing audio: {audio_path}"
        print(f"[TRANSCRIPTION] {msg}")

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

    def perform_diarization(self, audio_path: str, recording_id: Optional[int] = None, segment_number: Optional[int] = None) -> List[Dict]:
        """
        Perform speaker diarization on audio file.

        Args:
            audio_path: Path to audio/video file
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            List of speaker segments with start time, end time, and speaker label
        """
        import subprocess
        import tempfile

        pipeline = self._load_diarization_pipeline()

        msg = f"Performing speaker diarization: {audio_path}"
        print(f"[TRANSCRIPTION] {msg}")

        if recording_id:
            import database as db
            prefix = f"Segment {segment_number}: " if segment_number else ""
            db.add_transcription_log(recording_id, f'{prefix}Starting speaker diarization (this may take 5-10 minutes on CPU)', 'info')
            db.add_recording_log(recording_id, f'{prefix}Starting speaker diarization', 'info')

        # pyannote requires WAV format - extract audio if needed
        if not audio_path.endswith('.wav'):
            print(f"[TRANSCRIPTION] Extracting audio to WAV format for diarization...")
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Converting audio to WAV format', 'info')

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                temp_wav_path = temp_wav.name

            # Use ffmpeg to extract audio to WAV
            subprocess.run([
                'ffmpeg', '-i', audio_path,
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                temp_wav_path
            ], check=True, capture_output=True)

            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Audio converted, running diarization model', 'info')

            try:
                diarization = pipeline(temp_wav_path)
            finally:
                # Clean up temp file
                os.remove(temp_wav_path)
        else:
            diarization = pipeline(audio_path)

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Speaker diarization completed', 'info')
            db.add_recording_log(recording_id, f'{prefix}Speaker diarization completed', 'info')

        # Convert to list of segments
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                'start': turn.start,
                'end': turn.end,
                'speaker': speaker
            })

        return segments

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

            # Find overlapping speaker
            speaker = self._find_speaker_for_segment(
                seg_start, seg_end, diarization_segments
            )

            merged_segments.append({
                'start': seg_start,
                'end': seg_end,
                'text': seg_text,
                'speaker': speaker
            })

        return merged_segments

    def _find_speaker_for_segment(
        self,
        start: float,
        end: float,
        diarization_segments: List[Dict]
    ) -> str:
        """
        Find the speaker with the most overlap for a given time segment.

        Args:
            start: Segment start time
            end: Segment end time
            diarization_segments: List of speaker segments

        Returns:
            Speaker label with most overlap, or "UNKNOWN" if none found
        """
        max_overlap = 0
        best_speaker = "UNKNOWN"

        for dia_seg in diarization_segments:
            # Calculate overlap
            overlap_start = max(start, dia_seg['start'])
            overlap_end = min(end, dia_seg['end'])
            overlap = max(0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = dia_seg['speaker']

        return best_speaker

    def transcribe_with_speakers(
        self,
        video_path: str,
        output_path: Optional[str] = None,
        save_to_file: bool = True,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> Dict:
        """
        Complete transcription pipeline with speaker diarization.

        Args:
            video_path: Path to video file
            output_path: Optional path to save transcript (defaults to video_path + .json)
            save_to_file: Whether to save results to file (default: True)

        Returns:
            Dictionary with transcript segments and metadata

        Raises:
            FileNotFoundError: If video_path does not exist
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        print(f"[TRANSCRIPTION] Starting transcription with speaker diarization...")
        print(f"[TRANSCRIPTION] Input file: {video_path}")

        # Step 1: Transcribe with Whisper
        if recording_id:
            import database as db
            db.update_transcription_progress(recording_id, {'stage': 'whisper', 'step': 'transcribing'})

        transcription = self.transcribe_audio(video_path, recording_id=recording_id, segment_number=segment_number)

        # Step 2: Perform speaker diarization
        if recording_id:
            import database as db
            db.update_transcription_progress(recording_id, {'stage': 'diarization', 'step': 'analyzing'})

        diarization_segments = self.perform_diarization(video_path, recording_id=recording_id, segment_number=segment_number)

        # Step 3: Merge results
        if recording_id:
            import database as db
            prefix = f"Segment {segment_number}: " if segment_number else ""
            db.update_transcription_progress(recording_id, {'stage': 'merging', 'step': 'combining'})
            db.add_transcription_log(recording_id, f'{prefix}Merging transcription with speaker labels', 'info')

        merged_segments = self.merge_transcription_and_diarization(
            transcription, diarization_segments
        )

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Merge completed', 'info')

        # Prepare final output
        result = {
            'file': video_path,
            'language': transcription.get('language', 'en'),
            'segments': merged_segments,
            'full_text': transcription['text'],
            'num_speakers': len(set(seg['speaker'] for seg in merged_segments))
        }

        # Save to file if requested
        if save_to_file:
            if output_path is None:
                output_path = video_path + '.transcript.json'

            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Saving transcript to file', 'info')

            self.save_transcript(result, output_path)

        print(f"[TRANSCRIPTION] Detected {result['num_speakers']} unique speakers")

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Transcription complete - detected {result["num_speakers"]} speakers', 'info')
            db.add_recording_log(recording_id, f'{prefix}Transcription complete - detected {result["num_speakers"]} speakers', 'info')

        return result

    def save_transcript(self, transcript: Dict, output_path: str):
        """
        Save transcript to JSON file.

        Args:
            transcript: Transcript dictionary
            output_path: Path to save file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)

        print(f"[TRANSCRIPTION] Transcript saved to: {output_path}")

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
