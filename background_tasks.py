#!/usr/bin/env python3
"""
Background task tracking for web UI visibility.
Tracks long-running background operations like transcription, diarization, and speaker refinement.
"""

import threading
import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BackgroundTask:
    """Represents a background task."""
    task_id: str
    recording_id: int
    task_type: str  # 'transcription', 'diarization', 'gemini_refinement', 'postprocess'
    description: str
    status: str  # 'running', 'completed', 'failed'
    started_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    progress: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Calculate elapsed time
        if self.completed_at:
            result['elapsed_seconds'] = int(self.completed_at - self.started_at)
        else:
            result['elapsed_seconds'] = int(time.time() - self.started_at)
        return result


class BackgroundTaskManager:
    """Manages background tasks for visibility in web UI."""

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Start background thread to clean up old completed tasks."""
        def cleanup():
            while True:
                time.sleep(60)  # Run every minute
                self._cleanup_old_tasks()

        self._cleanup_thread = threading.Thread(target=cleanup, daemon=True)
        self._cleanup_thread.start()

    def _cleanup_old_tasks(self):
        """Remove tasks completed more than 5 minutes ago."""
        with self._lock:
            now = time.time()
            to_remove = []
            for task_id, task in self._tasks.items():
                if task.completed_at and (now - task.completed_at) > 300:  # 5 minutes
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self._tasks[task_id]

    def start_task(
        self,
        task_id: str,
        recording_id: int,
        task_type: str,
        description: str
    ) -> None:
        """Register a new background task as started."""
        with self._lock:
            self._tasks[task_id] = BackgroundTask(
                task_id=task_id,
                recording_id=recording_id,
                task_type=task_type,
                description=description,
                status='running',
                started_at=time.time()
            )

    def update_progress(self, task_id: str, progress: str) -> None:
        """Update task progress message."""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].progress = progress
            else:
                logger.warning(f"Attempted to update progress for non-existent task: {task_id}")

    def complete_task(self, task_id: str, error: Optional[str] = None) -> None:
        """Mark a task as completed or failed."""
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                task.completed_at = time.time()
                if error:
                    task.status = 'failed'
                    task.error = error
                else:
                    task.status = 'completed'
            else:
                logger.warning(f"Attempted to complete non-existent task: {task_id} (error: {error})")

    def get_all_tasks(self) -> list[Dict[str, Any]]:
        """Get all active and recently completed tasks."""
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    def get_recording_tasks(self, recording_id: int) -> list[Dict[str, Any]]:
        """Get tasks for a specific recording."""
        with self._lock:
            return [
                task.to_dict()
                for task in self._tasks.values()
                if task.recording_id == recording_id
            ]


# Global task manager instance
task_manager = BackgroundTaskManager()
