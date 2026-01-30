#!/usr/bin/env python3
"""
Services module for Calgary Council Stream Recorder.
Provides service classes for calendar, scheduling, streaming, and recording operations.
"""

from .calendar_service import CalendarService
from .meeting_scheduler import MeetingScheduler
from .stream_service import StreamService
from .recording_service import RecordingService

# Export recording components for advanced usage
from .recording_path_manager import RecordingPathManager
from .ffmpeg_command_builder import FFmpegCommandBuilder
from .recording_validator import RecordingValidator
from .segment_merger import SegmentMerger
from .recording_monitor import RecordingMonitor

__all__ = [
    'CalendarService',
    'MeetingScheduler',
    'StreamService',
    'RecordingService',
    'RecordingPathManager',
    'FFmpegCommandBuilder',
    'RecordingValidator',
    'SegmentMerger',
    'RecordingMonitor',
]
