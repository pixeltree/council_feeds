#!/usr/bin/env python3
"""
Transcription service for Calgary Council Stream Recorder.
Uses Whisper for speech-to-text and pyannote.ai API for speaker diarization.

This is the main entry point that delegates to modular components in the transcription package.
"""

import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from exceptions import WhisperError

# Import modular components
from transcription import AudioProcessor, WhisperService, DiarizationService, TranscriptMerger


class TranscriptionService:
    """Service for transcribing recorded videos with speaker diarization."""

    def __init__(
        self,
        pyannote_api_token: Optional[str] = None,
        pyannote_segmentation_threshold: float = 0.3
    ):
        """
        Initialize transcription service.

        Args:
            pyannote_api_token: pyannote.ai API token (required for transcription + diarization)
            pyannote_segmentation_threshold: Threshold for speaker segmentation (0.0-1.0)
        """
        self.logger = logging.getLogger(__name__)

        # Initialize modular components
        self.audio_processor = AudioProcessor()
        self.diarization_service = DiarizationService(
            api_token=pyannote_api_token,
            segmentation_threshold=pyannote_segmentation_threshold,
            enable_transcription=True  # Always use pyannote for transcription
        )
        self.merger = TranscriptMerger()

        # Keep these for backward compatibility
        self.pyannote_api_token = pyannote_api_token

    def extract_audio_to_wav(
        self,
        video_path: str,
        output_wav_path: Optional[str] = None,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> str:
        """
        Extract audio from video to WAV format.

        Delegates to AudioProcessor.

        Args:
            video_path: Path to video file
            output_wav_path: Optional output path
            recording_id: Optional recording ID for logging
            segment_number: Optional segment number for logging

        Returns:
            Path to extracted WAV file
        """
        return self.audio_processor.extract_audio_to_wav(
            video_path,
            output_wav_path,
            recording_id,
            segment_number
        )


    def perform_diarization(
        self,
        audio_path: str,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> List[Dict]:
        """
        Perform speaker diarization using pyannote.ai API.

        Delegates to DiarizationService.

        Args:
            audio_path: Path to audio/video file
            recording_id: Optional recording ID for logging
            segment_number: Optional segment number for logging

        Returns:
            List of speaker segments
        """
        return self.diarization_service.perform_diarization(
            audio_path,
            recording_id,
            segment_number
        )

    def merge_transcription_and_diarization(
        self,
        transcription: Dict,
        diarization_segments: List[Dict]
    ) -> List[Dict]:
        """
        Merge Whisper transcription with speaker diarization.

        Delegates to TranscriptMerger.

        Args:
            transcription: Whisper transcription result
            diarization_segments: Speaker diarization segments

        Returns:
            List of segments with text and speaker labels
        """
        return self.merger.merge_transcription_and_diarization(
            transcription,
            diarization_segments
        )

    def _find_speaker_for_segment(
        self,
        start: float,
        end: float,
        diarization_segments: List[Dict]
    ) -> Dict:
        """
        Find speaker for a segment (for backward compatibility).

        Delegates to TranscriptMerger.

        Args:
            start: Segment start time
            end: Segment end time
            diarization_segments: List of speaker segments

        Returns:
            Dictionary with speaker label and confidence
        """
        return self.merger._find_speaker_for_segment(start, end, diarization_segments)

    def format_transcript_as_text(self, segments: List[Dict]) -> str:
        """
        Format transcript segments as readable text.

        Delegates to TranscriptMerger.

        Args:
            segments: List of transcript segments with speaker labels

        Returns:
            Formatted transcript string
        """
        return self.merger.format_transcript_as_text(segments)

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
        Whisper and Diarization run in parallel for improved performance.

        Args:
            video_path: Path to video file
            output_path: Optional path to save transcript
            save_to_file: Whether to save results to file
            recording_id: Optional recording ID for tracking
            segment_number: Optional segment number for multi-segment recordings

        Returns:
            Dictionary with transcript segments and metadata

        Raises:
            WhisperError: If video_path does not exist
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

        # Step 1: Run pyannote for transcription + diarization (if not already completed)
        transcription = None
        pyannote_path = video_path + '.diarization.pyannote.json'
        diarization_already_done = steps.get('diarization', {}).get('status') == 'completed' and os.path.exists(pyannote_path)

        diarization_segments = None
        pyannote_diarization = None

        if diarization_already_done:
            # Load existing diarization from file
            self.logger.info("Transcription + diarization already completed - loading from file")
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}Transcription + diarization already completed - loading from file', 'info')

            with open(pyannote_path, 'r', encoding='utf-8') as f:
                pyannote_diarization = json.load(f)
                diarization_segments = pyannote_diarization.get('segments', [])
        else:
            # Run pyannote for both transcription and diarization in one API call
            self.logger.info("Using pyannote for transcription + diarization...")
            if recording_id:
                db.update_transcription_progress(recording_id, {'stage': 'diarization', 'step': 'analyzing'})

            diarization_segments = self.perform_diarization(
                audio_wav_path,
                recording_id=recording_id,
                segment_number=segment_number
            )

        # Extract transcription from diarization segments
        if diarization_segments:
            from config import TRANSCRIPTION_LANGUAGE
            # Build transcription from segments
            transcription = {
                'language': TRANSCRIPTION_LANGUAGE,
                'text': ' '.join(seg.get('text', '') for seg in diarization_segments if seg.get('text')),
                'segments': [
                    {
                        'start': seg['start'],
                        'end': seg['end'],
                        'text': seg.get('text', '')
                    }
                    for seg in diarization_segments if seg.get('text')
                ]
            }

        # Create pyannote diarization JSON structure (only if not loaded from file)
        if pyannote_diarization is None and diarization_segments is not None:
            pyannote_diarization = {
                'file': video_path,
                'segments': diarization_segments,
                'num_speakers': len(set(seg['speaker'] for seg in diarization_segments)) if diarization_segments else 0
            }

        # Save pyannote diarization data (original output from pyannote API)
        # Saved alongside Whisper output for consistent resumability pattern
        if pyannote_diarization and not diarization_already_done and save_to_file:
            pyannote_path = video_path + '.diarization.pyannote.json'
            with open(pyannote_path, 'w', encoding='utf-8') as f:
                json.dump(pyannote_diarization, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Pyannote diarization saved: {pyannote_path}")

        # Step 2: Prepare transcript for Gemini refinement
        # No merge step needed - pyannote already returns combined transcription + diarization
        merged_transcript = {
            'file': video_path,
            'language': transcription.get('language', 'en'),
            'segments': diarization_segments,  # Already have both text and speaker
            'full_text': transcription['text'],
            'num_speakers': len(set(seg['speaker'] for seg in diarization_segments))
        }

        # Step 3: Attempt Gemini refinement if enabled
        final_transcript = self._apply_gemini_refinement(
            merged_transcript,
            video_path,
            steps,
            save_to_file,
            recording_id,
            segment_number
        )

        # Update database with diarization paths if recording_id available
        if recording_id and save_to_file:
            gemini_path = video_path + '.diarization.gemini.json'
            db.update_recording_diarization_paths(recording_id, pyannote_path, gemini_path)

            # Extract and update refined speakers list if Gemini refinement was successful
            if final_transcript.get('refined_by') == 'gemini':
                refined_speakers = set()
                for segment in final_transcript.get('segments', []):
                    speaker = segment.get('speaker')
                    if speaker and not speaker.startswith('SPEAKER_'):
                        # Only include refined speakers (not generic SPEAKER_XX)
                        refined_speakers.add(speaker)

                if refined_speakers:
                    refined_speakers_list = [
                        {
                            'name': speaker,
                            'role': speaker.split()[0] if ' ' in speaker else 'Unknown',
                            'confidence': 'high'
                        }
                        for speaker in sorted(refined_speakers)
                    ]
                    db.update_recording_speakers(recording_id, refined_speakers_list)
                    self.logger.info(f"Updated database with {len(refined_speakers_list)} refined speakers")
                    if recording_id:
                        db.add_recording_log(
                            recording_id,
                            f'Updated speaker list with {len(refined_speakers_list)} refined speakers: {", ".join(sorted(refined_speakers))}',
                            'info'
                        )

        # Also save pyannote-only version for backward compatibility
        if save_to_file:
            legacy_path = video_path + '.diarization.json'
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(pyannote_diarization, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Legacy diarization saved: {legacy_path}")

        # Prepare final output
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

    def _apply_gemini_refinement(
        self,
        merged_transcript: Dict,
        video_path: str,
        steps: Dict,
        save_to_file: bool,
        recording_id: Optional[int],
        segment_number: Optional[int]
    ) -> Dict:
        """
        Apply Gemini speaker refinement if enabled.

        Args:
            merged_transcript: Merged transcript from Whisper + pyannote
            video_path: Path to video file
            steps: Resumability steps dict
            save_to_file: Whether to save to file
            recording_id: Optional recording ID
            segment_number: Optional segment number

        Returns:
            Final transcript (Gemini-refined or original)
        """
        from config import ENABLE_GEMINI_REFINEMENT, GEMINI_API_KEY, GEMINI_MODEL

        if not ENABLE_GEMINI_REFINEMENT:
            return merged_transcript

        if recording_id:
            import database as db

        prefix = f"Segment {segment_number}: " if segment_number else ""
        gemini_path = video_path + '.diarization.gemini.json'

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
                return json.load(f)

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
            expected_speakers = self._get_expected_speakers(
                recording_id,
                meeting_link,
                prefix
            )

            # Log speaker list
            if recording_id and expected_speakers:
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
            elif recording_id:
                db.add_transcription_log(
                    recording_id,
                    f'{prefix}No speaker list available for Gemini (using context only)',
                    'info'
                )

            # Call Gemini refinement
            self.logger.info("Requesting Gemini speaker refinement")
            import gemini_service

            gemini_transcript = gemini_service.refine_diarization(
                merged_transcript,
                expected_speakers,
                meeting_title,
                api_key=GEMINI_API_KEY,
                model=GEMINI_MODEL
            )

            # Check if refinement actually happened
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
                    with open(gemini_path, 'w', encoding='utf-8') as f:
                        json.dump(gemini_transcript, f, indent=2, ensure_ascii=False)
                    self.logger.info(f"Gemini-refined transcript saved: {gemini_path}")

                if recording_id:
                    db.add_transcription_log(
                        recording_id,
                        f'{prefix}Using Gemini-refined speaker labels',
                        'info'
                    )
                return gemini_transcript
            else:
                self.logger.info("Gemini refinement returned original (no changes)")
                if recording_id:
                    db.add_transcription_log(
                        recording_id,
                        f'{prefix}Using pyannote speaker labels (Gemini made no changes)',
                        'warning'
                    )
                return merged_transcript

        except Exception as e:
            self.logger.warning(f"Gemini refinement failed: {e}", exc_info=True)
            if recording_id:
                db.add_transcription_log(
                    recording_id,
                    f'{prefix}Gemini refinement failed: {e}',
                    'warning'
                )
            self.logger.info("Using merged transcript without Gemini refinement")
            return merged_transcript

    def _get_expected_speakers(
        self,
        recording_id: Optional[int],
        meeting_link: Optional[str],
        prefix: str
    ) -> List[Dict]:
        """
        Get expected speakers from database or agenda.

        Args:
            recording_id: Optional recording ID
            meeting_link: Optional meeting link for agenda parsing
            prefix: Log prefix

        Returns:
            List of expected speakers
        """
        expected_speakers = []

        if not recording_id:
            return expected_speakers

        import database as db

        # First, check if speakers are already stored in database
        stored_speakers = db.get_recording_speakers(recording_id)
        if stored_speakers:
            self.logger.info(f"Using {len(stored_speakers)} speakers from database")
            db.add_transcription_log(
                recording_id,
                f'{prefix}Using {len(stored_speakers)} speakers from database',
                'info'
            )
            return stored_speakers

        # If no speakers in database, try to fetch from agenda
        if meeting_link:
            self.logger.info(f"Extracting speakers from agenda: {meeting_link}")
            db.add_transcription_log(
                recording_id,
                f'{prefix}Fetching speaker list from meeting agenda',
                'info'
            )

            import agenda_parser
            expected_speakers = agenda_parser.extract_speakers(meeting_link)

            if expected_speakers:
                self.logger.info(f"Found {len(expected_speakers)} expected speakers from agenda")
                db.add_transcription_log(
                    recording_id,
                    f'{prefix}Found {len(expected_speakers)} expected speakers from agenda',
                    'info'
                )
                # Save speaker list to database
                db.update_recording_speakers(recording_id, expected_speakers)
            else:
                self.logger.info("No speakers found in agenda, will use context only")
                db.add_transcription_log(
                    recording_id,
                    f'{prefix}No speakers found in agenda',
                    'warning'
                )
        else:
            self.logger.info("No meeting link available for agenda extraction")
            db.add_transcription_log(
                recording_id,
                f'{prefix}No meeting link available for agenda extraction',
                'warning'
            )

        return expected_speakers

    def save_transcript(self, transcript: Dict, output_path: str) -> None:
        """
        Save transcript to JSON file.

        Args:
            transcript: Transcript dictionary
            output_path: Path to save file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Transcript saved to: {output_path}")
