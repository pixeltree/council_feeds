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

    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize diarization service.

        Args:
            api_token: pyannote.ai API token (required for diarization)
        """
        self.logger = logging.getLogger(__name__)
        self.api_token = api_token
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

        headers = {
            "Authorization": f"Bearer {self.api_token}",
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
        presigned_url = upload_data.get('url')

        # Step 2: Upload the audio file to the pre-signed URL
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
            self.api_url,
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
            result = self._poll_job(job_id, headers, audio_path, recording_id, segment_number)

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
