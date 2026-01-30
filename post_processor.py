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
        Detect silent periods in the video that likely represent breaks.

        Returns:
            List of (start_time, end_time) tuples in seconds
        """
        msg = f"Analyzing audio for silent periods (threshold: {self.silence_threshold_db}dB, min duration: {self.min_silence_duration}s)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        cmd = [
            self.ffmpeg_command,
            '-i', video_path,
            '-af', f'silencedetect=noise={self.silence_threshold_db}dB:d={self.min_silence_duration}',
            '-f', 'null',
            '-'
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for analysis
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
                msg = f"Found silence: {start:.1f}s - {end:.1f}s (duration: {duration:.1f}s)"
                self.logger.info(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'info')

            return silent_periods

        except subprocess.TimeoutExpired:
            msg = "Analysis timed out"
            self.logger.warning(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'warning')
            return []
        except Exception as e:
            msg = f"Error detecting silent periods: {e}"
            self.logger.error(msg, exc_info=True)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'error')
            return []

    def has_audio(self, video_path: str, recording_id: Optional[int] = None) -> bool:
        """
        Check if the recording has any actual audio content (not just silence).

        Returns:
            True if audio is detected, False if entire file is silent/no audio
        """
        msg = "Checking for audio content in entire file"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        cmd = [
            self.ffmpeg_command,
            '-i', video_path,
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for analysis
            )

            # Parse audio volume from output
            mean_volume = None
            max_volume = None

            for line in result.stderr.split('\n'):
                if 'mean_volume:' in line:
                    try:
                        mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    except (ValueError, IndexError):
                        # Ignore parsing errors in ffmpeg output; leave mean_volume as None
                        pass
                if 'max_volume:' in line:
                    try:
                        max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                    except (ValueError, IndexError):
                        # Ignore parsing errors in ffmpeg output; leave max_volume as None
                        pass

            # If we couldn't detect audio levels or they're extremely low, no audio
            if mean_volume is None and max_volume is None:
                msg = "No audio stream detected"
                self.logger.warning(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'warning')
                return False

            msg = f"Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB"
            self.logger.info(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'info')

            # If audio is very quiet, likely no real audio
            # Use same thresholds as static detection for consistency
            if mean_volume and max_volume:
                if mean_volume < AUDIO_DETECTION_MEAN_THRESHOLD_DB or max_volume < AUDIO_DETECTION_MAX_THRESHOLD_DB:
                    msg = "Audio levels too low - appears to be silent recording"
                    self.logger.warning(msg)
                    if recording_id:
                        db.add_recording_log(recording_id, msg, 'warning')
                    return False

            return True

        except subprocess.TimeoutExpired:
            msg = "Audio detection timed out"
            self.logger.warning(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'warning')
            return True  # Assume has audio if check fails
        except Exception as e:
            msg = f"Error detecting audio: {e}"
            self.logger.error(msg, exc_info=True)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'error')
            return True  # Assume has audio if check fails

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

    def process_recording(self, recording_path: str, recording_id: Optional[int] = None) -> Dict:
        """
        Process a recording: detect breaks and split into segments.

        Args:
            recording_path: Path to the original recording file
            recording_id: Optional database recording ID to track segments

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
                    # Best-effort status update; ignore DB errors
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
                    # Best-effort status update; ignore DB errors
                    pass
            return {"success": False, "error": "Could not determine duration"}

        msg = f"Total duration: {duration:.1f}s ({duration/60:.1f} minutes)"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        # Check if recording has any audio
        if not self.has_audio(recording_path, recording_id):
            msg = "No audio detected in entire recording - removing file"
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

            # Mark recording as failed in database if recording_id provided
            if recording_id:
                try:
                    db.update_recording(
                        recording_id,
                        datetime.now(CALGARY_TZ),
                        'failed',
                        'No audio detected in recording'
                    )
                    # Use 'skipped' status since post-processing successfully determined there was no audio
                    db.update_post_process_status(recording_id, 'skipped', 'No audio detected - file removed')
                    db.add_recording_log(recording_id, 'Recording marked as failed in database', 'info')
                    self.logger.info("Recording marked as failed in database")
                except Exception:
                    # Best-effort status update; ignore DB errors so they don't mask processing result
                    self.logger.warning("Could not update database")

            return {
                "success": False,
                "error": "No audio detected",
                "deleted": True,
                "message": "Recording had no audio and was removed"
            }

        # Detect silent periods (breaks)
        silent_periods = self.detect_silent_periods(recording_path, recording_id)

        # Calculate active segments
        segments = self.calculate_segments(duration, silent_periods)

        if not segments:
            msg = "No segmentation needed - no breaks detected"
            self.logger.info(msg)

            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'completed')
                    db.add_recording_log(recording_id, msg, 'info')
                except Exception:
                    # Best-effort status update; ignore DB errors
                    pass

            return {
                "success": True,
                "segments_created": 0,
                "message": "No breaks detected - no segmentation needed. Use transcribe button to generate transcript."
            }

        # Create output directory for segments
        base_name = os.path.splitext(os.path.basename(recording_path))[0]
        output_dir = os.path.join(os.path.dirname(recording_path), f"{base_name}_segments")
        os.makedirs(output_dir, exist_ok=True)

        if recording_id:
            db.add_recording_log(recording_id, f"Creating {len(segments)} segments", 'info')

        # Copy original to segments folder for safety
        original_dest = os.path.join(output_dir, f"{base_name}_original.mp4")
        msg = f"Preserving original: {original_dest}"
        self.logger.info(msg)
        if recording_id:
            db.add_recording_log(recording_id, msg, 'info')

        try:
            import shutil
            shutil.copy2(recording_path, original_dest)
        except Exception as e:
            self.logger.warning(f"Could not copy original: {e}")

        # Extract segments
        segment_files = []
        for i, (start, end) in enumerate(segments, 1):
            segment_duration = end - start
            output_path = os.path.join(output_dir, f"{base_name}_segment_{i}.mp4")

            msg = f"Extracting segment {i}/{len(segments)}: {start:.1f}s - {end:.1f}s ({segment_duration/60:.1f} min)"
            self.logger.info(msg)
            if recording_id:
                db.add_recording_log(recording_id, msg, 'info')

            if self.extract_segment(recording_path, output_path, start, end):
                file_size_bytes = os.path.getsize(output_path)
                file_size_mb = file_size_bytes / (1024**2)  # MB

                segment_info = {
                    "path": output_path,
                    "segment": i,
                    "start": start,
                    "end": end,
                    "duration": segment_duration,
                    "size_mb": file_size_mb,
                    "size_bytes": file_size_bytes
                }
                segment_files.append(segment_info)

                # Save segment to database if recording_id provided
                if recording_id:
                    try:
                        segment_id = db.create_segment(
                            recording_id=recording_id,
                            segment_number=i,
                            file_path=output_path,
                            start_time=start,
                            end_time=end,
                            duration=segment_duration,
                            file_size_bytes=file_size_bytes
                        )
                        segment_info['db_id'] = segment_id
                        msg = f"Segment {i} created: {file_size_mb:.1f} MB (DB ID: {segment_id})"
                        self.logger.info(msg)
                        db.add_recording_log(recording_id, msg, 'info')
                    except Exception as e:
                        msg = f"Segment {i} created: {file_size_mb:.1f} MB (DB save failed: {e})"
                        self.logger.warning(msg)
                        if recording_id:
                            db.add_recording_log(recording_id, msg, 'warning')
                else:
                    self.logger.info(f"Segment {i} created: {file_size_mb:.1f} MB")
            else:
                msg = f"Failed to create segment {i}"
                self.logger.error(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'error')

        # Note: Transcription is now handled separately via the /transcribe endpoint
        # This allows users to control when transcription happens independently of segmentation

        # Mark recording as segmented and post-processed in database
        if recording_id and len(segment_files) > 0:
            try:
                db.mark_recording_segmented(recording_id)
                db.update_post_process_status(recording_id, 'completed')
                msg = "Recording marked as segmented in database"
                self.logger.info(msg)
                db.add_recording_log(recording_id, msg, 'info')
            except Exception as e:
                msg = f"Could not mark recording as segmented: {e}"
                self.logger.warning(msg)
                if recording_id:
                    db.add_recording_log(recording_id, msg, 'error')
        elif recording_id:
            # Post-processing attempted but no segments created
            try:
                db.update_post_process_status(recording_id, 'completed', 'No segments created')
                db.add_recording_log(recording_id, 'No segments created', 'info')
            except Exception:
                # Best-effort status update; ignore DB errors
                pass

        self.logger.info("========================================")
        self.logger.info("Processing complete")
        self.logger.info(f"Segments folder: {output_dir}")
        self.logger.info(f"Segments created: {len(segment_files)}/{len(segments)}")
        self.logger.info(f"Original preserved: {original_dest}")
        self.logger.info("========================================")

        return {
            "success": True,
            "segments_created": len(segment_files),
            "output_dir": output_dir,
            "segment_files": segment_files,
            "original_preserved": original_dest
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
