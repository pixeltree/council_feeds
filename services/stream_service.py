#!/usr/bin/env python3
"""
Stream service for detecting and checking stream availability.
"""

import logging
import requests
import subprocess
import re
from bs4 import BeautifulSoup
from typing import List, Optional

from config import (
    STREAM_PAGE_URL,
    STREAM_URL_PATTERNS,
    STREAM_URLS_BY_ROOM,
    YTDLP_COMMAND,
)


class StreamService:
    """Service for detecting and checking stream availability."""

    def __init__(
        self,
        stream_page_url: str = STREAM_PAGE_URL,
        stream_url_patterns: Optional[List[str]] = None,
        ytdlp_command: str = YTDLP_COMMAND
    ):
        self.stream_page_url = stream_page_url
        self.stream_url_patterns = stream_url_patterns or STREAM_URL_PATTERNS
        self.ytdlp_command = ytdlp_command
        self.logger = logging.getLogger(__name__)

    def _try_ytdlp(self) -> Optional[str]:
        """Try to extract stream URL using yt-dlp."""
        try:
            result = subprocess.run(
                [self.ytdlp_command, '-g', '--no-warnings', self.stream_page_url],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                url = result.stdout.strip()
                self.logger.info(f"yt-dlp found stream: {url}")
                return url
        except subprocess.TimeoutExpired:
            self.logger.warning("yt-dlp timed out")
        except FileNotFoundError:
            self.logger.warning("yt-dlp not found, trying manual methods...")
        except Exception as e:
            self.logger.error(f"yt-dlp error: {e}", exc_info=True)
        return None

    def _try_url_patterns(self, patterns: List[str]) -> Optional[str]:
        """Try common URL patterns to find a working stream."""
        for pattern_url in patterns:
            try:
                response = requests.head(pattern_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    self.logger.info(f"Found working stream pattern: {pattern_url}")
                    return pattern_url
            except Exception:
                # Try next pattern if this one fails
                pass
        return None

    def _parse_page_for_stream(self) -> Optional[str]:
        """Parse the stream page HTML to find m3u8 URL."""
        try:
            response = requests.get(self.stream_page_url, timeout=10)
            response.raise_for_status()

            # Look for m3u8 URL in the page content
            m3u8_pattern = re.compile(r'https?://[^\s"\']+\.m3u8[^\s"\']*')
            matches = m3u8_pattern.findall(response.text)

            if matches:
                return str(matches[0])

            # Alternative: parse for video source tags
            soup = BeautifulSoup(response.text, 'html.parser')
            video_tags = soup.find_all(['video', 'source'])
            for tag in video_tags:
                src = tag.get('src', '')
                if '.m3u8' in src:
                    if src.startswith('http'):
                        return str(src)
                    elif src.startswith('//'):
                        return 'https:' + str(src)

            return None
        except Exception as e:
            self.logger.error(f"Error fetching stream URL: {e}", exc_info=True)
            return None

    def get_stream_url(self, room: Optional[str] = None) -> Optional[str]:
        """Extract the HLS stream URL using yt-dlp or try common patterns.

        Args:
            room: Optional room name to try room-specific stream URLs first
        """
        # Determine which URL patterns to try based on room
        patterns_to_try = []
        if room and room in STREAM_URLS_BY_ROOM:
            # Try room-specific URLs first
            patterns_to_try = STREAM_URLS_BY_ROOM[room]
            self.logger.info(f"Trying {room} stream URLs...")
        else:
            # Fall back to all patterns
            patterns_to_try = self.stream_url_patterns

        # Try using yt-dlp to extract the stream URL (skip if room-specific)
        if not room:
            url = self._try_ytdlp()
            if url:
                return url

        # Try room-specific or common ISILive URL patterns
        url = self._try_url_patterns(patterns_to_try)
        if url:
            return url

        # Try parsing the page
        return self._parse_page_for_stream()

    def is_stream_live(self, stream_url: str) -> bool:
        """Check if the stream is currently live."""
        if not stream_url:
            return False

        try:
            response = requests.head(stream_url, timeout=10, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            # Try GET request as fallback
            try:
                response = requests.get(stream_url, timeout=10, stream=True)
                return response.status_code == 200
            except Exception:
                # Return False if both HEAD and GET fail
                return False
