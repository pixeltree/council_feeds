#!/usr/bin/env python3
"""
Post-processing service for splitting council meeting recordings into segments.
Removes silent/break periods and creates separate files for each active segment.

EXPERIMENTAL: This is a best-effort approach using silence detection.
Original recordings are always preserved.
"""

import os
import subprocess
import json
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import re
import tempfile
import database as db
from config import CALGARY_TZ, AUDIO_DETECTION_MEAN_THRESHOLD_DB, AUDIO_DETECTION_MAX_THRESHOLD_DB


class PostProcessor:
    """Post-processes recordings to detect and split segments."""

    def __init__(
        self,
        silence_threshold_db: int = -40,
        min_silence_duration: int = 120,  # 2 minutes
        ffmpeg_command: str = "ffmpeg",
        ffprobe_command: str = "ffprobe"
    ):
        """
        Initialize post-processor.

        Args:
            silence_threshold_db: Audio level (in dB) to consider as silence.
                                 More negative = stricter (e.g., -50dB is very quiet)
            min_silence_duration: Minimum silence duration (seconds) to split on.
                                 Breaks are typically 10-30 minutes.
            ffmpeg_command: Path to ffmpeg binary
            ffprobe_command: Path to ffprobe binary
        """
        self.silence_threshold_db = silence_threshold_db
        self.min_silence_duration = min_silence_duration
        self.ffmpeg_command = ffmpeg_command
        self.ffprobe_command = ffprobe_command
        self.logger = logging.getLogger(__name__)

    def detect_silent_periods(self, video_path: str, recording_id: Optional[int] = None) -> List[Tuple[float, float]]:
        """
        Detect periods without speech (breaks) in the video.

        Uses speech frequency filtering to detect breaks even when background music is present.
        Filters to speech frequencies (300-3400 Hz) before silence detection, so music-only
        periods will be detected as "silent" (no speech).

        Returns:
            List of (start_time, end_time) tuples in seconds representing breaks
        """
        msg = f"Analyzing for speech breaks (speech freq filter + silence threshold: {self.silence_threshold_db}dB, min duration: {self.min_silence_duration}s)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        # Apply speech frequency filter BEFORE silence detection
        # This way, music-only breaks will be detected as "silent" (no speech)
        cmd = [
            self.ffmpeg_command,
            '-i', video_path,
            '-af', f'highpass=f=300,lowpass=f=3400,silencedetect=noise={self.silence_threshold_db}dB:d={self.min_silence_duration}',
            '-f', 'null',
            '-'
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout (increased for large files)
            )

            # Parse silence detection output from stderr
            silence_starts = []
            silence_ends = []

            for line in result.stderr.split('\n'):
                if 'silencedetect' in line:
                    # Look for silence_start
                    start_match = re.search(r'silence_start: ([\d.]+)', line)
                    if start_match:
                        silence_starts.append(float(start_match.group(1)))

                    # Look for silence_end
                    end_match = re.search(r'silence_end: ([\d.]+)', line)
                    if end_match:
                        silence_ends.append(float(end_match.group(1)))

            # Pair up starts and ends
            silent_periods = []
            for start, end in zip(silence_starts, silence_ends):
                duration = end - start
                silent_periods.append((start, end))
                msg = f"Found speech break: {start:.1f}s - {end:.1f}s (duration: {duration:.1f}s)"
                self.logger.info(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'info')

            if not silent_periods:
                msg = "No speech breaks detected - continuous speech throughout recording"
                self.logger.info(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'info')

            return silent_periods

        except subprocess.TimeoutExpired:
            msg = "Speech break analysis timed out - video may be very large"
            self.logger.warning(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'warning')
            return []
        except Exception as e:
            msg = f"Error detecting speech breaks: {e}"
            self.logger.error(msg, exc_info=True)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'error')
            return []

    def _parse_volume_output(self, stderr_output: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Parse mean and max volume from ffmpeg volumedetect output.

        Args:
            stderr_output: stderr from ffmpeg volumedetect command

        Returns:
            Tuple of (mean_volume, max_volume) in dB, or (None, None) if not found
        """
        mean_volume = None
        max_volume = None

        for line in stderr_output.split('\n'):
            if 'mean_volume:' in line:
                try:
                    mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                except (ValueError, IndexError):
                    pass
            if 'max_volume:' in line:
                try:
                    max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                except (ValueError, IndexError):
                    pass

        return mean_volume, max_volume

    def _detect_speech_in_sample(self, video_path: str, position: float, duration: int,
                                   recording_id: Optional[int] = None) -> bool:
        """
        Detect if a sample contains human speech (not just music or noise).

        Uses ffmpeg to extract audio and analyze speech characteristics:
        - Applies highpass/lowpass filters to isolate speech frequencies (300-3400 Hz)
        - Checks for sufficient volume in the speech frequency range

        Args:
            video_path: Path to video file
            position: Start position in seconds
            duration: Sample duration in seconds
            recording_id: Optional recording ID for logging

        Returns:
            True if speech is detected, False otherwise
        """
        # Extract audio sample and filter for speech frequencies
        # Human speech is primarily 300-3400 Hz, music has much wider range
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_audio:
            temp_path = temp_audio.name

        try:
            # Extract audio with speech frequency filter
            extract_cmd = [
                self.ffmpeg_command,
                '-ss', str(position),
                '-i', video_path,
                '-t', str(duration),
                '-af', 'highpass=f=300,lowpass=f=3400,volume=2.0',  # Speech frequency range
                '-ar', '16000',  # 16kHz sample rate sufficient for speech
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                temp_path
            ]

            result = subprocess.run(
                extract_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0 or not os.path.exists(temp_path):
                return False

            # Check if filtered audio has significant volume (indicates speech)
            volume_cmd = [
                self.ffmpeg_command,
                '-i', temp_path,
                '-af', 'volumedetect',
                '-f', 'null',
                '-'
            ]

            volume_result = subprocess.run(
                volume_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            mean_volume, max_volume = self._parse_volume_output(volume_result.stderr)

            # If speech frequencies have significant volume, likely contains speech
            # Use more lenient thresholds since we've already filtered to speech range
            if mean_volume and max_volume:
                speech_detected = mean_volume > -50 and max_volume > -30
                return speech_detected

            return False

        except Exception as e:
            self.logger.debug(f"Speech detection error: {e}")
            return False
        finally:
            # Clean up temp file
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except:
                pass

    def has_audio(self, video_path: str, recording_id: Optional[int] = None) -> bool:
        """
        Check if the recording has any actual speech content (not just music/silence).

        Uses interval sampling with speech detection: analyzes 2 minutes every 30 minutes.
        Specifically detects human speech frequencies (300-3400 Hz) to ignore background music.

        Returns:
            True if speech is detected in any sample, False if no speech found
        """
        duration = self.get_video_duration(video_path, recording_id)
        if duration == 0:
            msg = "Could not determine video duration"
            self.logger.warning(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'warning')
            return True  # Assume has audio if we can't check

        # Sample every 30 minutes, taking 2 minutes at each position
        sample_interval = 30 * 60  # 30 minutes in seconds
        sample_duration = 120  # 2 minutes

        sample_positions = []
        position = 0
        while position < duration:
            sample_positions.append(position)
            position += sample_interval

        # Always sample the end if not already covered
        if len(sample_positions) == 0 or duration - sample_positions[-1] > sample_duration:
            sample_positions.append(max(0, duration - sample_duration))

        msg = f"Checking for speech in {len(sample_positions)} positions (2min each, every 30min)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        for i, position in enumerate(sample_positions, 1):
            try:
                # Use speech detection instead of simple volume detection
                has_speech = self._detect_speech_in_sample(video_path, position, sample_duration, recording_id)

                if has_speech:
                    msg = f"Speech detected in sample {i}/{len(sample_positions)} at {position:.0f}s"
                    self.logger.info(msg)
                    if recording_id:
                        db.add_recording_log(recording_id, msg, 'info')
                    return True
                else:
                    msg = f"Sample {i}/{len(sample_positions)} at {position:.0f}s: No speech detected (may have music/silence)"
                    self.logger.debug(msg)

            except subprocess.TimeoutExpired:
                msg = f"Sample {i}/{len(sample_positions)} timed out, continuing with next sample"
                self.logger.warning(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'warning')
                continue
            except Exception as e:
                msg = f"Error analyzing sample {i}/{len(sample_positions)}: {e}"
                self.logger.error(msg, exc_info=True)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'error')
                continue

        # All samples were checked and none had speech
        msg = "No speech detected in any sample - appears to be recording without voices"
        self.logger.warning(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'warning')
        return False

    def get_video_duration(self, video_path: str, recording_id: Optional[int] = None) -> float:
        """Get total duration of video in seconds."""
        # First try to get duration from format
        cmd = [
            self.ffprobe_command,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                self.logger.error(f"ffprobe error: {result.stderr}")
                return 0
            data = json.loads(result.stdout)
            if 'format' in data and 'duration' in data['format']:
                return float(data['format']['duration'])
        except json.JSONDecodeError as e:
            self.logger.warning(f"Could not parse ffprobe output: {e}")
        except Exception as e:
            self.logger.warning(f"Error getting format duration: {e}")

        # If format duration not available, try decoding the file to get duration
        # This works for files with incomplete metadata
        msg = "Format duration not available, calculating from file"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')
        cmd = [
            self.ffprobe_command,
            '-v', 'error',
            '-count_packets',
            '-show_entries', 'stream=duration,nb_read_packets',
            '-of', 'json',
            video_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                self.logger.error(f"ffprobe error: {result.stderr}")
                return 0

            data = json.loads(result.stdout)

            # Try to get duration from streams
            if 'streams' in data:
                for stream in data['streams']:
                    if stream.get('codec_type') == 'video' and 'duration' in stream:
                        duration = float(stream['duration'])
                        if duration > 0:
                            self.logger.info(f"Got duration from video stream: {duration}s")
                            return duration

            # If still no duration, use ffmpeg to decode and count frames
            self.logger.info("Calculating duration by decoding file (may take a while)")
            cmd = [
                self.ffmpeg_command,
                '-i', video_path,
                '-f', 'null',
                '-'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Parse duration from ffmpeg output
            duration_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', result.stderr)
            if duration_match:
                hours, minutes, seconds = duration_match.groups()
                duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                self.logger.info(f"Calculated duration: {duration}s")
                return duration

        except subprocess.TimeoutExpired:
            self.logger.warning("Duration calculation timed out")
        except Exception as e:
            self.logger.warning(f"Could not get video duration: {e}")

        return 0

    def calculate_segments(self, duration: float, silent_periods: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Calculate active segments (non-silent periods) to extract.

        Args:
            duration: Total video duration in seconds
            silent_periods: List of (start, end) tuples for silent periods

        Returns:
            List of (start, end) tuples for active segments
        """
        if not silent_periods:
            self.logger.info("No breaks detected - keeping original file")
            return []

        segments: List[Tuple[float, float]] = []
        last_end: float = 0.0

        for silence_start, silence_end in silent_periods:
            # Add segment before this silence (if significant)
            if silence_start - last_end > 30:  # At least 30 seconds of content
                segments.append((last_end, silence_start))
            last_end = silence_end

        # Add final segment after last silence
        if duration - last_end > 30:
            segments.append((last_end, duration))

        return segments

    def extract_segment(self, input_path: str, output_path: str, start: float, end: float) -> bool:
        """
        Extract a segment from the video without re-encoding.

        Args:
            input_path: Source video file
            output_path: Output file for segment
            start: Start time in seconds
            end: End time in seconds

        Returns:
            True if successful
        """
        duration = end - start

        cmd = [
            self.ffmpeg_command,
            '-i', input_path,
            '-ss', str(start),
            '-t', str(duration),
            '-c', 'copy',  # No re-encoding
            '-avoid_negative_ts', '1',
            output_path
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=duration * 2)
            return True
        except subprocess.TimeoutExpired:
            self.logger.error("Error extracting segment: timeout")
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error extracting segment: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error extracting segment: {e}", exc_info=True)
            return False

    def extract_wav(self, recording_path: str, recording_id: Optional[int] = None) -> Optional[str]:
        """
        Extract WAV audio from video recording for transcription.

        Args:
            recording_path: Path to the original recording file
            recording_id: Optional database recording ID for logging

        Returns:
            Path to extracted WAV file, or None if extraction failed
        """
        base_name = os.path.splitext(recording_path)[0]
        wav_path = f"{base_name}.wav"

        # Skip if WAV already exists
        if os.path.exists(wav_path):
            msg = f"WAV file already exists: {wav_path}"
            self.logger.info(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'info')
            return wav_path

        msg = "Extracting audio to WAV format (16kHz mono for transcription)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        cmd = [
            self.ffmpeg_command,
            '-i', recording_path,
            '-ar', '16000',  # 16kHz sample rate (sufficient for speech)
            '-ac', '1',      # Mono
            '-c:a', 'pcm_s16le',  # 16-bit PCM
            '-y',  # Overwrite if exists
            wav_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout for large files
            )

            if result.returncode != 0:
                msg = f"FFmpeg error: {result.stderr}"
                self.logger.error(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'error')
                return None

            if os.path.exists(wav_path):
                file_size_mb = os.path.getsize(wav_path) / (1024**2)
                msg = f"WAV extracted successfully: {wav_path} ({file_size_mb:.1f} MB)"
                self.logger.info(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'info')
                return wav_path
            else:
                msg = "WAV file was not created"
                self.logger.error(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'error')
                return None

        except subprocess.TimeoutExpired:
            msg = "WAV extraction timed out (file may be very large)"
            self.logger.error(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'error')
            return None
        except Exception as e:
            msg = f"Error extracting WAV: {e}"
            self.logger.error(msg, exc_info=True)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'error')
            return None

    def process_recording(self, recording_path: str, recording_id: Optional[int] = None) -> Dict:
        """
        Process a recording: extract WAV audio for transcription.

        Args:
            recording_path: Path to the original recording file
            recording_id: Optional database recording ID to track progress

        Returns:
            Dictionary with processing results
        """
        self.logger.info("========================================")
        self.logger.info("Starting post-processing")
        self.logger.info(f"Input: {recording_path}")
        self.logger.info("========================================")

        # Mark as processing in database
        if recording_id:
            try:
                db.update_post_process_status(recording_id, 'processing')
                db.add_recording_log(recording_id, 'Starting post-processing', 'info')
            except Exception as e:
                self.logger.warning(f"Could not update status: {e}")

        if not os.path.exists(recording_path):
            msg = f"File not found: {recording_path}"
            self.logger.error(msg)
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'failed', 'File not found')
                    db.add_recording_log(recording_id, msg, 'error')
                except Exception:
                    pass
            return {"success": False, "error": "File not found"}

        # Get video duration
        duration = self.get_video_duration(recording_path, recording_id)
        if duration == 0:
            msg = "Could not determine video duration"
            self.logger.error(msg)
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'failed', msg)
                    db.add_recording_log(recording_id, msg, 'error')
                except Exception:
                    pass
            return {"success": False, "error": "Could not determine duration"}

        msg = f"Total duration: {duration:.1f}s ({duration/60:.1f} minutes)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        # Check if recording has any speech
        if not self.has_audio(recording_path, recording_id):
            msg = "No speech detected in recording - removing file"
            self.logger.warning(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'warning')

            # Delete the recording file
            try:
                os.remove(recording_path)
                msg = f"Deleted recording file: {recording_path}"
                self.logger.info(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'info')
            except OSError as e:
                msg = f"Could not delete file: {e}"
                self.logger.warning(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'warning')

            # Mark recording as failed in database
            if recording_id:
                try:
                    db.update_recording(
                        recording_id,
                        datetime.now(CALGARY_TZ),
                        'failed',
                        'No speech detected in recording'
                    )
                    db.update_post_process_status(recording_id, 'skipped', 'No speech detected - file removed')
                    db.add_recording_log(recording_id, 'Recording marked as failed in database', 'info')
                    self.logger.info("Recording marked as failed in database")
                except Exception:
                    self.logger.warning("Could not update database")

            return {
                "success": False,
                "error": "No speech detected",
                "deleted": True,
                "message": "Recording had no speech and was removed"
            }

        # Extract WAV audio for transcription
        wav_path = self.extract_wav(recording_path, recording_id)

        if not wav_path:
            msg = "Failed to extract WAV audio"
            self.logger.error(msg)
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'failed', msg)
                    db.add_recording_log(recording_id, msg, 'error')
                except Exception:
                    pass
            return {"success": False, "error": "WAV extraction failed"}

        # Store WAV path in database
        if recording_id:
            try:
                with db.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE recordings SET wav_path = ? WHERE id = ?",
                        (wav_path, recording_id)
                    )
                msg = f"WAV path saved to database: {wav_path}"
                self.logger.info(msg)
                db.add_recording_log(recording_id, msg, 'info')
            except Exception as e:
                msg = f"Could not save WAV path to database: {e}"
                self.logger.warning(msg)

        # Mark post-processing as completed
        if recording_id:
            try:
                db.update_post_process_status(recording_id, 'completed')
                db.add_recording_log(recording_id, 'Post-processing completed - WAV ready for transcription', 'info')
            except Exception:
                pass

        self.logger.info("========================================")
        self.logger.info("Post-processing complete")
        self.logger.info(f"WAV file: {wav_path}")
        self.logger.info("Ready for transcription")
        self.logger.info("========================================")

        return {
            "success": True,
            "wav_path": wav_path,
            "message": "WAV extraction completed. Ready for transcription."
        }


if __name__ == "__main__":
    # Example usage / testing
    import sys

    # Set up basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    if len(sys.argv) < 2:
        logger.error("Usage: python post_processor.py <video_file>")
        sys.exit(1)

    video_file = sys.argv[1]
    processor = PostProcessor()
    result = processor.process_recording(video_file)

    if result["success"]:
        logger.info(f"Success! Created {result.get('segments_created', 0)} segments")
    else:
        logger.error(f"Failed: {result.get('error', 'Unknown error')}")
