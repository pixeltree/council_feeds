"""Custom exception types for the Council Feeds application.

This module defines a hierarchy of domain-specific exceptions that provide
clear error handling and improved debugging capabilities.

Exception Hierarchy:
    CouncilRecorderError (base)
    ├── ConfigurationError
    ├── StreamError
    │   ├── StreamNotAvailableError
    │   └── StreamConnectionError
    ├── RecordingError
    │   ├── RecordingProcessError
    │   └── RecordingStorageError
    ├── TranscriptionError
    │   ├── WhisperError
    │   ├── DiarizationError
    │   └── GeminiError
    └── DatabaseError
        ├── DatabaseConnectionError
        └── DatabaseQueryError
"""


class CouncilRecorderError(Exception):
    """Base exception for all Council Recorder errors."""

    def __init__(self, message: str, details: str = None):
        """Initialize the exception with a message and optional details.

        Args:
            message: Human-readable error message
            details: Additional technical details about the error
        """
        self.message = message
        self.details = details
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format the complete error message."""
        if self.details:
            return f"{self.message}\nDetails: {self.details}"
        return self.message


# Configuration Errors
class ConfigurationError(CouncilRecorderError):
    """Raised when there's an issue with application configuration."""
    pass


# Stream Errors
class StreamError(CouncilRecorderError):
    """Base class for stream-related errors."""
    pass


class StreamNotAvailableError(StreamError):
    """Raised when a stream is not available or accessible."""

    def __init__(self, stream_url: str, reason: str = None):
        """Initialize with stream URL and optional reason.

        Args:
            stream_url: The URL of the unavailable stream
            reason: Optional reason why the stream is unavailable
        """
        self.stream_url = stream_url
        message = f"Stream not available: {stream_url}"
        super().__init__(message, reason)


class StreamConnectionError(StreamError):
    """Raised when unable to connect to a stream."""

    def __init__(self, stream_url: str, error: str = None):
        """Initialize with stream URL and optional error details.

        Args:
            stream_url: The URL of the stream
            error: Optional error details from the connection attempt
        """
        self.stream_url = stream_url
        message = f"Failed to connect to stream: {stream_url}"
        super().__init__(message, error)


# Recording Errors
class RecordingError(CouncilRecorderError):
    """Base class for recording-related errors."""
    pass


class RecordingProcessError(RecordingError):
    """Raised when the recording process encounters an error."""

    def __init__(self, recording_id: int = None, error: str = None):
        """Initialize with optional recording ID and error details.

        Args:
            recording_id: ID of the recording that failed
            error: Error details from the recording process
        """
        self.recording_id = recording_id
        message = "Recording process failed"
        if recording_id:
            message += f" (recording_id: {recording_id})"
        super().__init__(message, error)


class RecordingStorageError(RecordingError):
    """Raised when unable to store or access recording files."""

    def __init__(self, file_path: str, operation: str, error: str = None):
        """Initialize with file path, operation, and optional error.

        Args:
            file_path: Path to the recording file
            operation: The operation that failed (e.g., 'save', 'read', 'delete')
            error: Optional error details
        """
        self.file_path = file_path
        self.operation = operation
        message = f"Failed to {operation} recording file: {file_path}"
        super().__init__(message, error)


# Transcription Errors
class TranscriptionError(CouncilRecorderError):
    """Base class for transcription-related errors."""
    pass


class WhisperError(TranscriptionError):
    """Raised when Whisper transcription fails."""

    def __init__(self, file_path: str = None, error: str = None):
        """Initialize with optional file path and error details.

        Args:
            file_path: Path to the audio file being transcribed
            error: Error details from Whisper
        """
        self.file_path = file_path
        message = "Whisper transcription failed"
        if file_path:
            message += f" for file: {file_path}"
        super().__init__(message, error)


class DiarizationError(TranscriptionError):
    """Raised when speaker diarization fails."""

    def __init__(self, file_path: str = None, error: str = None):
        """Initialize with optional file path and error details.

        Args:
            file_path: Path to the audio file being diarized
            error: Error details from the diarization process
        """
        self.file_path = file_path
        message = "Speaker diarization failed"
        if file_path:
            message += f" for file: {file_path}"
        super().__init__(message, error)


class GeminiError(TranscriptionError):
    """Raised when Gemini AI processing fails."""

    def __init__(self, operation: str = None, error: str = None):
        """Initialize with optional operation and error details.

        Args:
            operation: The operation that failed (e.g., 'speaker refinement')
            error: Error details from Gemini API
        """
        self.operation = operation
        message = "Gemini AI processing failed"
        if operation:
            message += f" during {operation}"
        super().__init__(message, error)


# Database Errors
class DatabaseError(CouncilRecorderError):
    """Base class for database-related errors."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when unable to connect to the database."""

    def __init__(self, db_path: str = None, error: str = None):
        """Initialize with optional database path and error details.

        Args:
            db_path: Path to the database file
            error: Error details from the connection attempt
        """
        self.db_path = db_path
        message = "Failed to connect to database"
        if db_path:
            message += f": {db_path}"
        super().__init__(message, error)


class DatabaseQueryError(DatabaseError):
    """Raised when a database query fails."""

    def __init__(self, query: str = None, error: str = None):
        """Initialize with optional query and error details.

        Args:
            query: The SQL query that failed (truncated if too long)
            error: Error details from the database
        """
        self.query = query
        message = "Database query failed"
        if query:
            # Truncate long queries for readability
            truncated_query = query[:100] + "..." if len(query) > 100 else query
            message += f": {truncated_query}"
        super().__init__(message, error)
