"""Tests for custom exception types."""

import pytest
from exceptions import (
    CouncilRecorderError,
    ConfigurationError,
    StreamError,
    StreamNotAvailableError,
    StreamConnectionError,
    RecordingError,
    RecordingProcessError,
    RecordingStorageError,
    TranscriptionError,
    WhisperError,
    DiarizationError,
    GeminiError,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseQueryError
)


class TestBaseException:
    """Test the base CouncilRecorderError exception."""

    def test_basic_exception(self):
        """Test basic exception creation with message."""
        exc = CouncilRecorderError("Test error")
        assert exc.message == "Test error"
        assert exc.details is None
        assert str(exc) == "Test error"

    def test_exception_with_details(self):
        """Test exception with details."""
        exc = CouncilRecorderError("Test error", "Additional details")
        assert exc.message == "Test error"
        assert exc.details == "Additional details"
        assert "Test error" in str(exc)
        assert "Additional details" in str(exc)

    def test_exception_inheritance(self):
        """Test that all custom exceptions inherit from base."""
        assert issubclass(StreamError, CouncilRecorderError)
        assert issubclass(RecordingError, CouncilRecorderError)
        assert issubclass(TranscriptionError, CouncilRecorderError)
        assert issubclass(DatabaseError, CouncilRecorderError)


class TestConfigurationError:
    """Test ConfigurationError exception."""

    def test_configuration_error(self):
        """Test configuration error creation."""
        exc = ConfigurationError("Invalid config", "MISSING_API_KEY")
        assert exc.message == "Invalid config"
        assert exc.details == "MISSING_API_KEY"
        assert isinstance(exc, CouncilRecorderError)


class TestStreamErrors:
    """Test stream-related exception types."""

    def test_stream_error(self):
        """Test base stream error."""
        exc = StreamError("Stream error")
        assert exc.message == "Stream error"
        assert isinstance(exc, CouncilRecorderError)

    def test_stream_not_available_error(self):
        """Test stream not available error."""
        url = "http://example.com/stream.m3u8"
        exc = StreamNotAvailableError(url, "Stream offline")
        assert exc.stream_url == url
        assert exc.message == f"Stream not available: {url}"
        assert exc.details == "Stream offline"
        assert isinstance(exc, StreamError)

    def test_stream_connection_error(self):
        """Test stream connection error."""
        url = "http://example.com/stream.m3u8"
        exc = StreamConnectionError(url, "Connection timeout")
        assert exc.stream_url == url
        assert exc.message == f"Failed to connect to stream: {url}"
        assert exc.details == "Connection timeout"
        assert isinstance(exc, StreamError)


class TestRecordingErrors:
    """Test recording-related exception types."""

    def test_recording_error(self):
        """Test base recording error."""
        exc = RecordingError("Recording error")
        assert exc.message == "Recording error"
        assert isinstance(exc, CouncilRecorderError)

    def test_recording_process_error(self):
        """Test recording process error."""
        exc = RecordingProcessError(123, "ffmpeg crashed")
        assert exc.recording_id == 123
        assert "recording_id: 123" in exc.message
        assert exc.details == "ffmpeg crashed"
        assert isinstance(exc, RecordingError)

    def test_recording_process_error_without_id(self):
        """Test recording process error without ID."""
        exc = RecordingProcessError(error="ffmpeg crashed")
        assert exc.recording_id is None
        assert "Recording process failed" in exc.message
        assert exc.details == "ffmpeg crashed"

    def test_recording_storage_error(self):
        """Test recording storage error."""
        exc = RecordingStorageError("/path/to/file.mp4", "save", "Disk full")
        assert exc.file_path == "/path/to/file.mp4"
        assert exc.operation == "save"
        assert "save" in exc.message
        assert "/path/to/file.mp4" in exc.message
        assert exc.details == "Disk full"
        assert isinstance(exc, RecordingError)


class TestTranscriptionErrors:
    """Test transcription-related exception types."""

    def test_transcription_error(self):
        """Test base transcription error."""
        exc = TranscriptionError("Transcription error")
        assert exc.message == "Transcription error"
        assert isinstance(exc, CouncilRecorderError)

    def test_whisper_error(self):
        """Test Whisper error."""
        exc = WhisperError("/path/to/video.mp4", "Model load failed")
        assert exc.file_path == "/path/to/video.mp4"
        assert "/path/to/video.mp4" in exc.message
        assert exc.details == "Model load failed"
        assert isinstance(exc, TranscriptionError)

    def test_whisper_error_without_file(self):
        """Test Whisper error without file path."""
        exc = WhisperError(error="Model load failed")
        assert exc.file_path is None
        assert "Whisper transcription failed" in exc.message
        assert exc.details == "Model load failed"

    def test_diarization_error(self):
        """Test diarization error."""
        exc = DiarizationError("/path/to/audio.wav", "API timeout")
        assert exc.file_path == "/path/to/audio.wav"
        assert "/path/to/audio.wav" in exc.message
        assert exc.details == "API timeout"
        assert isinstance(exc, TranscriptionError)

    def test_diarization_error_without_file(self):
        """Test diarization error without file path."""
        exc = DiarizationError(error="API timeout")
        assert exc.file_path is None
        assert "Speaker diarization failed" in exc.message

    def test_gemini_error(self):
        """Test Gemini error."""
        exc = GeminiError("speaker refinement", "API key invalid")
        assert exc.operation == "speaker refinement"
        assert "speaker refinement" in exc.message
        assert exc.details == "API key invalid"
        assert isinstance(exc, TranscriptionError)

    def test_gemini_error_without_operation(self):
        """Test Gemini error without operation."""
        exc = GeminiError(error="API key invalid")
        assert exc.operation is None
        assert "Gemini AI processing failed" in exc.message


class TestDatabaseErrors:
    """Test database-related exception types."""

    def test_database_error(self):
        """Test base database error."""
        exc = DatabaseError("Database error")
        assert exc.message == "Database error"
        assert isinstance(exc, CouncilRecorderError)

    def test_database_connection_error(self):
        """Test database connection error."""
        exc = DatabaseConnectionError("/path/to/db.sqlite", "Permission denied")
        assert exc.db_path == "/path/to/db.sqlite"
        assert "/path/to/db.sqlite" in exc.message
        assert exc.details == "Permission denied"
        assert isinstance(exc, DatabaseError)

    def test_database_connection_error_without_path(self):
        """Test database connection error without path."""
        exc = DatabaseConnectionError(error="Permission denied")
        assert exc.db_path is None
        assert "Failed to connect to database" in exc.message

    def test_database_query_error(self):
        """Test database query error."""
        query = "SELECT * FROM recordings WHERE id = ?"
        exc = DatabaseQueryError(query, "Syntax error")
        assert exc.query == query
        assert query in exc.message
        assert exc.details == "Syntax error"
        assert isinstance(exc, DatabaseError)

    def test_database_query_error_long_query(self):
        """Test database query error with long query (should truncate)."""
        long_query = "SELECT * FROM recordings WHERE " + "x = 1 AND " * 50
        exc = DatabaseQueryError(long_query, "Syntax error")
        assert exc.query == long_query
        assert len(exc.message) < len(long_query) + 100  # Should be truncated
        assert "..." in exc.message

    def test_database_query_error_without_query(self):
        """Test database query error without query."""
        exc = DatabaseQueryError(error="Syntax error")
        assert exc.query is None
        assert "Database query failed" in exc.message


class TestExceptionRaising:
    """Test that exceptions can be raised and caught correctly."""

    def test_raise_and_catch_base(self):
        """Test raising and catching base exception."""
        with pytest.raises(CouncilRecorderError) as exc_info:
            raise CouncilRecorderError("Test")
        assert exc_info.value.message == "Test"

    def test_raise_and_catch_stream_error(self):
        """Test raising and catching stream error."""
        with pytest.raises(StreamError):
            raise StreamNotAvailableError("http://example.com")

    def test_raise_and_catch_recording_error(self):
        """Test raising and catching recording error."""
        with pytest.raises(RecordingError):
            raise RecordingProcessError(123, "Failed")

    def test_raise_and_catch_transcription_error(self):
        """Test raising and catching transcription error."""
        with pytest.raises(TranscriptionError):
            raise WhisperError("/path/to/file.mp4", "Failed")

    def test_raise_and_catch_database_error(self):
        """Test raising and catching database error."""
        with pytest.raises(DatabaseError):
            raise DatabaseQueryError("SELECT *", "Failed")

    def test_catch_specific_exception(self):
        """Test catching specific exception type."""
        with pytest.raises(StreamNotAvailableError) as exc_info:
            raise StreamNotAvailableError("http://example.com", "Offline")
        assert exc_info.value.stream_url == "http://example.com"

    def test_catch_as_base_class(self):
        """Test that specific exceptions can be caught as base class."""
        with pytest.raises(CouncilRecorderError):
            raise StreamNotAvailableError("http://example.com")

        with pytest.raises(CouncilRecorderError):
            raise RecordingProcessError(123)

        with pytest.raises(CouncilRecorderError):
            raise WhisperError("/path/to/file.mp4")

        with pytest.raises(CouncilRecorderError):
            raise DatabaseQueryError("SELECT *")
