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
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import re
import database as db


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

    def detect_silent_periods(self, video_path: str) -> List[Tuple[float, float]]:
        """
        Detect silent periods in the video that likely represent breaks.

        Returns:
            List of (start_time, end_time) tuples in seconds
        """
        print(f"[POST-PROCESS] Analyzing audio for silent periods...")
        print(f"[POST-PROCESS] Threshold: {self.silence_threshold_db}dB, Min duration: {self.min_silence_duration}s")

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
                print(f"[POST-PROCESS] Found silence: {start:.1f}s - {end:.1f}s (duration: {duration:.1f}s)")

            return silent_periods

        except subprocess.TimeoutExpired:
            print(f"[POST-PROCESS] Warning: Analysis timed out")
            return []
        except Exception as e:
            print(f"[POST-PROCESS] Error detecting silent periods: {e}")
            return []

    def has_audio(self, video_path: str) -> bool:
        """
        Check if the recording has any actual audio content (not just silence).

        Returns:
            True if audio is detected, False if entire file is silent/no audio
        """
        print(f"[POST-PROCESS] Checking for audio content in entire file...")

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
                    except:
                        pass
                if 'max_volume:' in line:
                    try:
                        max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                    except:
                        pass

            # If we couldn't detect audio levels or they're extremely low, no audio
            if mean_volume is None and max_volume is None:
                print(f"[POST-PROCESS] No audio stream detected")
                return False

            print(f"[POST-PROCESS] Audio levels - Mean: {mean_volume}dB, Max: {max_volume}dB")

            # If audio is very quiet (below -50dB mean or -30dB max), likely no real audio
            # Actual meetings have speech typically above -30dB mean
            if mean_volume and max_volume:
                if mean_volume < -50 or max_volume < -30:
                    print(f"[POST-PROCESS] Audio levels too low - appears to be silent recording")
                    return False

            return True

        except subprocess.TimeoutExpired:
            print(f"[POST-PROCESS] Warning: Audio detection timed out")
            return True  # Assume has audio if check fails
        except Exception as e:
            print(f"[POST-PROCESS] Error detecting audio: {e}")
            return True  # Assume has audio if check fails

    def get_video_duration(self, video_path: str) -> float:
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
                print(f"[POST-PROCESS] ffprobe error: {result.stderr}")
                return 0
            data = json.loads(result.stdout)
            if 'format' in data and 'duration' in data['format']:
                return float(data['format']['duration'])
        except json.JSONDecodeError as e:
            print(f"[POST-PROCESS] Warning: Could not parse ffprobe output: {e}")
        except Exception as e:
            print(f"[POST-PROCESS] Warning: Error getting format duration: {e}")

        # If format duration not available, try decoding the file to get duration
        # This works for files with incomplete metadata
        print(f"[POST-PROCESS] Format duration not available, calculating from file...")
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
                print(f"[POST-PROCESS] ffprobe error: {result.stderr}")
                return 0

            data = json.loads(result.stdout)

            # Try to get duration from streams
            if 'streams' in data:
                for stream in data['streams']:
                    if stream.get('codec_type') == 'video' and 'duration' in stream:
                        duration = float(stream['duration'])
                        if duration > 0:
                            print(f"[POST-PROCESS] Got duration from video stream: {duration}s")
                            return duration

            # If still no duration, use ffmpeg to decode and count frames
            print(f"[POST-PROCESS] Calculating duration by decoding file (may take a while)...")
            cmd = [
                self.ffmpeg_command,
                '-i', video_path,
                '-f', 'null',
                '-'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Parse duration from ffmpeg output
            import re
            duration_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', result.stderr)
            if duration_match:
                hours, minutes, seconds = duration_match.groups()
                duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                print(f"[POST-PROCESS] Calculated duration: {duration}s")
                return duration

        except Exception as e:
            print(f"[POST-PROCESS] Warning: Could not get video duration: {e}")

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
            print("[POST-PROCESS] No breaks detected - keeping original file")
            return []

        segments = []
        last_end = 0

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
        except Exception as e:
            print(f"[POST-PROCESS] Error extracting segment: {e}")
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
        print(f"\n[POST-PROCESS] ========================================")
        print(f"[POST-PROCESS] Starting post-processing")
        print(f"[POST-PROCESS] Input: {recording_path}")
        print(f"[POST-PROCESS] ========================================\n")

        # Mark as processing in database
        if recording_id:
            try:
                db.update_post_process_status(recording_id, 'processing')
            except Exception as e:
                print(f"[POST-PROCESS] Warning: Could not update status: {e}")

        if not os.path.exists(recording_path):
            print(f"[POST-PROCESS] Error: File not found: {recording_path}")
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'failed', 'File not found')
                except:
                    pass
            return {"success": False, "error": "File not found"}

        # Get video duration
        duration = self.get_video_duration(recording_path)
        if duration == 0:
            print(f"[POST-PROCESS] Error: Could not determine video duration")
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'failed', 'Could not determine duration')
                except:
                    pass
            return {"success": False, "error": "Could not determine duration"}

        print(f"[POST-PROCESS] Total duration: {duration:.1f}s ({duration/60:.1f} minutes)")

        # Check if recording has any audio
        if not self.has_audio(recording_path):
            print(f"[POST-PROCESS] No audio detected in entire recording - removing file")

            # Delete the recording file
            try:
                os.remove(recording_path)
                print(f"[POST-PROCESS] Deleted recording file: {recording_path}")
            except Exception as e:
                print(f"[POST-PROCESS] Warning: Could not delete file: {e}")

            # Mark recording as failed in database if recording_id provided
            if recording_id:
                try:
                    db.update_recording(
                        recording_id,
                        datetime.now(),
                        'failed',
                        'No audio detected in recording'
                    )
                    db.update_post_process_status(recording_id, 'completed', 'No audio detected - file removed')
                    print(f"[POST-PROCESS] Recording marked as failed in database")
                except Exception as e:
                    print(f"[POST-PROCESS] Warning: Could not update database: {e}")

            return {
                "success": False,
                "error": "No audio detected",
                "deleted": True,
                "message": "Recording had no audio and was removed"
            }

        # Detect silent periods (breaks)
        silent_periods = self.detect_silent_periods(recording_path)

        # Calculate active segments
        segments = self.calculate_segments(duration, silent_periods)

        if not segments:
            print(f"[POST-PROCESS] No segmentation needed")
            if recording_id:
                try:
                    db.update_post_process_status(recording_id, 'completed')
                except:
                    pass
            return {
                "success": True,
                "segments_created": 0,
                "message": "No breaks detected or breaks too short to split"
            }

        # Create output directory for segments
        base_name = os.path.splitext(os.path.basename(recording_path))[0]
        output_dir = os.path.join(os.path.dirname(recording_path), f"{base_name}_segments")
        os.makedirs(output_dir, exist_ok=True)

        # Copy original to segments folder for safety
        original_dest = os.path.join(output_dir, f"{base_name}_original.mp4")
        print(f"[POST-PROCESS] Preserving original: {original_dest}")

        try:
            import shutil
            shutil.copy2(recording_path, original_dest)
        except Exception as e:
            print(f"[POST-PROCESS] Warning: Could not copy original: {e}")

        # Extract segments
        segment_files = []
        for i, (start, end) in enumerate(segments, 1):
            segment_duration = end - start
            output_path = os.path.join(output_dir, f"{base_name}_segment_{i}.mp4")

            print(f"[POST-PROCESS] Extracting segment {i}/{len(segments)}: {start:.1f}s - {end:.1f}s ({segment_duration/60:.1f} min)")

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
                        print(f"[POST-PROCESS] ✓ Segment {i} created: {file_size_mb:.1f} MB (DB ID: {segment_id})")
                    except Exception as e:
                        print(f"[POST-PROCESS] ✓ Segment {i} created: {file_size_mb:.1f} MB (DB save failed: {e})")
                else:
                    print(f"[POST-PROCESS] ✓ Segment {i} created: {file_size_mb:.1f} MB")
            else:
                print(f"[POST-PROCESS] ✗ Failed to create segment {i}")

        # Mark recording as segmented and post-processed in database
        if recording_id and len(segment_files) > 0:
            try:
                db.mark_recording_segmented(recording_id)
                db.update_post_process_status(recording_id, 'completed')
                print(f"[POST-PROCESS] Recording marked as segmented in database")
            except Exception as e:
                print(f"[POST-PROCESS] Warning: Could not mark recording as segmented: {e}")
        elif recording_id:
            # Post-processing attempted but no segments created
            try:
                db.update_post_process_status(recording_id, 'completed', 'No segments created')
            except:
                pass

        print(f"\n[POST-PROCESS] ========================================")
        print(f"[POST-PROCESS] Processing complete")
        print(f"[POST-PROCESS] Segments folder: {output_dir}")
        print(f"[POST-PROCESS] Segments created: {len(segment_files)}/{len(segments)}")
        print(f"[POST-PROCESS] Original preserved: {original_dest}")
        print(f"[POST-PROCESS] ========================================\n")

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

    if len(sys.argv) < 2:
        print("Usage: python post_processor.py <video_file>")
        sys.exit(1)

    video_file = sys.argv[1]
    processor = PostProcessor()
    result = processor.process_recording(video_file)

    if result["success"]:
        print(f"\nSuccess! Created {result.get('segments_created', 0)} segments")
    else:
        print(f"\nFailed: {result.get('error', 'Unknown error')}")
