#!/usr/bin/env python3
"""
Speaker diarization service using pyannote.ai API.
"""

import os
import time
import json
import logging
import requests
from typing import List, Dict, Optional
from exceptions import DiarizationError


class DiarizationService:
    """Service for speaker diarization using pyannote.ai API."""

    def __init__(self, api_token: Optional[str] = None, segmentation_threshold: float = 0.3, enable_transcription: bool = False):
        """
        Initialize diarization service.

        Args:
            api_token: pyannote.ai API token (required for diarization)
            segmentation_threshold: Threshold for speaker segmentation (0.0-1.0).
                                   Lower values = more speakers detected. Default: 0.3
            enable_transcription: If True, use pyannote STT orchestration for transcription.
                                 If False, only perform diarization. Default: False
        """
        self.logger = logging.getLogger(__name__)
        self.api_token = api_token
        self.segmentation_threshold = segmentation_threshold
        self.enable_transcription = enable_transcription
        self.api_url = "https://api.pyannote.ai/v1/diarize"

    def perform_diarization(
        self,
        audio_path: str,
        recording_id: Optional[int] = None,
        segment_number: Optional[int] = None
    ) -> List[Dict]:
        """
        Perform speaker diarization using pyannote.ai API.

        Args:
            audio_path: Path to audio/video file (preferably WAV)
            recording_id: Optional recording ID for progress logging
            segment_number: Optional segment number for logging

        Returns:
            List of speaker segments with start time, end time, and speaker label
        """
        if not self.api_token:
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

            # Set diarization status to pending
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE recordings SET diarization_status = ? WHERE id = ?",
                    ('pending', recording_id)
                )

            # Check if we already have a media URL for this recording (for retry)
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT pyannote_media_url FROM recordings WHERE id = ?", (recording_id,))
                result = cursor.fetchone()
                existing_media_url = result[0] if result and result[0] else None

            if existing_media_url:
                msg = f"Reusing existing pyannote.ai media URL: {existing_media_url}"
                self.logger.info(msg)
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
                db.add_recording_log(recording_id, f'{prefix}Reusing uploaded audio (no re-upload needed)', 'info')
                # Update progress to show we're not uploading
                db.update_transcription_progress(recording_id, {'stage': 'diarization', 'step': 'preparing'})
                media_url = existing_media_url
        else:
            existing_media_url = None

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        # Step 1 & 2: Upload file (skip if reusing existing URL)
        if not existing_media_url:
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
            presigned_url = upload_data.get('url')

            # Step 2: Upload the audio file to the pre-signed URL
            file_size_bytes = os.path.getsize(audio_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            msg = f"Uploading audio file ({file_size_mb:.1f} MB) to pyannote.ai"
            self.logger.info(msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

            # Upload with progress tracking
            class ProgressFileReader:
                def __init__(self, file_path, recording_id, prefix):
                    self.file_path = file_path
                    self.recording_id = recording_id
                    self.prefix = prefix
                    self.file_size = os.path.getsize(file_path)
                    self.uploaded = 0
                    self.last_logged_percent = -10
                    self._file = open(file_path, 'rb')

                def read(self, size=-1):
                    chunk = self._file.read(size)
                    self.uploaded += len(chunk)

                    # Log progress every 10%
                    percent = int((self.uploaded / self.file_size) * 100)
                    if percent >= self.last_logged_percent + 10:
                        self.last_logged_percent = percent
                        if self.recording_id:
                            import database as db
                            msg = f"{self.prefix}Upload progress: {percent}% ({self.uploaded / (1024*1024):.1f} / {self.file_size / (1024*1024):.1f} MB)"
                            db.add_recording_log(self.recording_id, msg, 'info')

                    return chunk

                def __len__(self):
                    return self.file_size

                def close(self):
                    self._file.close()

            file_reader = ProgressFileReader(audio_path, recording_id, prefix)
            try:
                upload_file_response = requests.put(
                    presigned_url,
                    data=file_reader,
                    headers={"Content-Type": "audio/wav"},
                    timeout=600  # 10 minute timeout for large files
                )
            finally:
                file_reader.close()

            if upload_file_response.status_code not in [200, 204]:
                error_msg = f"Failed to upload file: {upload_file_response.status_code}: {upload_file_response.text}"
                self.logger.error(error_msg)
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                raise DiarizationError(audio_path, error_msg)

            msg = f"Audio file uploaded successfully ({file_size_mb:.1f} MB)"
            self.logger.info(msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

                # Save media URL to database for future reuse
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE recordings SET pyannote_media_url = ?, pyannote_upload_size_mb = ? WHERE id = ?",
                        (media_url, file_size_mb, recording_id)
                    )
                msg = f"Saved pyannote media URL to database: {media_url}"
                self.logger.info(msg)
                db.add_recording_log(recording_id, f'{prefix}Upload complete - URL saved for reuse', 'info')

        # Step 3: Check for existing job ID (resume interrupted job)
        existing_job_id = None
        if recording_id:
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT pyannote_job_id FROM recordings WHERE id = ?",
                    (recording_id,)
                )
                result = cursor.fetchone()
                existing_job_id = result[0] if result and result[0] else None

            if existing_job_id:
                msg = f"Found existing pyannote job (ID: {existing_job_id}). Resuming..."
                self.logger.info(msg)
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
                db.add_recording_log(recording_id, f'{prefix}Resuming existing job (avoiding duplicate credits)', 'info')

                # Set status to running if not already
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE recordings SET diarization_status = ? WHERE id = ?",
                        ('running', recording_id)
                    )

                # Skip to polling
                try:
                    result = self._poll_job(existing_job_id, headers, audio_path, recording_id, segment_number)

                    # Clear job ID and set status to completed
                    with db.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE recordings SET pyannote_job_id = NULL, diarization_status = ? WHERE id = ?",
                            ('completed', recording_id)
                        )
                except Exception as e:
                    # Set status to failed on error
                    with db.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE recordings SET diarization_status = ? WHERE id = ?",
                            ('failed', recording_id)
                        )
                    raise

                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}Speaker diarization completed', 'info')
                    db.add_recording_log(recording_id, f'{prefix}Speaker diarization completed', 'info')

                # Convert API response to list of segments
                segments = []
                diarization_data = result.get('diarization', result.get('segments', []))
                for segment_data in diarization_data:
                    segment = {
                        'start': segment_data['start'],
                        'end': segment_data['end'],
                        'speaker': segment_data['speaker']
                    }
                    if 'confidence' in segment_data:
                        segment['confidence'] = segment_data['confidence']
                    if 'text' in segment_data:
                        segment['text'] = segment_data['text']
                    segments.append(segment)

                return segments

        # Step 4: Submit new diarization job with the media URL
        msg = "Submitting diarization job to pyannote.ai"
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        # Request diarization with confidence scores and optional transcription
        request_body = {
            "url": media_url,
            "confidence": True
        }

        # Add transcription parameter if enabled
        if self.enable_transcription:
            request_body["transcription"] = True
            msg = "Submitting diarization + transcription job to pyannote.ai (STT Orchestration)"
            self.logger.info(msg)
            if recording_id:
                db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        response = requests.post(
            self.api_url,
            headers=headers,
            json=request_body,
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
            # Save job ID and set status to running
            if recording_id:
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE recordings SET pyannote_job_id = ?, diarization_status = ? WHERE id = ?",
                        (job_id, 'running', recording_id)
                    )
                self.logger.info(f"Saved pyannote job ID to database: {job_id}")

            try:
                result = self._poll_job(job_id, headers, audio_path, recording_id, segment_number)

                # Clear job ID and set status to completed
                if recording_id:
                    with db.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE recordings SET pyannote_job_id = NULL, diarization_status = ? WHERE id = ?",
                            ('completed', recording_id)
                        )
            except Exception as e:
                # Set status to failed on error
                if recording_id:
                    with db.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE recordings SET diarization_status = ? WHERE id = ?",
                            ('failed', recording_id)
                        )
                raise

        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}Speaker diarization completed', 'info')
            db.add_recording_log(recording_id, f'{prefix}Speaker diarization completed', 'info')

        # Convert API response to list of segments
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
            # Include transcription text if available (from STT orchestration)
            if 'text' in segment_data:
                segment['text'] = segment_data['text']
            segments.append(segment)

        return segments

    def _poll_job(
        self,
        job_id: str,
        headers: Dict,
        audio_path: str,
        recording_id: Optional[int],
        segment_number: Optional[int]
    ) -> Dict:
        """
        Poll for diarization job completion.

        Args:
            job_id: Job ID to poll
            headers: Request headers
            audio_path: Audio file path (for error messages)
            recording_id: Optional recording ID for logging
            segment_number: Optional segment number for logging

        Returns:
            Job result data

        Raises:
            DiarizationError: If polling fails or times out
        """
        if recording_id:
            import database as db
            prefix = f"Segment {segment_number}: " if segment_number else ""

        msg = f"Diarization job started (Job ID: {job_id}). Processing audio..."
        self.logger.info(msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')

        job_url = f"https://api.pyannote.ai/v1/jobs/{job_id}"
        last_status = None
        max_poll_time = 600  # 10 minutes max
        poll_interval = 10  # Poll every 10 seconds
        max_iterations = max_poll_time // poll_interval
        iteration = 0

        while iteration < max_iterations:
            time.sleep(poll_interval)
            iteration += 1

            try:
                job_response = requests.get(job_url, headers=headers, timeout=10)
                job_response.raise_for_status()
                job_data = job_response.json()

                # Log pertinent information from the poll response
                status = job_data.get('status')
                progress = job_data.get('progress')
                error = job_data.get('error')

                log_parts = [f"Status: {status}"]
                if progress is not None:
                    log_parts.append(f"Progress: {progress}")
                if error:
                    log_parts.append(f"Error: {error}")

                msg = f"Poll #{iteration}: {', '.join(log_parts)}"
                self.logger.info(msg)
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}{msg}', 'info')
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

            if status == 'succeeded':
                return job_data.get('output', {})
            elif status == 'failed':
                error_msg = f"Diarization job failed: {job_data.get('error', 'Unknown error')}"
                self.logger.error(error_msg)
                if recording_id:
                    db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
                raise DiarizationError(audio_path, error_msg)

        # Timeout reached
        error_msg = f"Diarization job timed out after {max_poll_time} seconds"
        self.logger.error(error_msg)
        if recording_id:
            db.add_transcription_log(recording_id, f'{prefix}ERROR: {error_msg}', 'error')
        raise DiarizationError(audio_path, error_msg)
