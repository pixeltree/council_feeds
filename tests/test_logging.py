"""
Tests for logging configuration.
"""

import logging
import os
import tempfile
from pathlib import Path
import pytest

from logging_config import setup_logging, get_logger


class TestLoggingSetup:
    """Test logging configuration and setup."""

    def test_setup_logging_default_config(self, tmp_path):
        """Test logging setup with default configuration."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_dir=log_dir)

        # Verify log directory was created
        assert Path(log_dir).exists()

        # Verify log file was created
        log_file = Path(log_dir) / "council_feeds.log"
        assert log_file.exists()

        # Verify root logger is configured
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO
        assert len(root_logger.handlers) > 0

    def test_setup_logging_custom_level(self, tmp_path):
        """Test logging setup with custom log level."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_level="DEBUG", log_dir=log_dir)

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_setup_logging_console_disabled(self, tmp_path):
        """Test logging setup with console output disabled."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_dir=log_dir, console_output=False)

        root_logger = logging.getLogger()
        # Should have only file handler (no console handler)
        stream_handlers = [h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)]
        # Note: RotatingFileHandler is a subclass of StreamHandler, so we need to be more specific
        from logging.handlers import RotatingFileHandler
        console_handlers = [h for h in root_logger.handlers
                          if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)]
        assert len(console_handlers) == 0

    def test_setup_logging_custom_log_file(self, tmp_path):
        """Test logging setup with custom log file name."""
        log_dir = str(tmp_path / "logs")
        custom_log_file = "custom_test.log"

        setup_logging(log_dir=log_dir, log_file=custom_log_file)

        # Verify custom log file was created
        log_file = Path(log_dir) / custom_log_file
        assert log_file.exists()

    def test_get_logger(self):
        """Test getting a logger instance."""
        logger = get_logger("test_module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_logging_writes_to_file(self, tmp_path):
        """Test that log messages are actually written to the log file."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_dir=log_dir)

        logger = get_logger("test_logger")
        test_message = "Test log message"
        logger.info(test_message)

        # Flush handlers to ensure message is written
        for handler in logging.getLogger().handlers:
            handler.flush()

        # Read log file and verify message was written
        log_file = Path(log_dir) / "council_feeds.log"
        log_content = log_file.read_text()
        assert test_message in log_content
        assert "test_logger" in log_content

    def test_logging_respects_log_level(self, tmp_path):
        """Test that log levels are respected."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_level="WARNING", log_dir=log_dir)

        logger = get_logger("test_logger")
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")

        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        # Read log file
        log_file = Path(log_dir) / "council_feeds.log"
        log_content = log_file.read_text()

        # Only WARNING and above should be logged
        assert "Debug message" not in log_content
        assert "Info message" not in log_content
        assert "Warning message" in log_content

    def test_log_rotation_configuration(self, tmp_path):
        """Test that log rotation is properly configured."""
        log_dir = str(tmp_path / "logs")
        max_bytes = 1024  # 1KB
        backup_count = 3

        setup_logging(log_dir=log_dir, max_bytes=max_bytes, backup_count=backup_count)

        # Find the rotating file handler
        from logging.handlers import RotatingFileHandler
        root_logger = logging.getLogger()
        rotating_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]

        assert len(rotating_handlers) > 0
        handler = rotating_handlers[0]
        assert handler.maxBytes == max_bytes
        assert handler.backupCount == backup_count

    def test_multiple_setup_calls_clear_handlers(self, tmp_path):
        """Test that calling setup_logging multiple times clears old handlers."""
        log_dir = str(tmp_path / "logs")

        # First setup
        setup_logging(log_dir=log_dir)
        first_handler_count = len(logging.getLogger().handlers)

        # Second setup - should clear old handlers and add new ones
        setup_logging(log_dir=log_dir)
        second_handler_count = len(logging.getLogger().handlers)

        # Handler count should be the same (old handlers cleared, new ones added)
        assert first_handler_count == second_handler_count

    def test_logging_with_exception(self, tmp_path):
        """Test logging with exception information."""
        log_dir = str(tmp_path / "logs")

        setup_logging(log_dir=log_dir)

        logger = get_logger("test_logger")

        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.error("Error occurred", exc_info=True)

        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        # Read log file and verify exception was logged
        log_file = Path(log_dir) / "council_feeds.log"
        log_content = log_file.read_text()
        assert "Error occurred" in log_content
        assert "ValueError" in log_content
        assert "Test exception" in log_content
        assert "Traceback" in log_content
