#!/usr/bin/env python3
"""
Transcription service for Calgary Council Stream Recorder.
Uses Whisper for speech-to-text and pyannote.ai API for speaker diarization.
"""

import os
import requests
from faster_whisper import WhisperModel
from typing import Dict, List, Optional
from datetime import timedelta
import json
import time
import logging
from exceptions import WhisperError, DiarizationError, GeminiError


class TranscriptionService:
    """Service for transcribing recorded videos with speaker diarization."""

    def __init__(
        self,
        whisper_model: str = "base",
        pyannote_api_token: Optional[str] = None,
        device: Optional[str] = None
    ):
        """
        Initialize transcription service.

        Args:
            whisper_model: Whisper model size (tiny, base, small, medium, large)
            pyannote_api_token: pyannote.ai API token (required for diarization)
            device: Device to use for Whisper ('cpu', 'cuda', or None for auto-detect)
        """
        self.logger = logging.getLogger(__name__)
        self.whisper_model_name = whisper_model
        self.pyannote_api_token = pyannote_api_token
        self.pyannote_api_url = "https://api.pyannote.ai/v1/diarize"

        # Determine device for Whisper only
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        self._last_recording_id = None  # Track last recording ID for logging

        # Lazy load Whisper model (only when needed)
        self._whisper_model = None

    def _load_whisper_model(self):
        """Lazy load Whisper model."""
        if self._whisper_model is None:
            self.logger.info(f"Using device for Whisper: {self.device}")
            self.logger.info(f"Loading Whisper model '{self.whisper_model_name}'...")
            # faster-whisper uses compute_type instead of device parameter
            compute_type = "int8" if self.device == "cpu" else "float16"
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device=self.device,
                compute_type=compute_type
            )
        return self._whisper_model


    def _check_step_completed(self, steps: Dict, step_name: str) -> bool:
        """Check if a transcription step is already completed.

        Args:
            steps: Dictionary of step statuses
            step_name: Name of step to check

        Returns:
            True if step is completed, False otherwise
        """
        return steps.get(step_name, {}).get('status') == 'completed'

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

    def extract_audio_to_wav(self, video_path: str, output_wav_path: Optional[str] = None, recording_id: Optional[int] = None, segment_number: Optional[int] = None) -> str:
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
        import subprocess
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

    def perform_diarization(self, audio_path: str, recording_id: Optional[int] = None, segment_number: Optional[int] = None) -> List[Dict]:
        """
        Perform speaker diarization using pyannote.ai API.

        Args:
            audio_path: Path to audio/video file (preferably WAV)
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            List of speaker segments with start time, end time, and speaker label
        """
        if not self.pyannote_api_token:
            raise ValueError(
                "pyannote.ai API token required for speaker diarization. "
                "Get one at https://www.pyannote.ai/"
            )

        msg = f"Performing speaker diarization via API: {audio_path}"
        self.logger.info(msg)

        if recording_id:
            import database as db
            prefix = f"Segment {segment_number}: " if segment_number else ""
            db.add_transcription_log(recording_id, f'{prefix}Starting speaker diarization via pyannote.ai API', 'info')
            db.add_recording_log(recording_id, f'{prefix}Starting speaker diarization', 'info')

        headers = {
            "Authorization": f"Bearer {self.pyannote_api_token}",
            "Content-Type": "application/json"
        }

        # Step 1: Create a pre-signed URL for upload
        filename = os.path.basename(audio_path)
        media_key = f"{int(time.time())}_{filename}"
        media_url = f"media://{media_key}"

        msg = "Preparing to upload audio file to pyannote.ai"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        upload_response = requests.post(
            "https://api.pyannote.ai/v1/media/input",
            headers=headers,
            json={"url": media_url},
            timeout=30
        )

        if upload_response.status_code not in [200, 201]:
            error_msg = f"Failed to create upload URL: {upload_response.status_code}: {upload_response.text}"
            self.logger.error(error_msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
            raise DiarizationError(audio_path, error_msg)

        upload_data = upload_response.json()
        presigned_url = upload_data.get('url')  # Response has 'url' not 'presigned_url'

        # Step 2: Upload the audio file to the pre-signed URL
        # Get file size for progress tracking
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        msg = f"Uploading audio file ({file_size_mb:.1f} MB) to pyannote.ai"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        with open(audio_path, 'rb') as audio_file:
            upload_file_response = requests.put(
                presigned_url,
                data=audio_file,
                headers={"Content-Type": "audio/wav"},
                timeout=300  # 5 minute timeout for file upload
            )

        if upload_file_response.status_code not in [200, 204]:
            error_msg = f"Failed to upload file: {upload_file_response.status_code}: {upload_file_response.text}"
            self.logger.error(error_msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
            raise DiarizationError(audio_path, error_msg)

        msg = "Audio file uploaded successfully"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        # Step 3: Submit diarization job with the media URL
        msg = "Submitting diarization job to pyannote.ai"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        response = requests.post(
            self.pyannote_api_url,
            headers=headers,
            json={"url": media_url},
            timeout=30
        )

        if response.status_code != 200:
            error_msg = f"API request failed with status {response.status_code}: {response.text}"
            self.logger.error(error_msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
            raise DiarizationError(audio_path, error_msg)

        result = response.json()

        # Check if job is async (requires polling)
        job_id = result.get('jobId')
        if job_id:
            msg = f"Diarization job started (Job ID: {job_id}). Processing audio..."
            self.logger.info(msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

            # Poll for completion with timeout
            job_url = f"https://api.pyannote.ai/v1/jobs/{job_id}"
            last_status = None
            max_poll_time = 600  # 10 minutes max
            poll_interval = 5  # Poll every 5 seconds
            max_iterations = max_poll_time // poll_interval
            iteration = 0

            while iteration < max_iterations:
                time.sleep(poll_interval)
                iteration += 1

                try:
                    job_response = requests.get(job_url, headers=headers, timeout=10)
                    job_response.raise_for_status()
                    job_data = job_response.json()
                except requests.RequestException as e:
                    error_msg = f"Diarization job status request failed: {e}"
                    self.logger.error(error_msg, exc_info=True)
                    if recording_id:
                        db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                    raise DiarizationError(audio_path, error_msg)
                except json.JSONDecodeError as e:
                    error_msg = f"Diarization job status response was not valid JSON: {e}"
                    self.logger.error(error_msg, exc_info=True)
                    if recording_id:
                        db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                    raise DiarizationError(audio_path, error_msg)

                status = job_data.get('status')

                # Log status changes
                if status != last_status:
                    msg = f"Diarization job status: {status}"
                    self.logger.info(msg)
                    if recording_id:
                        db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
                    last_status = status

                if status == 'succeeded':
                    result = job_data.get('output', {})
                    break
                elif status == 'failed':
                    error_msg = f"Diarization job failed: {job_data.get('error', 'Unknown error')}"
                    self.logger.error(error_msg)
                    if recording_id:
                        db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                    raise DiarizationError(audio_path, error_msg)
            else:
                # Timeout reached
                error_msg = f"Diarization job timed out after {max_poll_time} seconds"
                self.logger.error(error_msg)
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                raise DiarizationError(audio_path, error_msg)

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Speaker diarization completed', 'info')
            db.add_recording_log(recording_id, f'{prefix}Speaker diarization completed', 'info')

        # Convert API response to list of segments
        # pyannote.ai returns diarization in format: {"diarization": [{"start": ..., "end": ..., "speaker": ..., "confidence": ...}]}
        segments = []
        diarization_data = result.get('diarization', result.get('segments', []))
        for segment_data in diarization_data:
            segment = {
                'start': segment_data['start'],
                'end': segment_data['end'],
                'speaker': segment_data['speaker']
            }
            # Include confidence score if available
            if 'confidence' in segment_data:
                segment['confidence'] = segment_data['confidence']
            segments.append(segment)

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

        This method supports resumability - it checks for completed steps and skips them.

        Args:
            video_path: Path to video file
            output_path: Optional path to save transcript (defaults to video_path + .json)
            save_to_file: Whether to save results to file (default: True)
            recording_id: Optional recording ID for tracking
            segment_number: Optional segment number for multi-segment recordings

        Returns:
            Dictionary with transcript segments and metadata

        Raises:
            FileNotFoundError: If video_path does not exist
        """
        if not os.path.exists(video_path):
            raise WhisperError(video_path, f"Video file not found: {video_path}")

        # Import database module once at the start if we have a recording_id
        if recording_id:
            import database as db

        self.logger.info("Starting transcription with speaker diarization...")
        self.logger.info(f"Input file: {video_path}")

        # Prepare log prefix for segment logging
        prefix = f"Segment {segment_number}: " if segment_number else ""

        # Check which steps are already completed by detecting files
        from transcription_progress import detect_transcription_progress
        steps = detect_transcription_progress(video_path)
        completed_steps = [name for name, data in steps.items() if data['status'] == 'completed']
        if completed_steps:
            self.logger.info(f"Resumability check - completed steps: {completed_steps}")

        # Step 0: Extract audio to WAV format once (for both Whisper and pyannote)
        if recording_id:
            db.update_transcription_progress(recording_id, {'stage': 'extraction', 'step': 'extracting'})

        audio_wav_path = self.extract_audio_to_wav(video_path, recording_id=recording_id, segment_number=segment_number)

        try:
            # Step 1: Transcribe with Whisper (check if already completed)
            transcription = None
            pyannote_path = video_path + '.diarization.pyannote.json'
            whisper_path = video_path + '.whisper.json'

            # Check if we can skip Whisper (whisper file exists)
            if steps.get('whisper', {}).get('status') == 'completed' and os.path.exists(whisper_path):
                # Load existing transcription from saved file
                self.logger.info("Whisper already completed - loading from file")
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}Whisper transcription already completed - loading from file', 'info')
                with open(whisper_path, 'r', encoding='utf-8') as f:
                    transcript_data = json.load(f)
                    # Reconstruct transcription dict from saved transcript
                    transcription = {
                        'language': transcript_data.get('language', 'en'),
                        'text': transcript_data.get('full_text', ''),
                        'segments': transcript_data.get('segments', [])
                    }
            else:
                if recording_id:
                    db.update_transcription_progress(recording_id, {'stage': 'whisper', 'step': 'transcribing'})

                transcription = self.transcribe_audio(audio_wav_path, recording_id=recording_id, segment_number=segment_number)

                # Save Whisper output to intermediate file for resumability
                whisper_output_path = video_path + '.whisper.json'
                with open(whisper_output_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'language': transcription.get('language', 'en'),
                        'full_text': transcription['text'],
                        'segments': transcription['segments']
                    }, f, indent=2, ensure_ascii=False)
                self.logger.info(f"Whisper output saved: {whisper_output_path}")

            # Step 2: Perform speaker diarization (check if already completed)
            diarization_segments = None
            pyannote_diarization = None

            if steps.get('diarization', {}).get('status') == 'completed' and os.path.exists(pyannote_path):
                # Load existing diarization from file
                self.logger.info("Diarization already completed - loading from file")
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}Speaker diarization already completed - loading from file', 'info')

                with open(pyannote_path, 'r', encoding='utf-8') as f:
                    pyannote_diarization = json.load(f)
                    diarization_segments = pyannote_diarization.get('segments', [])
            else:
                if recording_id:
                    db.update_transcription_progress(recording_id, {'stage': 'diarization', 'step': 'analyzing'})

                diarization_segments = self.perform_diarization(audio_wav_path, recording_id=recording_id, segment_number=segment_number)

            # Create pyannote diarization JSON structure (only if not loaded from file)
            if pyannote_diarization is None:
                pyannote_diarization = {
                    'file': video_path,
                    'segments': diarization_segments,
                    'num_speakers': len(set(seg['speaker'] for seg in diarization_segments))
                }

                # Save pyannote diarization data (original output from pyannote API)
                if save_to_file:
                    pyannote_path = video_path + '.diarization.pyannote.json'
                    with open(pyannote_path, 'w', encoding='utf-8') as f:
                        json.dump(pyannote_diarization, f, indent=2, ensure_ascii=False)
                    self.logger.info(f"Pyannote diarization saved: {pyannote_path}")

            # Step 3: Merge transcription with diarization (before Gemini)
            if recording_id:
                prefix = f"Segment {segment_number}: " if segment_number else ""
                db.update_transcription_progress(recording_id, {'stage': 'merging', 'step': 'combining'})
                db.add_transcription_log(recording_id, f'{prefix}Merging transcription with speaker labels', 'info')

            merged_segments = self.merge_transcription_and_diarization(
                transcription, diarization_segments
            )

            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Initial merge completed', 'info')

            # Create merged transcript structure for Gemini
            merged_transcript = {
                'file': video_path,
                'language': transcription.get('language', 'en'),
                'segments': merged_segments,
                'full_text': transcription['text'],
                'num_speakers': len(set(seg['speaker'] for seg in merged_segments))
            }

            # Step 4: Attempt Gemini refinement if enabled (operates on merged transcript with text)
            gemini_transcript = None
            gemini_path = video_path + '.diarization.gemini.json'
            final_transcript = merged_transcript  # Default to merged

            from config import ENABLE_GEMINI_REFINEMENT, GEMINI_API_KEY, GEMINI_MODEL

            if ENABLE_GEMINI_REFINEMENT:
                # Check if Gemini step already completed
                if steps.get('gemini', {}).get('status') == 'completed' and os.path.exists(gemini_path):
                    self.logger.info("Gemini refinement already completed - loading from file")
                    if recording_id:
                        db.add_transcription_log(
                            recording_id,
                            f'{prefix}Gemini refinement already completed - loading from file',
                            'info'
                        )
                    with open(gemini_path, 'r', encoding='utf-8') as f:
                        gemini_transcript = json.load(f)
                        final_transcript = gemini_transcript
                else:
                    # Run Gemini refinement
                    try:
                        # Get meeting context if recording_id available
                        meeting_link = None
                        meeting_title = "Council Meeting"

                        if recording_id:
                            recording = db.get_recording_by_id(recording_id)
                            if recording and recording.get('meeting_id'):
                                # Get meeting details
                                with db.get_db_connection() as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "SELECT title, link FROM meetings WHERE id = ?",
                                        (recording['meeting_id'],)
                                    )
                                    meeting_row = cursor.fetchone()
                                    if meeting_row:
                                        meeting_title = meeting_row['title'] or meeting_title
                                        meeting_link = meeting_row['link']

                            db.add_transcription_log(
                                recording_id,
                                f'{prefix}Attempting Gemini speaker refinement',
                                'info'
                            )

                        # Extract expected speakers from meeting agenda
                        expected_speakers = []

                        # First, check if speakers are already stored in database
                        if recording_id:
                            stored_speakers = db.get_recording_speakers(recording_id)
                            if stored_speakers:
                                expected_speakers = stored_speakers
                                self.logger.info(f"Using {len(expected_speakers)} speakers from database")
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Using {len(expected_speakers)} speakers from database',
                                    'info'
                                )

                        # If no speakers in database, try to fetch from agenda
                        if not expected_speakers and meeting_link:
                            self.logger.info(f"Extracting speakers from agenda: {meeting_link}")
                            if recording_id:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Fetching speaker list from meeting agenda',
                                    'info'
                                )

                            import agenda_parser
                            expected_speakers = agenda_parser.extract_speakers(meeting_link)

                            if expected_speakers:
                                self.logger.info(f"Found {len(expected_speakers)} expected speakers from agenda")
                                if recording_id:
                                    db.add_transcription_log(
                                        recording_id,
                                        f'{prefix}Found {len(expected_speakers)} expected speakers from agenda',
                                        'info'
                                    )
                                    # Save speaker list to database
                                    db.update_recording_speakers(recording_id, expected_speakers)
                            else:
                                self.logger.info("No speakers found in agenda, will use context only")
                                if recording_id:
                                    db.add_transcription_log(
                                        recording_id,
                                        f'{prefix}No speakers found in agenda',
                                        'warning'
                                    )
                        elif not expected_speakers:
                            self.logger.info("No meeting link available for agenda extraction")
                            if recording_id:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}No meeting link available for agenda extraction',
                                    'warning'
                                )

                        # Call Gemini refinement with merged transcript (has text!)
                        self.logger.info("Requesting Gemini speaker refinement")
                        if recording_id:
                            # Log speaker list to database
                            if expected_speakers:
                                # Format as "Role LastName" (e.g., "Councillor Atkinson")
                                formatted_speakers = []
                                for s in expected_speakers:
                                    last_name = s['name'].split()[-1] if s.get('name') else 'Unknown'
                                    role = s.get('role', 'Unknown')
                                    formatted_speakers.append(f"{role} {last_name}")
                                speaker_summary = ', '.join(formatted_speakers)
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Speaker list being sent to Gemini: {speaker_summary}',
                                    'info'
                                )
                            else:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}No speaker list available for Gemini (using context only)',
                                    'info'
                                )
                        import gemini_service

                        gemini_transcript = gemini_service.refine_diarization(
                            merged_transcript,
                            expected_speakers,
                            meeting_title,
                            api_key=GEMINI_API_KEY,
                            model=GEMINI_MODEL
                        )

                        # Check if refinement actually happened (Gemini adds metadata)
                        if gemini_transcript.get('refined_by') == 'gemini':
                            self.logger.info("Gemini refinement completed successfully")
                            if recording_id:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Gemini refinement completed',
                                    'info'
                                )

                            # Save Gemini-refined transcript
                            if save_to_file:
                                gemini_path = video_path + '.diarization.gemini.json'
                                with open(gemini_path, 'w', encoding='utf-8') as f:
                                    json.dump(gemini_transcript, f, indent=2, ensure_ascii=False)
                                self.logger.info(f"Gemini-refined transcript saved: {gemini_path}")

                            # Use Gemini version for final transcript
                            final_transcript = gemini_transcript

                            self.logger.info("Using Gemini-refined speaker labels")
                            if recording_id:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Using Gemini-refined speaker labels',
                                    'info'
                                )
                        else:
                            self.logger.info("Gemini refinement returned original (no changes)")
                            if recording_id:
                                db.add_transcription_log(
                                    recording_id,
                                    f'{prefix}Using pyannote speaker labels (Gemini made no changes)',
                                    'warning'
                                )

                    except Exception as e:
                        self.logger.warning(f"Gemini refinement failed: {e}", exc_info=True)
                        if recording_id:
                            db.add_transcription_log(
                                recording_id,
                                f'{prefix}Gemini refinement failed: {e}',
                                'warning'
                            )
                        self.logger.info("Using merged transcript without Gemini refinement")

            # Update database with diarization paths if recording_id available
            if recording_id and save_to_file:
                db.update_recording_diarization_paths(recording_id, pyannote_path, gemini_path)

            # Also save pyannote-only version for backward compatibility
            if save_to_file:
                legacy_path = video_path + '.diarization.json'
                with open(legacy_path, 'w', encoding='utf-8') as f:
                    json.dump(pyannote_diarization, f, indent=2, ensure_ascii=False)
                self.logger.info(f"Legacy diarization saved: {legacy_path}")

            # Prepare final output (use final_transcript which may be Gemini-refined)
            result = final_transcript

            # Save to file if requested
            if save_to_file:
                if output_path is None:
                    output_path = video_path + '.transcript.json'

                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}Saving transcript to file', 'info')

                self.save_transcript(result, output_path)

            self.logger.info(f"Detected {result['num_speakers']} unique speakers")

            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Transcription complete - detected {result["num_speakers"]} speakers', 'info')
                db.add_recording_log(recording_id, f'{prefix}Transcription complete - detected {result["num_speakers"]} speakers', 'info')

            return result

        finally:
            # Clean up WAV file even on errors
            if os.path.exists(audio_wav_path):
                try:
                    os.remove(audio_wav_path)
                    self.logger.info(f"Cleaned up audio file: {audio_wav_path}")
                except OSError as e:
                    self.logger.warning(f"Could not remove audio file: {e}")

    def save_transcript(self, transcript: Dict, output_path: str):
        """
        Save transcript to JSON file.

        Args:
            transcript: Transcript dictionary
            output_path: Path to save file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Transcript saved to: {output_path}")

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
