#!/usr/bin/env python3
"""
Shared state module for thread-safe access to global state variables.
"""

import threading


class MonitoringState:
    """Thread-safe monitoring state management."""

    def __init__(self) -> None:
        self._enabled = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Get monitoring enabled state (thread-safe)."""
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set monitoring enabled state (thread-safe)."""
        with self._lock:
            self._enabled = value

    def enable(self) -> None:
        """Enable monitoring (thread-safe)."""
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        """Disable monitoring (thread-safe)."""
        with self._lock:
            self._enabled = False


# Global monitoring state instance
monitoring_state = MonitoringState()


class CalendarRefreshState:
    """Thread-safe calendar refresh request management."""

    def __init__(self) -> None:
        self._requested = False
        self._lock = threading.Lock()

    @property
    def requested(self) -> bool:
        """Check if calendar refresh is requested (thread-safe)."""
        with self._lock:
            return self._requested

    @requested.setter
    def requested(self, value: bool) -> None:
        """Set calendar refresh requested state (thread-safe)."""
        with self._lock:
            self._requested = value

    def request(self) -> None:
        """Request a calendar refresh (thread-safe)."""
        with self._lock:
            self._requested = True

    def clear(self) -> None:
        """Clear calendar refresh request (thread-safe)."""
        with self._lock:
            self._requested = False


# Global calendar refresh state instance
calendar_refresh_state = CalendarRefreshState()
