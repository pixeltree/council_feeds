#!/usr/bin/env python3
import requests
import subprocess
import time
import os
import json
from datetime import datetime
from bs4 import BeautifulSoup
import re

STREAM_PAGE_URL = "https://video.isilive.ca/play/calgarycc/live"
CHECK_INTERVAL = 10  # Check every 10 seconds
OUTPUT_DIR = "./recordings"
MAX_RETRIES = 3

# Common ISILive stream URL patterns
STREAM_URL_PATTERNS = [
    "https://lin12.isilive.ca/live/calgarycc/live/chunklist.m3u8",
    "https://lin12.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/calgarycc/live/playlist.m3u8",
    "https://video.isilive.ca/live/_definst_/calgarycc/live/playlist.m3u8",
]

def get_stream_url():
    """Extract the HLS stream URL using yt-dlp or try common patterns."""
    # Try using yt-dlp to extract the stream URL
    try:
        result = subprocess.run(
            ['yt-dlp', '-g', '--no-warnings', STREAM_PAGE_URL],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            print(f"yt-dlp found stream: {url}")
            return url
    except subprocess.TimeoutExpired:
        print("yt-dlp timed out")
    except FileNotFoundError:
        print("yt-dlp not found, trying manual methods...")
    except Exception as e:
        print(f"yt-dlp error: {e}")

    # Try common ISILive URL patterns
    for pattern_url in STREAM_URL_PATTERNS:
        try:
            response = requests.head(pattern_url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                print(f"Found working stream pattern: {pattern_url}")
                return pattern_url
        except:
            pass

    # Try parsing the page
    try:
        response = requests.get(STREAM_PAGE_URL, timeout=10)
        response.raise_for_status()

        # Look for m3u8 URL in the page content
        m3u8_pattern = re.compile(r'https?://[^\s"\']+\.m3u8[^\s"\']*')
        matches = m3u8_pattern.findall(response.text)

        if matches:
            return matches[0]

        # Alternative: parse for video source tags
        soup = BeautifulSoup(response.text, 'html.parser')
        video_tags = soup.find_all(['video', 'source'])
        for tag in video_tags:
            src = tag.get('src', '')
            if '.m3u8' in src:
                if src.startswith('http'):
                    return src
                elif src.startswith('//'):
                    return 'https:' + src

        return None
    except Exception as e:
        print(f"Error fetching stream URL: {e}")
        return None

def is_stream_live(stream_url):
    """Check if the stream is currently live."""
    if not stream_url:
        return False

    try:
        response = requests.head(stream_url, timeout=10, allow_redirects=True)
        return response.status_code == 200
    except:
        # Try GET request as fallback
        try:
            response = requests.get(stream_url, timeout=10, stream=True)
            return response.status_code == 200
        except:
            return False

def record_stream(stream_url):
    """Record the stream to a file using ffmpeg."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"council_meeting_{timestamp}.mp4")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Starting recording: {output_file}")

    # ffmpeg command to record HLS stream
    cmd = [
        'ffmpeg',
        '-i', stream_url,
        '-c', 'copy',  # Copy codec (no re-encoding for efficiency)
        '-bsf:a', 'aac_adtstoasc',  # Fix AAC stream
        '-f', 'mp4',
        output_file
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        print(f"Recording started (PID: {process.pid})")

        # Monitor the process
        while True:
            # Check if stream is still live every 30 seconds
            time.sleep(30)

            if not is_stream_live(stream_url):
                print("Stream is no longer live. Stopping recording...")
                process.terminate()
                time.sleep(5)
                if process.poll() is None:
                    process.kill()
                break

            # Check if process is still running
            if process.poll() is not None:
                print("Recording process ended")
                break

        print(f"Recording saved: {output_file}")
        return True

    except Exception as e:
        print(f"Error during recording: {e}")
        return False

def main():
    """Main monitoring loop."""
    print("Calgary Council Stream Recorder Started")
    print(f"Monitoring: {STREAM_PAGE_URL}")
    print(f"Check interval: {CHECK_INTERVAL} seconds")
    print(f"Output directory: {OUTPUT_DIR}")
    print("-" * 50)

    while True:
        try:
            stream_url = get_stream_url()

            if stream_url:
                print(f"Found stream URL: {stream_url}")

                if is_stream_live(stream_url):
                    print("Stream is LIVE! Starting recording...")
                    record_stream(stream_url)
                    print("Recording completed. Resuming monitoring...")
                else:
                    print(f"Stream found but not live. Checking again in {CHECK_INTERVAL}s...")
            else:
                print(f"No stream URL found. Checking again in {CHECK_INTERVAL}s...")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\nShutting down recorder...")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
