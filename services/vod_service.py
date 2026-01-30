#!/usr/bin/env python3
"""
VOD (Video on Demand) service for importing past council meeting videos.

This service handles downloading videos from Escriba meeting pages that host
past council meeting recordings on ISILive video player.
"""

import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from config import CALGARY_TZ, OUTPUT_DIR, RECORDING_FORMAT, YTDLP_COMMAND

logger = logging.getLogger(__name__)


class VodService:
    """Service for extracting and downloading VOD content from Escriba meeting pages."""

    # Whitelist of allowed domains for security
    ALLOWED_DOMAINS = ['pub-calgary.escribemeetings.com']

    def __init__(
        self,
        ytdlp_command: str = YTDLP_COMMAND,
        recording_format: str = RECORDING_FORMAT,
        output_dir: str = OUTPUT_DIR
    ):
        """Initialize VOD service.

        Args:
            ytdlp_command: Path to yt-dlp command
            recording_format: Desired output format (mkv, mp4, ts)
            output_dir: Base directory for recordings
        """
        self.ytdlp_command = ytdlp_command
        self.recording_format = recording_format
        self.output_dir = output_dir
        self.logger = logging.getLogger(__name__)

    def validate_escriba_url(self, url: str) -> bool:
        """Validate that URL is from allowed Escriba domain.

        Args:
            url: URL to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc in self.ALLOWED_DOMAINS
        except Exception:
            return False

    def extract_meeting_info(self, escriba_url: str) -> Dict[str, Any]:
        """Extract meeting metadata from Escriba meeting page.

        Args:
            escriba_url: URL of Escriba meeting page

        Returns:
            Dictionary with meeting metadata:
                - title: Meeting title
                - datetime: Meeting datetime
                - meeting_id: Escriba meeting ID (from URL)
                - link: Original Escriba URL
                - timestamp: Unix timestamp for folder naming

        Raises:
            ValueError: If URL is invalid or extraction fails
        """
        if not self.validate_escriba_url(escriba_url):
            raise ValueError(f"Invalid Escriba URL: {escriba_url}")

        try:
            # Extract meeting ID from URL
            parsed = urlparse(escriba_url)
            query_params = parse_qs(parsed.query)
            meeting_id = query_params.get('Id', [None])[0]

            if not meeting_id:
                raise ValueError("Could not extract meeting ID from URL")

            # Fetch page content
            response = requests.get(escriba_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract meeting title
            title_elem = soup.find('h1') or soup.find('title')
            title = title_elem.get_text().strip() if title_elem else f"Meeting {meeting_id}"

            # Try to extract date from title or page
            meeting_date = self._extract_date_from_title(title)
            if not meeting_date:
                # Try to find date in page content
                meeting_date = self._extract_date_from_page(soup)

            # Default to current time if no date found
            if not meeting_date:
                self.logger.warning(f"Could not extract date from {escriba_url}, using current time")
                meeting_date = datetime.now(CALGARY_TZ)

            # Ensure timezone-aware
            if meeting_date.tzinfo is None:
                meeting_date = CALGARY_TZ.localize(meeting_date)

            return {
                'title': title,
                'datetime': meeting_date,
                'meeting_id': meeting_id,
                'link': escriba_url,
                'timestamp': int(meeting_date.timestamp())
            }

        except Exception as e:
            self.logger.error(f"Failed to extract meeting info from {escriba_url}: {e}")
            raise ValueError(f"Failed to extract meeting info: {e}")

    def _extract_date_from_title(self, title: str) -> Optional[datetime]:
        """Extract date from meeting title.

        Looks for patterns like:
        - April 22, 2024
        - 2024-04-22
        - April 22nd, 2024

        Args:
            title: Meeting title

        Returns:
            Parsed datetime or None
        """
        # Pattern: Month Day, Year (e.g., "April 22, 2024")
        pattern1 = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})'
        match = re.search(pattern1, title, re.IGNORECASE)
        if match:
            month_name, day, year = match.groups()
            try:
                date_str = f"{month_name} {day}, {year}"
                return datetime.strptime(date_str, "%B %d, %Y")
            except ValueError:
                pass

        # Pattern: YYYY-MM-DD
        pattern2 = r'(\d{4})-(\d{2})-(\d{2})'
        match = re.search(pattern2, title)
        if match:
            year, month, day = match.groups()
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError:
                pass

        return None

    def _extract_date_from_page(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract date from page content.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Parsed datetime or None
        """
        # Look for common date containers
        date_selectors = [
            'span.date',
            'div.date',
            'span.meeting-date',
            'div.meeting-date',
            'time'
        ]

        for selector in date_selectors:
            elem = soup.select_one(selector)
            if elem:
                date_text = elem.get_text().strip()
                parsed_date = self._extract_date_from_title(date_text)
                if parsed_date:
                    return parsed_date

        return None

    def extract_video_url(self, escriba_url: str) -> Optional[str]:
        """Extract video URL from Escriba meeting page.

        This is a fallback method if yt-dlp fails. It attempts to parse
        the ISILive player data from the page HTML.

        Args:
            escriba_url: URL of Escriba meeting page

        Returns:
            Video URL or None if not found
        """
        try:
            response = requests.get(escriba_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for ISILive player div
            player_div = soup.find('div', id='isi_player')
            if player_div:
                client_id = player_div.get('data-client_id')
                stream_name = player_div.get('data-stream_name')

                if client_id and stream_name:
                    # Construct ISILive VOD URL
                    # Pattern observed: video.isilive.ca/vod/{client_id}/{stream_name}
                    video_url = f"https://video.isilive.ca/vod/{client_id}/{stream_name}"
                    self.logger.info(f"Extracted ISILive video URL: {video_url}")
                    return video_url

            # Try to find mp4 links directly
            mp4_pattern = re.compile(r'https?://[^\s"\']+\.mp4[^\s"\']*')
            matches = mp4_pattern.findall(response.text)
            if matches:
                return matches[0]

            return None

        except Exception as e:
            self.logger.error(f"Failed to extract video URL from {escriba_url}: {e}")
            return None

    def download_vod(self, escriba_url: str, output_path: str) -> str:
        """Download VOD from Escriba meeting URL.

        Uses yt-dlp as primary method, with fallback to direct URL extraction.

        Args:
            escriba_url: URL of Escriba meeting page
            output_path: Full path where video should be saved

        Returns:
            Path to downloaded video file

        Raises:
            RuntimeError: If download fails
        """
        if not self.validate_escriba_url(escriba_url):
            raise ValueError(f"Invalid Escriba URL: {escriba_url}")

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        # Try yt-dlp first (primary method)
        try:
            self.logger.info(f"Downloading VOD from {escriba_url} using yt-dlp...")
            self._download_with_ytdlp(escriba_url, output_path)

            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                self.logger.info(f"Successfully downloaded video to {output_path} ({file_size} bytes)")
                return output_path

        except Exception as e:
            self.logger.warning(f"yt-dlp download failed: {e}, trying fallback method...")

        # Fallback: Try direct URL extraction and ffmpeg download
        try:
            video_url = self.extract_video_url(escriba_url)
            if video_url:
                self.logger.info(f"Downloading VOD from {video_url} using ffmpeg...")
                self._download_with_ffmpeg(video_url, output_path)

                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    self.logger.info(f"Successfully downloaded video to {output_path} ({file_size} bytes)")
                    return output_path

        except Exception as e:
            self.logger.error(f"Fallback download failed: {e}")

        raise RuntimeError(f"Failed to download video from {escriba_url}")

    def _download_with_ytdlp(self, url: str, output_path: str) -> None:
        """Download video using yt-dlp.

        Args:
            url: Video URL
            output_path: Output file path

        Raises:
            RuntimeError: If download fails
        """
        # Remove extension from output path for yt-dlp template
        output_template = output_path.rsplit('.', 1)[0]

        cmd = [
            self.ytdlp_command,
            '--no-warnings',
            '--quiet',
            '--progress',
            '--merge-output-format', self.recording_format,
            '-o', f'{output_template}.%(ext)s',
            url
        ]

        self.logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown error"
            raise RuntimeError(f"yt-dlp failed: {error_msg}")

        # yt-dlp may add extension, find the actual file
        expected_path = f"{output_template}.{self.recording_format}"
        if os.path.exists(expected_path) and not os.path.exists(output_path):
            os.rename(expected_path, output_path)

    def _download_with_ffmpeg(self, video_url: str, output_path: str) -> None:
        """Download video using ffmpeg.

        Args:
            video_url: Direct video URL
            output_path: Output file path

        Raises:
            RuntimeError: If download fails
        """
        cmd = [
            'ffmpeg',
            '-i', video_url,
            '-c', 'copy',
            '-y',  # Overwrite output file
            output_path
        ]

        self.logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown error"
            raise RuntimeError(f"ffmpeg download failed: {error_msg}")
