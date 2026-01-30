#!/usr/bin/env python3
"""
Resource management context managers for Calgary Council Stream Recorder.
Provides guaranteed cleanup for processes, files, and database transactions.
"""

import os
import signal
import subprocess
import sqlite3
import logging
from contextlib import contextmanager
from typing import Iterator, List
from pathlib import Path


logger = logging.getLogger(__name__)


@contextmanager
def recording_process(cmd: List[str], timeout: int = 10) -> Iterator[subprocess.Popen]:
    """
    Context manager for ffmpeg recording process with guaranteed cleanup.

    Ensures the process is properly terminated and cleaned up even if exceptions occur.
    Uses SIGINT first for graceful shutdown, then escalates to SIGTERM and SIGKILL.

    Args:
        cmd: Command list to execute (e.g., ['ffmpeg', '-i', 'input.mp4', ...])
        timeout: Maximum seconds to wait for graceful shutdown (default: 10)

    Yields:
        subprocess.Popen: The running process

    Example:
        with recording_process(['ffmpeg', '-i', 'stream.m3u8', 'output.mp4']) as process:
            # Process runs here
            while process.poll() is None:
                # Monitor recording
                pass
        # Process guaranteed to be cleaned up here
    """
    process = None
    try:
        logger.debug(f"Starting process: {' '.join(cmd[:3])}...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        yield process

    finally:
        if process is not None:
            _cleanup_process(process, timeout)


def _cleanup_process(process: subprocess.Popen, timeout: int) -> None:
    """
    Clean up a subprocess with escalating termination signals.

    Args:
        process: Process to clean up
        timeout: Maximum seconds to wait for graceful shutdown
    """
    if process.poll() is not None:
        logger.debug(f"Process already terminated with code {process.returncode}")
        return

    logger.info("Stopping process gracefully with SIGINT...")
    try:
        # Try SIGINT first (allows ffmpeg to finalize files properly)
        if hasattr(signal, 'SIGINT'):
            process.send_signal(signal.SIGINT)
        else:
            process.terminate()
    except OSError as e:
        logger.warning(f"Could not send SIGINT: {e}")
        process.terminate()

    # Wait for graceful shutdown
    try:
        process.wait(timeout=timeout)
        logger.info("Process stopped gracefully")
        return
    except subprocess.TimeoutExpired:
        logger.warning(f"Process did not stop within {timeout}s, escalating...")

    # Try SIGTERM
    if process.poll() is None:
        logger.warning("Sending SIGTERM...")
        process.terminate()
        try:
            process.wait(timeout=2)
            logger.info("Process terminated")
            return
        except subprocess.TimeoutExpired:
            logger.warning("Process did not respond to SIGTERM")

    # Force kill as last resort
    if process.poll() is None:
        logger.warning("Force killing process with SIGKILL...")
        process.kill()
        try:
            process.wait(timeout=1)
            logger.warning("Process killed")
        except subprocess.TimeoutExpired:
            logger.error("Process could not be killed - may be zombie")


@contextmanager
def temporary_wav_file(video_path: str) -> Iterator[str]:
    """
    Context manager for temporary WAV file extraction with guaranteed cleanup.

    Extracts audio to a temporary WAV file and ensures it's deleted after use,
    even if exceptions occur.

    Args:
        video_path: Path to source video file

    Yields:
        str: Path to temporary WAV file

    Example:
        with temporary_wav_file('recording.mp4') as wav_path:
            # Extract and use WAV file
            extract_audio(video_path, wav_path)
            transcribe(wav_path)
        # WAV file guaranteed to be deleted here
    """
    wav_path = video_path + '.temp.wav'

    try:
        logger.debug(f"Creating temporary WAV file: {wav_path}")
        yield wav_path

    finally:
        # Clean up WAV file
        if os.path.exists(wav_path):
            try:
                os.remove(wav_path)
                logger.debug(f"Cleaned up temporary WAV file: {wav_path}")
            except OSError as e:
                logger.warning(f"Could not remove temporary WAV file {wav_path}: {e}")


@contextmanager
def db_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """
    Context manager for database transactions with automatic rollback on error.

    Ensures database consistency by automatically rolling back on exceptions
    and committing on success.

    Args:
        conn: SQLite database connection

    Yields:
        sqlite3.Cursor: Database cursor for executing queries

    Example:
        with db_transaction(conn) as cursor:
            cursor.execute("INSERT INTO recordings (...) VALUES (...)")
            cursor.execute("UPDATE meetings SET ...")
        # Committed if successful, rolled back if exception occurred
    """
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
        logger.debug("Transaction committed")

    except Exception as e:
        conn.rollback()
        logger.warning(f"Transaction rolled back due to error: {e}")
        raise

    finally:
        cursor.close()


@contextmanager
def managed_file(file_path: str, mode: str = 'r', encoding: str = 'utf-8',
                 cleanup: bool = False) -> Iterator:
    """
    Context manager for file operations with optional cleanup.

    Args:
        file_path: Path to file
        mode: File open mode ('r', 'w', 'rb', 'wb', etc.)
        encoding: Text encoding (only for text modes)
        cleanup: If True, delete file after use

    Yields:
        File handle

    Example:
        with managed_file('output.json', 'w', cleanup=True) as f:
            json.dump(data, f)
        # File automatically closed and deleted if cleanup=True
    """
    file_handle = None
    try:
        # Open with encoding only for text modes
        if 'b' in mode:
            file_handle = open(file_path, mode)
        else:
            file_handle = open(file_path, mode, encoding=encoding)
        yield file_handle

    finally:
        if file_handle is not None:
            try:
                file_handle.close()
            except Exception as e:
                logger.warning(f"Error closing file {file_path}: {e}")

        if cleanup and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Cleaned up file: {file_path}")
            except OSError as e:
                logger.warning(f"Could not remove file {file_path}: {e}")
