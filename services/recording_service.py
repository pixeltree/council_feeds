#!/usr/bin/env python3
"""
Recording service for orchestrating stream recording operations.
"""

import os
import logging
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from transcription_service import TranscriptionService
    from post_processor import PostProcessor

import database as db
from exceptions import RecordingStorageError
from resource_managers import recording_process
from config import (
    CALGARY_TZ,
    OUTPUT_DIR,
    FFMPEG_COMMAND,
    ENABLE_POST_PROCESSING,
    POST_PROCESS_SILENCE_THRESHOLD_DB,
    POST_PROCESS_MIN_SILENCE_DURATION,
    ENABLE_TRANSCRIPTION,
    PYANNOTE_API_TOKEN,
    ENABLE_SEGMENTED_RECORDING,
)

from .stream_service import StreamService
from .recording_path_manager import RecordingPathManager
from .ffmpeg_command_builder import FFmpegCommandBuilder
from .recording_validator import RecordingValidator
from .segment_merger import SegmentMerger
from .recording_monitor import RecordingMonitor


class RecordingService:
    """Service for recording streams using ffmpeg."""

    def __init__(
        self,
        output_dir: str = OUTPUT_DIR,
        ffmpeg_command: str = FFMPEG_COMMAND,
        timezone: Any = CALGARY_TZ,
        stream_service: Optional[StreamService] = None,
        transcription_service: Optional["TranscriptionService"] = None,
        post_processor: Optional["PostProcessor"] = None
    ):
        self.output_dir = output_dir
        self.ffmpeg_command = ffmpeg_command
        self.timezone = timezone
        self.stream_service = stream_service or StreamService()
        self.transcription_service = transcription_service
        self.post_processor = post_processor
        self.current_process: Optional[subprocess.Popen[bytes]] = None
        self.current_recording_id: Optional[int] = None
        self.logger = logging.getLogger(__name__)

        # Initialize helper components
        self.path_manager = RecordingPathManager(output_dir)
        self.command_builder = FFmpegCommandBuilder(ffmpeg_command)
        self.validator = RecordingValidator(ffmpeg_command)
        self.segment_merger = SegmentMerger(output_dir, ffmpeg_command)
        self.monitor = RecordingMonitor(self.stream_service, self.validator)

    def _find_meeting_id(self, current_meeting: Optional[Dict[str, Any]]) -> Optional[int]:
        """Find associated meeting ID in database.

        Args:
            current_meeting: Current meeting information

        Returns:
            Meeting ID if found, None otherwise
        """
        if not current_meeting:
            return None

        db_meeting = db.find_meeting_by_datetime(current_meeting['datetime'])
        if db_meeting:
            self.logger.info(f"Associated with meeting: {db_meeting['title']}")
            return int(db_meeting['id'])
        return None

    def _create_recording_record(
        self,
        meeting_id: Optional[int],
        output_file: str,
        stream_url: str,
        start_time: datetime
    ) -> int:
        """Create recording record in database and initialize tracking.

        Args:
            meeting_id: Associated meeting ID
            output_file: Path to output file
            stream_url: Stream URL being recorded
            start_time: Recording start time

        Returns:
            Recording ID
        """
        recording_id_result = db.create_recording(meeting_id, output_file, stream_url, start_time)
        if recording_id_result is None:
            raise RecordingStorageError(output_file, 'create', 'Failed to create recording in database')
        recording_id = int(recording_id_result)
        self.current_recording_id = recording_id
        self.monitor.reset_stop()
        db.log_stream_status(stream_url, 'live', meeting_id, 'Recording started')
        return recording_id

    def _run_post_processing(self, output_file: str, recording_id: int) -> bool:
        """Run post-processing on the recording.

        Args:
            output_file: Path to the recording file
            recording_id: Database ID of the recording

        Returns:
            True if post-processing deleted the file (skip transcription), False otherwise
        """
        if not ENABLE_POST_PROCESSING:
            return False

        self.logger.info("[EXPERIMENTAL] Post-processing enabled - splitting recording into segments")
        try:
            # Use injected post processor or create a default one
            if self.post_processor is None:
                from post_processor import PostProcessor
                processor = PostProcessor(
                    silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
                    min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION,
                    ffmpeg_command=self.ffmpeg_command
                )
            else:
                processor = self.post_processor

            result = processor.process_recording(output_file, recording_id)
            if result.get('success'):
                self.logger.info(f"[POST-PROCESS] Successfully created {result.get('segments_created', 0)} segments")
            elif result.get('deleted'):
                self.logger.warning(f"[POST-PROCESS] Recording removed: {result.get('message', 'No audio detected')}")
                return True  # File was deleted
            else:
                self.logger.error(f"[POST-PROCESS] Processing failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            self.logger.error(f"[POST-PROCESS] Error during post-processing: {e}", exc_info=True)
            self.logger.info("[POST-PROCESS] Original recording preserved")

        return False

    def _run_transcription(self, output_file: str, recording_id: int) -> None:
        """Run transcription on the recording.

        Args:
            output_file: Path to the recording file
            recording_id: Database ID of the recording
        """
        if not ENABLE_TRANSCRIPTION:
            return

        self.logger.info("[TRANSCRIPTION] Transcription enabled - generating transcript with speaker diarization")
        try:
            # Use injected transcription service or create a default one
            if self.transcription_service is None:
                from transcription_service import TranscriptionService
                from config import PYANNOTE_SEGMENTATION_THRESHOLD
                transcriber = TranscriptionService(
                    pyannote_api_token=PYANNOTE_API_TOKEN,
                    pyannote_segmentation_threshold=PYANNOTE_SEGMENTATION_THRESHOLD
                )
            else:
                transcriber = self.transcription_service

            # Transcribe the video
            transcript_result = transcriber.transcribe_with_speakers(output_file)

            # Save formatted text version
            text_output = output_file + '.transcript.txt'
            formatted_text = transcriber.format_transcript_as_text(transcript_result['segments'])
            with open(text_output, 'w', encoding='utf-8') as f:
                f.write(formatted_text)

            self.logger.info(f"[TRANSCRIPTION] Successfully transcribed with {transcript_result['num_speakers']} speakers")
            self.logger.info(f"[TRANSCRIPTION] Transcript saved to: {text_output}")

            # Update database with transcript path
            if recording_id:
                db.update_recording_transcript(recording_id, output_file + '.transcript.json')

        except Exception as e:
            self.logger.error(f"[TRANSCRIPTION] Error during transcription: {e}", exc_info=True)
            self.logger.info("[TRANSCRIPTION] Recording preserved, transcription skipped")

    def record_stream(
        self,
        stream_url: str,
        current_meeting: Optional[Dict] = None
    ) -> bool:
        """Record the stream to a file using ffmpeg, tracking in database."""
        start_time = datetime.now(self.timezone)
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")

        # Determine output paths
        output_file, output_pattern, format_ext = self.path_manager.determine_output_paths(timestamp)
        self.path_manager.ensure_output_directory(output_file)

        if output_pattern:
            self.logger.info(f"Starting segmented recording: {output_pattern}")
        else:
            self.logger.info(f"Starting recording: {output_file}")

        # Find associated meeting and create recording record
        meeting_id = self._find_meeting_id(current_meeting)
        recording_id = self._create_recording_record(meeting_id, output_file, stream_url, start_time)

        # Build ffmpeg command
        cmd = self.command_builder.build_command(stream_url, output_file, output_pattern, format_ext)

        try:
            with recording_process(cmd, timeout=10) as process:
                self.current_process = process
                self.logger.info(f"Recording started (PID: {process.pid})")

                # Monitor the process
                self.monitor.monitor_recording(
                    process,
                    stream_url,
                    output_file,
                    output_pattern,
                    meeting_id
                )

            end_time = datetime.now(self.timezone)

            # Clean up process tracking
            self.current_process = None
            self.current_recording_id = None

            # If segmented, merge segments into single file
            if ENABLE_SEGMENTED_RECORDING and output_pattern:
                self.logger.info("Merging recording segments...")
                merged_file = self.segment_merger.merge_segments(
                    output_pattern,
                    output_file,
                    timestamp
                )
                if merged_file is None:
                    # Merge actually failed (not just no segments)
                    error_msg = "Could not merge segments; marking recording as failed"
                    self.logger.error(error_msg)
                    db.update_recording(recording_id, end_time, 'failed', error_msg)
                    db.log_stream_status(stream_url, 'error', meeting_id, error_msg)
                    return False
                else:
                    output_file = merged_file
                    self.logger.info(f"Recording saved: {output_file}")
            else:
                self.logger.info(f"Recording saved: {output_file}")

            # Check if recording has any content
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                duration = int((end_time - start_time).total_seconds())
                self.logger.info(f"Duration: {duration}s, Size: {file_size / (1024**2):.1f} MB")

            # Validate recording has content
            has_content = self.validator.validate_recording_content(output_file, recording_id, end_time)
            if not has_content:
                return True  # Return success since we handled it properly

            # Update recording status in database as completed
            db.update_recording(recording_id, end_time, 'completed')

            # Run post-processing if enabled
            file_was_deleted = self._run_post_processing(output_file, recording_id)
            if file_was_deleted:
                return True  # Skip transcription since file was deleted

            # Run transcription if enabled
            self._run_transcription(output_file, recording_id)

            return True

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error during recording: {error_msg}", exc_info=True)

            # Clean up process tracking
            self.current_process = None
            self.current_recording_id = None

            # Update recording as failed
            db.update_recording(recording_id, datetime.now(self.timezone), 'failed', error_msg)
            db.log_stream_status(stream_url, 'error', meeting_id, error_msg)

            return False

    def stop_recording(self) -> bool:
        """Request the current recording to stop."""
        if self.current_process and self.current_process.poll() is None:
            self.monitor.request_stop()
            return True
        return False

    def is_recording(self) -> bool:
        """Check if a recording is currently in progress."""
        return self.current_process is not None and self.current_process.poll() is None
