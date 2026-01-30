#!/usr/bin/env python3
"""
Tests for resource cleanup context managers.
"""

import os
import signal
import sqlite3
import subprocess
import tempfile
import time
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from resource_managers import (
    recording_process,
    temporary_wav_file,
    db_transaction,
    managed_file,
    _cleanup_process
)


class TestRecordingProcessContextManager:
    """Tests for recording_process context manager."""

    def test_normal_execution(self):
        """Test process cleanup on normal exit."""
        cmd = ['sleep', '0.1']
        with recording_process(cmd) as process:
            assert process is not None
            assert process.poll() is None  # Process running
            time.sleep(0.15)

        # After context exit, process should be cleaned up
        assert process.poll() is not None

    def test_cleanup_on_exception(self):
        """Test process cleanup when exception occurs."""
        cmd = ['sleep', '10']
        with pytest.raises(ValueError):
            with recording_process(cmd) as process:
                assert process.poll() is None  # Process running
                raise ValueError("Test exception")

        # Process should be terminated despite exception
        time.sleep(0.5)
        assert process.poll() is not None

    def test_process_already_terminated(self):
        """Test cleanup when process has already exited."""
        cmd = ['echo', 'test']
        with recording_process(cmd) as process:
            time.sleep(0.1)  # Let process finish
            assert process.poll() is not None
        # Should not raise any errors

    def test_graceful_shutdown_with_sigint(self):
        """Test that SIGINT is sent first for graceful shutdown."""
        # Use a script that handles SIGINT gracefully
        script = """
import signal
import sys
import time

def handler(signum, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, handler)
time.sleep(10)
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            cmd = ['python3', script_path]
            start_time = time.time()

            with recording_process(cmd, timeout=2) as process:
                time.sleep(0.1)
                assert process.poll() is None
                # Exit context - should trigger graceful shutdown

            elapsed = time.time() - start_time
            # Should exit quickly via SIGINT, not wait full timeout
            assert elapsed < 3
            assert process.poll() is not None

        finally:
            os.unlink(script_path)

    def test_timeout_escalation(self):
        """Test that process is killed if it doesn't respond to SIGINT."""
        # Script that ignores SIGINT
        script = """
import signal
import time

signal.signal(signal.SIGINT, signal.SIG_IGN)
time.sleep(30)
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            cmd = ['python3', script_path]
            start_time = time.time()

            with recording_process(cmd, timeout=1) as process:
                time.sleep(0.1)
                assert process.poll() is None

            elapsed = time.time() - start_time
            # Should not take full 30 seconds, should be killed after timeout
            assert elapsed < 5
            assert process.poll() is not None

        finally:
            os.unlink(script_path)


class TestCleanupProcessFunction:
    """Tests for _cleanup_process helper function."""

    def test_cleanup_already_terminated_process(self):
        """Test cleanup of process that already exited."""
        process = subprocess.Popen(['echo', 'test'])
        time.sleep(0.1)
        assert process.poll() is not None

        # Should handle gracefully
        _cleanup_process(process, timeout=1)
        assert process.poll() is not None

    def test_cleanup_running_process(self):
        """Test cleanup of running process."""
        process = subprocess.Popen(['sleep', '10'])
        assert process.poll() is None

        _cleanup_process(process, timeout=1)

        time.sleep(0.1)
        assert process.poll() is not None


class TestTemporaryWavFileContextManager:
    """Tests for temporary_wav_file context manager."""

    def test_wav_file_cleanup_on_success(self):
        """Test WAV file is deleted after successful use."""
        video_path = '/tmp/test_video.mp4'

        with temporary_wav_file(video_path) as wav_path:
            assert wav_path == '/tmp/test_video.mp4.temp.wav'
            # Create the file
            Path(wav_path).touch()
            assert os.path.exists(wav_path)

        # File should be deleted after context exit
        assert not os.path.exists(wav_path)

    def test_wav_file_cleanup_on_exception(self):
        """Test WAV file is deleted even if exception occurs."""
        video_path = '/tmp/test_video_exception.mp4'
        wav_path = video_path + '.temp.wav'

        with pytest.raises(ValueError):
            with temporary_wav_file(video_path) as wav:
                Path(wav).touch()
                assert os.path.exists(wav)
                raise ValueError("Test exception")

        # File should still be deleted despite exception
        assert not os.path.exists(wav_path)

    def test_wav_file_cleanup_when_file_doesnt_exist(self):
        """Test cleanup handles non-existent files gracefully."""
        video_path = '/tmp/test_nonexistent.mp4'

        with temporary_wav_file(video_path) as wav_path:
            # Don't create the file
            assert not os.path.exists(wav_path)

        # Should not raise any errors

    def test_wav_file_cleanup_permission_error(self):
        """Test cleanup handles permission errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, 'test.mp4')

            with temporary_wav_file(video_path) as wav_path:
                # Create file
                Path(wav_path).touch()
                # Make parent directory read-only (can't delete file)
                os.chmod(tmpdir, 0o444)

            # Should not raise exception, just log warning
            # File might still exist due to permission error

            # Restore permissions for cleanup
            os.chmod(tmpdir, 0o755)


class TestDbTransactionContextManager:
    """Tests for db_transaction context manager."""

    def test_transaction_commit_on_success(self):
        """Test transaction is committed on successful completion."""
        # Create in-memory database
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE test (id INTEGER, value TEXT)')

        with db_transaction(conn) as cursor:
            cursor.execute("INSERT INTO test VALUES (1, 'test')")

        # Verify data was committed
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test")
        result = cursor.fetchone()
        assert result == (1, 'test')
        conn.close()

    def test_transaction_rollback_on_exception(self):
        """Test transaction is rolled back on exception."""
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE test (id INTEGER, value TEXT)')

        # Insert initial data
        conn.execute("INSERT INTO test VALUES (1, 'initial')")
        conn.commit()

        # Try to insert more data but raise exception
        with pytest.raises(ValueError):
            with db_transaction(conn) as cursor:
                cursor.execute("INSERT INTO test VALUES (2, 'should_rollback')")
                raise ValueError("Test exception")

        # Verify only initial data exists
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test")
        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0] == (1, 'initial')
        conn.close()

    def test_nested_transactions(self):
        """Test nested transaction behavior."""
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE test (id INTEGER)')

        # SQLite doesn't support true nested transactions, but should not error
        with db_transaction(conn) as cursor1:
            cursor1.execute("INSERT INTO test VALUES (1)")
            # Note: nested transaction will actually commit the parent
            with db_transaction(conn) as cursor2:
                cursor2.execute("INSERT INTO test VALUES (2)")

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM test")
        count = cursor.fetchone()[0]
        assert count == 2
        conn.close()

    def test_transaction_with_database_error(self):
        """Test transaction rollback on database error."""
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')

        with pytest.raises(sqlite3.IntegrityError):
            with db_transaction(conn) as cursor:
                cursor.execute("INSERT INTO test VALUES (1)")
                cursor.execute("INSERT INTO test VALUES (1)")  # Duplicate primary key

        # Verify no data was committed
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM test")
        count = cursor.fetchone()[0]
        assert count == 0
        conn.close()


class TestManagedFileContextManager:
    """Tests for managed_file context manager."""

    def test_file_read(self):
        """Test managed file reading."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write('test content')
            temp_path = f.name

        try:
            with managed_file(temp_path, 'r') as f:
                content = f.read()
                assert content == 'test content'

            # File should still exist (cleanup=False)
            assert os.path.exists(temp_path)
        finally:
            os.unlink(temp_path)

    def test_file_write(self):
        """Test managed file writing."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            with managed_file(temp_path, 'w') as f:
                f.write('new content')

            # Verify content was written
            with open(temp_path, 'r') as f:
                assert f.read() == 'new content'
        finally:
            os.unlink(temp_path)

    def test_file_write_with_cleanup(self):
        """Test managed file writing with automatic cleanup."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        with managed_file(temp_path, 'w', cleanup=True) as f:
            f.write('temporary content')
            assert os.path.exists(temp_path)

        # File should be deleted after context exit
        assert not os.path.exists(temp_path)

    def test_file_binary_mode(self):
        """Test managed file in binary mode."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            data = b'\x00\x01\x02\x03'
            with managed_file(temp_path, 'wb') as f:
                f.write(data)

            with managed_file(temp_path, 'rb') as f:
                read_data = f.read()
                assert read_data == data
        finally:
            os.unlink(temp_path)

    def test_file_cleanup_on_exception(self):
        """Test file is cleaned up even on exception."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        with pytest.raises(ValueError):
            with managed_file(temp_path, 'w', cleanup=True) as f:
                f.write('test')
                raise ValueError("Test exception")

        # File should be deleted despite exception
        assert not os.path.exists(temp_path)

    def test_file_encoding(self):
        """Test managed file with different encoding."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            # Write UTF-8 content
            with managed_file(temp_path, 'w', encoding='utf-8') as f:
                f.write('Hello 世界 🌍')

            # Read back
            with managed_file(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
                assert content == 'Hello 世界 🌍'
        finally:
            os.unlink(temp_path)


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""

    def test_recording_with_database_transaction(self):
        """Test recording process with database transaction."""
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE recordings (id INTEGER, status TEXT)')

        # Simulate successful recording
        cmd = ['echo', 'recording']
        with recording_process(cmd) as process:
            with db_transaction(conn) as cursor:
                cursor.execute("INSERT INTO recordings VALUES (1, 'started')")
            time.sleep(0.1)

        # Update status after recording
        with db_transaction(conn) as cursor:
            cursor.execute("UPDATE recordings SET status = 'completed' WHERE id = 1")

        # Verify final state
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM recordings WHERE id = 1")
        status = cursor.fetchone()[0]
        assert status == 'completed'
        conn.close()

    def test_transcription_with_temp_files(self):
        """Test transcription workflow with temporary files."""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            video_path = f.name
            f.write(b'fake video data')

        try:
            # Simulate extraction and transcription
            with temporary_wav_file(video_path) as wav_path:
                # Create WAV file (simulated extraction)
                with managed_file(wav_path, 'wb') as f:
                    f.write(b'fake audio data')

                assert os.path.exists(wav_path)

                # Simulate transcription processing
                with managed_file(wav_path, 'rb') as f:
                    data = f.read()
                    assert data == b'fake audio data'

            # WAV should be cleaned up
            assert not os.path.exists(wav_path)

            # Video should still exist
            assert os.path.exists(video_path)

        finally:
            os.unlink(video_path)

    def test_error_recovery_with_cleanup(self):
        """Test that resources are cleaned up on error."""
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE test (id INTEGER)')

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            # Simulate operation that fails
            with pytest.raises(RuntimeError):
                with db_transaction(conn) as cursor:
                    cursor.execute("INSERT INTO test VALUES (1)")

                    with managed_file(temp_path, 'w', cleanup=True) as f:
                        f.write('data')
                        raise RuntimeError("Simulated failure")

            # Transaction should be rolled back
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM test")
            assert cursor.fetchone()[0] == 0

            # File should be cleaned up
            assert not os.path.exists(temp_path)

        finally:
            conn.close()
            if os.path.exists(temp_path):
                os.unlink(temp_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
