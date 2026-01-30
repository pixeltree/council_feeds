#!/usr/bin/env python3
"""
Meeting scheduler service for determining meeting windows and scheduling logic.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any

from config import (
    CALGARY_TZ,
    MEETING_BUFFER_BEFORE,
    MEETING_BUFFER_AFTER,
)


class MeetingScheduler:
    """Service for determining meeting windows and scheduling logic."""

    def __init__(
        self,
        buffer_before: timedelta = MEETING_BUFFER_BEFORE,
        buffer_after: timedelta = MEETING_BUFFER_AFTER,
        timezone: Any = CALGARY_TZ
    ):
        self.buffer_before = buffer_before
        self.buffer_after = buffer_after
        self.timezone = timezone

    def is_within_meeting_window(
        self,
        current_time: datetime,
        meetings: List[Dict]
    ) -> Tuple[bool, Optional[Dict]]:
        """Check if current time is within any meeting window."""
        for meeting in meetings:
            start_window = meeting['datetime'] - self.buffer_before
            end_window = meeting['datetime'] + self.buffer_after

            if start_window <= current_time <= end_window:
                return True, meeting

        return False, None

    def get_next_meeting(
        self,
        current_time: datetime,
        meetings: List[Dict]
    ) -> Optional[Dict]:
        """Get the next upcoming meeting after current time."""
        future_meetings = [m for m in meetings if m['datetime'] > current_time]
        return future_meetings[0] if future_meetings else None
