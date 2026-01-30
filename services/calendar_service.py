#!/usr/bin/env python3
"""
Calendar service for fetching and managing council meeting calendar.
"""

import logging
import requests
from datetime import datetime
from dateutil import parser as date_parser
from typing import List, Dict, Any

import database as db
from config import (
    CALGARY_TZ,
    COUNCIL_CALENDAR_API,
    COUNCIL_CHAMBER,
    ENGINEERING_TRADITIONS_ROOM,
)


class CalendarService:
    """Service for fetching and managing council meeting calendar."""

    def __init__(self, api_url: str = COUNCIL_CALENDAR_API, timezone: Any = CALGARY_TZ):
        self.api_url = api_url
        self.timezone = timezone
        self.logger = logging.getLogger(__name__)

    def determine_room(self, title: str) -> str:
        """Determine meeting room based on title."""
        title_lower = title.lower()
        if 'council meeting' in title_lower:
            return COUNCIL_CHAMBER
        else:
            # All committee meetings use Engineering Traditions Room
            return ENGINEERING_TRADITIONS_ROOM

    def fetch_council_meetings(self) -> List[Dict]:
        """Fetch upcoming meetings from Calgary Open Data API (both Council and Committee)."""
        try:
            response = requests.get(self.api_url, timeout=15)
            response.raise_for_status()
            meetings = response.json()

            # Process all meetings and determine their rooms
            all_meetings = []
            for meeting in meetings:
                title = meeting.get('title', '')
                try:
                    # Parse the meeting date
                    date_str = meeting.get('meeting_date', '')
                    # Parse as naive datetime first
                    meeting_dt_naive = date_parser.parse(date_str, fuzzy=True)

                    # Localize to Calgary timezone
                    meeting_dt = self.timezone.localize(meeting_dt_naive)

                    # Determine room based on title
                    room = self.determine_room(title)

                    all_meetings.append({
                        'title': title,
                        'datetime': meeting_dt,
                        'raw_date': date_str,
                        'link': meeting.get('link', ''),
                        'room': room
                    })
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Could not parse date '{date_str}': {e}")
                    continue

            # Sort by datetime
            all_meetings.sort(key=lambda x: x['datetime'])

            return all_meetings

        except Exception as e:
            self.logger.error(f"Error fetching council meetings: {e}", exc_info=True)
            return []

    def get_upcoming_meetings(self, force_refresh: bool = False) -> List[Dict]:
        """Get upcoming meetings, using database cache if available and fresh."""
        # Check if we need to refresh from API
        last_refresh = db.get_metadata('last_calendar_refresh')
        needs_refresh = force_refresh

        # Use timezone-aware current time
        now = datetime.now(self.timezone)

        if last_refresh and not needs_refresh:
            try:
                last_refresh_dt = datetime.fromisoformat(last_refresh)
                # Make timezone-aware if it isn't already
                if last_refresh_dt.tzinfo is None:
                    last_refresh_dt = self.timezone.localize(last_refresh_dt)

                self.logger.info(f"Using cached meeting schedule (last updated: {last_refresh_dt.strftime('%Y-%m-%d %H:%M %Z')})")
            except (ValueError, TypeError):
                needs_refresh = True
        else:
            needs_refresh = True

        # Fetch fresh data if needed
        if needs_refresh:
            self.logger.info("Fetching fresh meeting schedule from Calgary Open Data API...")
            meetings = self.fetch_council_meetings()

            if meetings:
                # Save to database
                saved_count = db.save_meetings(meetings)
                db.set_metadata('last_calendar_refresh', now.isoformat())
                self.logger.info(f"Saved {saved_count} Council meetings to database")

        # Always return from database to ensure consistency
        return db.get_upcoming_meetings()
