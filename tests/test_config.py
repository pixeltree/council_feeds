#!/usr/bin/env python3
"""
Tests for configuration validation.

Tests the AppConfig dataclass and validation logic to ensure proper configuration
validation at startup.
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from config import AppConfig, validate_config, CALGARY_TZ


class TestAppConfigValidation:
    """Test configuration validation logic."""

    def test_valid_config_from_defaults(self):
        """Test that default configuration is valid."""
        # Should not raise any exceptions
        config = validate_config()
        assert config is not None
        assert isinstance(config, AppConfig)
        assert config.timezone == CALGARY_TZ

    def test_active_check_interval_must_be_positive(self):
        """Test that ACTIVE_CHECK_INTERVAL must be positive."""
        # Create a config with invalid active_check_interval
        config = AppConfig(
            stream_page_url="http://test.com",
            council_calendar_api="http://test.com/api",
            active_check_interval=0,  # Invalid
            idle_check_interval=1800,
            output_dir="./recordings",
            db_dir="./data",
            db_path="./data/test.db",
            max_retries=3,
            web_host="0.0.0.0",
            web_port=5000,
            ffmpeg_command="ffmpeg",
            ytdlp_command="yt-dlp",
            enable_post_processing=False,
            post_process_silence_threshold_db=-40,
            post_process_min_silence_duration=120,
            audio_detection_mean_threshold_db=-50,
            audio_detection_max_threshold_db=-30,
            enable_transcription=False,
            whisper_model="base",
            pyannote_api_token=None,
            recording_format="mkv",
            enable_segmented_recording=True,
            segment_duration=900,
            recording_reconnect=True,
            enable_static_detection=True,
            static_min_growth_kb=10,
            static_check_interval=30,
            static_max_failures=3,
            static_scene_threshold=200,
            gemini_api_key=None,
            gemini_model="gemini-1.5-flash",
            enable_gemini_refinement=False,
            timezone=CALGARY_TZ
        )

        with pytest.raises(ValueError, match="ACTIVE_CHECK_INTERVAL must be positive"):
            config.validate()

    def test_idle_interval_must_be_greater_than_active(self):
        """Test that IDLE_CHECK_INTERVAL must be greater than ACTIVE_CHECK_INTERVAL."""
        config = AppConfig(
            stream_page_url="http://test.com",
            council_calendar_api="http://test.com/api",
            active_check_interval=60,
            idle_check_interval=30,  # Less than active - invalid
            output_dir="./recordings",
            db_dir="./data",
            db_path="./data/test.db",
            max_retries=3,
            web_host="0.0.0.0",
            web_port=5000,
            ffmpeg_command="ffmpeg",
            ytdlp_command="yt-dlp",
            enable_post_processing=False,
            post_process_silence_threshold_db=-40,
            post_process_min_silence_duration=120,
            audio_detection_mean_threshold_db=-50,
            audio_detection_max_threshold_db=-30,
            enable_transcription=False,
            whisper_model="base",
            pyannote_api_token=None,
            recording_format="mkv",
            enable_segmented_recording=True,
            segment_duration=900,
            recording_reconnect=True,
            enable_static_detection=True,
            static_min_growth_kb=10,
            static_check_interval=30,
            static_max_failures=3,
            static_scene_threshold=200,
            gemini_api_key=None,
            gemini_model="gemini-1.5-flash",
            enable_gemini_refinement=False,
            timezone=CALGARY_TZ
        )

        with pytest.raises(ValueError, match="must be greater than"):
            config.validate()

    def test_output_dir_must_be_writable(self, tmp_path):
        """Test that OUTPUT_DIR must be writable."""
        # Create a read-only directory (if possible on this platform)
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        # On Unix-like systems, we can make it read-only
        if hasattr(os, 'chmod'):
            readonly_dir.chmod(0o444)

            with patch.dict(os.environ, {"OUTPUT_DIR": str(readonly_dir)}):
                from importlib import reload
                import config as config_module
                reload(config_module)

                try:
                    with pytest.raises(ValueError, match="not writable"):
                        config_module.validate_config()
                finally:
                    # Restore write permissions for cleanup
                    readonly_dir.chmod(0o755)

    def test_output_dir_created_if_not_exists(self, tmp_path):
        """Test that OUTPUT_DIR is created if it doesn't exist."""
        new_dir = tmp_path / "new_output"
        assert not new_dir.exists()

        with patch.dict(os.environ, {"OUTPUT_DIR": str(new_dir)}):
            from importlib import reload
            import config as config_module
            reload(config_module)

            config = config_module.validate_config()
            assert new_dir.exists()
            assert new_dir.is_dir()

    def test_db_dir_must_be_writable(self, tmp_path):
        """Test that DB_DIR must be writable."""
        readonly_dir = tmp_path / "readonly_db"
        readonly_dir.mkdir()

        if hasattr(os, 'chmod'):
            readonly_dir.chmod(0o444)

            with patch.dict(os.environ, {
                "DB_DIR": str(readonly_dir),
                "OUTPUT_DIR": str(tmp_path / "output")  # Valid output dir
            }):
                from importlib import reload
                import config as config_module
                reload(config_module)

                try:
                    with pytest.raises(ValueError, match="not writable"):
                        config_module.validate_config()
                finally:
                    readonly_dir.chmod(0o755)

    def test_whisper_model_must_be_valid(self, tmp_path):
        """Test that WHISPER_MODEL must be a valid model name."""
        with patch.dict(os.environ, {
            "WHISPER_MODEL": "invalid_model",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="WHISPER_MODEL must be one of"):
                config_module.validate_config()

    def test_valid_whisper_models(self, tmp_path):
        """Test that all valid Whisper models are accepted."""
        valid_models = ["tiny", "base", "small", "medium", "large", "turbo"]

        for model in valid_models:
            with patch.dict(os.environ, {
                "WHISPER_MODEL": model,
                "OUTPUT_DIR": str(tmp_path / "output"),
                "DB_DIR": str(tmp_path / "db")
            }):
                from importlib import reload
                import config as config_module
                reload(config_module)

                config = config_module.validate_config()
                assert config.whisper_model == model

    def test_pyannote_token_required_when_transcription_enabled(self, tmp_path):
        """Test that PYANNOTE_API_TOKEN is required when transcription is enabled."""
        with patch.dict(os.environ, {
            "ENABLE_TRANSCRIPTION": "true",
            "PYANNOTE_API_TOKEN": "",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="PYANNOTE_API_TOKEN is required"):
                config_module.validate_config()

    def test_pyannote_token_not_required_when_transcription_disabled(self, tmp_path):
        """Test that PYANNOTE_API_TOKEN is not required when transcription is disabled."""
        with patch.dict(os.environ, {
            "ENABLE_TRANSCRIPTION": "false",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }, clear=True):
            from importlib import reload
            import config as config_module
            reload(config_module)

            # Should not raise
            config = config_module.validate_config()
            assert not config.enable_transcription

    def test_gemini_api_key_required_when_refinement_enabled(self, tmp_path):
        """Test that GEMINI_API_KEY is required when Gemini refinement is enabled."""
        with patch.dict(os.environ, {
            "ENABLE_GEMINI_REFINEMENT": "true",
            "GEMINI_API_KEY": "",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
                config_module.validate_config()

    def test_recording_format_must_be_valid(self, tmp_path):
        """Test that RECORDING_FORMAT must be a valid format."""
        with patch.dict(os.environ, {
            "RECORDING_FORMAT": "invalid",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="RECORDING_FORMAT must be one of"):
                config_module.validate_config()

    def test_valid_recording_formats(self, tmp_path):
        """Test that all valid recording formats are accepted."""
        valid_formats = ["mkv", "mp4", "ts"]

        for fmt in valid_formats:
            with patch.dict(os.environ, {
                "RECORDING_FORMAT": fmt,
                "OUTPUT_DIR": str(tmp_path / "output"),
                "DB_DIR": str(tmp_path / "db")
            }):
                from importlib import reload
                import config as config_module
                reload(config_module)

                config = config_module.validate_config()
                assert config.recording_format == fmt

    def test_segment_duration_must_be_positive(self, tmp_path):
        """Test that SEGMENT_DURATION must be positive when segmented recording is enabled."""
        with patch.dict(os.environ, {
            "ENABLE_SEGMENTED_RECORDING": "true",
            "SEGMENT_DURATION": "0",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="SEGMENT_DURATION must be positive"):
                config_module.validate_config()

    def test_web_port_must_be_valid(self, tmp_path):
        """Test that WEB_PORT must be between 1 and 65535."""
        invalid_ports = ["0", "65536", "-1", "99999"]

        for port in invalid_ports:
            with patch.dict(os.environ, {
                "WEB_PORT": port,
                "OUTPUT_DIR": str(tmp_path / "output"),
                "DB_DIR": str(tmp_path / "db")
            }):
                from importlib import reload
                import config as config_module
                reload(config_module)

                with pytest.raises(ValueError, match="WEB_PORT must be between"):
                    config_module.validate_config()

    def test_static_detection_settings_validation(self, tmp_path):
        """Test validation of static detection settings."""
        # Test negative min growth
        with patch.dict(os.environ, {
            "ENABLE_STATIC_DETECTION": "true",
            "STATIC_MIN_GROWTH_KB": "-1",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="STATIC_MIN_GROWTH_KB must be non-negative"):
                config_module.validate_config()

        # Test zero check interval
        with patch.dict(os.environ, {
            "ENABLE_STATIC_DETECTION": "true",
            "STATIC_CHECK_INTERVAL": "0",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="STATIC_CHECK_INTERVAL must be positive"):
                config_module.validate_config()

        # Test zero max failures
        with patch.dict(os.environ, {
            "ENABLE_STATIC_DETECTION": "true",
            "STATIC_MAX_FAILURES": "0",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            with pytest.raises(ValueError, match="STATIC_MAX_FAILURES must be positive"):
                config_module.validate_config()

    def test_max_retries_must_be_non_negative(self, tmp_path):
        """Test that MAX_RETRIES must be non-negative."""
        with patch.dict(os.environ, {
            "MAX_RETRIES": "-1",
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            # MAX_RETRIES is read as an int directly in config.py, so this might not be caught
            # by our validation. Let's test what happens.
            try:
                config = config_module.validate_config()
                # If we get here, check that negative is caught
                if config.max_retries < 0:
                    pytest.fail("MAX_RETRIES should have been validated")
            except ValueError as e:
                # Expected
                assert "MAX_RETRIES" in str(e)

    def test_multiple_validation_errors_reported(self, tmp_path):
        """Test that multiple validation errors are reported together."""
        config = AppConfig(
            stream_page_url="http://test.com",
            council_calendar_api="http://test.com/api",
            active_check_interval=0,  # Invalid
            idle_check_interval=1800,
            output_dir=str(tmp_path / "output"),
            db_dir=str(tmp_path / "db"),
            db_path=str(tmp_path / "db" / "test.db"),
            max_retries=3,
            web_host="0.0.0.0",
            web_port=0,  # Invalid
            ffmpeg_command="ffmpeg",
            ytdlp_command="yt-dlp",
            enable_post_processing=False,
            post_process_silence_threshold_db=-40,
            post_process_min_silence_duration=120,
            audio_detection_mean_threshold_db=-50,
            audio_detection_max_threshold_db=-30,
            enable_transcription=False,
            whisper_model="invalid",  # Invalid
            pyannote_api_token=None,
            recording_format="mkv",
            enable_segmented_recording=True,
            segment_duration=900,
            recording_reconnect=True,
            enable_static_detection=True,
            static_min_growth_kb=10,
            static_check_interval=30,
            static_max_failures=3,
            static_scene_threshold=200,
            gemini_api_key=None,
            gemini_model="gemini-1.5-flash",
            enable_gemini_refinement=False,
            timezone=CALGARY_TZ
        )

        with pytest.raises(ValueError) as exc_info:
            config.validate()

        error_message = str(exc_info.value)
        # All three errors should be mentioned
        assert "ACTIVE_CHECK_INTERVAL" in error_message
        assert "WHISPER_MODEL" in error_message
        assert "WEB_PORT" in error_message

    def test_config_dataclass_attributes(self, tmp_path):
        """Test that AppConfig dataclass has all expected attributes."""
        with patch.dict(os.environ, {
            "OUTPUT_DIR": str(tmp_path / "output"),
            "DB_DIR": str(tmp_path / "db")
        }):
            from importlib import reload
            import config as config_module
            reload(config_module)

            config = config_module.validate_config()

            # Test that all expected attributes exist
            assert hasattr(config, 'stream_page_url')
            assert hasattr(config, 'council_calendar_api')
            assert hasattr(config, 'active_check_interval')
            assert hasattr(config, 'idle_check_interval')
            assert hasattr(config, 'output_dir')
            assert hasattr(config, 'db_dir')
            assert hasattr(config, 'db_path')
            assert hasattr(config, 'max_retries')
            assert hasattr(config, 'web_host')
            assert hasattr(config, 'web_port')
            assert hasattr(config, 'ffmpeg_command')
            assert hasattr(config, 'ytdlp_command')
            assert hasattr(config, 'enable_post_processing')
            assert hasattr(config, 'enable_transcription')
            assert hasattr(config, 'whisper_model')
            assert hasattr(config, 'pyannote_api_token')
            assert hasattr(config, 'recording_format')
            assert hasattr(config, 'enable_segmented_recording')
            assert hasattr(config, 'segment_duration')
            assert hasattr(config, 'enable_static_detection')
            assert hasattr(config, 'gemini_api_key')
            assert hasattr(config, 'gemini_model')
            assert hasattr(config, 'enable_gemini_refinement')
            assert hasattr(config, 'timezone')
