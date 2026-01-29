#!/usr/bin/env python3
"""
File-based transcription progress detection.

Instead of tracking progress in the database, we detect which steps are complete
by checking for the existence of output files. This is simpler and more reliable
since the files are the source of truth.
"""

import os
from typing import Dict, Optional


def detect_transcription_progress(video_path: str) -> Dict:
    """
    Detect transcription progress by checking for output files.

    Args:
        video_path: Path to the video file

    Returns:
        Dictionary with step status based on file existence
    """
    if not video_path:
        return {}

    steps = {}

    # Step 1: Audio Extraction - check for WAV file
    wav_path = os.path.splitext(video_path)[0] + '.wav'
    steps['extraction'] = {
        'status': 'completed' if os.path.exists(wav_path) else 'pending',
        'file': wav_path if os.path.exists(wav_path) else None
    }

    # Step 2: Whisper Transcription - check for whisper output file
    whisper_path = video_path + '.whisper.json'
    steps['whisper'] = {
        'status': 'completed' if os.path.exists(whisper_path) else 'pending',
        'file': whisper_path if os.path.exists(whisper_path) else None
    }

    # Step 3: Diarization - check for pyannote file
    pyannote_path = video_path + '.diarization.pyannote.json'
    steps['diarization'] = {
        'status': 'completed' if os.path.exists(pyannote_path) else 'pending',
        'file': pyannote_path if os.path.exists(pyannote_path) else None
    }

    # Step 4: Gemini refinement - check for gemini file
    gemini_path = video_path + '.diarization.gemini.json'
    transcript_path = video_path + '.transcript.json'
    if os.path.exists(gemini_path):
        steps['gemini'] = {
            'status': 'completed',
            'file': gemini_path
        }
    else:
        # Gemini is optional - show as skipped if diarization and whisper complete but gemini doesn't exist
        if os.path.exists(pyannote_path) and os.path.exists(whisper_path):
            steps['gemini'] = {
                'status': 'skipped',
                'file': None
            }
        else:
            steps['gemini'] = {
                'status': 'pending',
                'file': None
            }

    # Step 5: Merge - if transcript exists with speakers, merge is done
    if os.path.exists(transcript_path):
        steps['merge'] = {
            'status': 'completed',
            'file': transcript_path
        }
    else:
        steps['merge'] = {
            'status': 'pending',
            'file': None
        }

    return steps


def get_overall_status(steps: Dict) -> str:
    """
    Determine overall transcription status from step status.

    Args:
        steps: Dictionary of step statuses

    Returns:
        Overall status: 'completed', 'processing', 'pending', or 'failed'
    """
    if not steps:
        return 'pending'

    # If final merge step is completed, transcription is complete
    if steps.get('merge', {}).get('status') == 'completed':
        return 'completed'

    # If any step is completed or in progress, we're processing
    completed_count = sum(1 for step in steps.values() if step.get('status') == 'completed')
    if completed_count > 0:
        return 'processing'

    return 'pending'


def get_next_step(steps: Dict) -> Optional[str]:
    """
    Get the next step that needs to be processed.

    Args:
        steps: Dictionary of step statuses

    Returns:
        Name of next step to process, or None if all done
    """
    step_order = ['extraction', 'whisper', 'diarization', 'gemini', 'merge']

    for step_name in step_order:
        step = steps.get(step_name, {})
        status = step.get('status')

        # Skip optional steps that are skipped
        if status == 'skipped':
            continue

        # Found a pending step
        if status == 'pending':
            return step_name

    return None


def is_step_resumable(video_path: str, step_name: str) -> bool:
    """
    Check if a specific step can be resumed (output file already exists).

    Args:
        video_path: Path to video file
        step_name: Name of the step

    Returns:
        True if step output exists and can be reused
    """
    steps = detect_transcription_progress(video_path)
    step = steps.get(step_name, {})
    return step.get('status') == 'completed'


def get_step_file_path(video_path: str, step_name: str) -> Optional[str]:
    """
    Get the output file path for a specific step.

    Args:
        video_path: Path to video file
        step_name: Name of the step

    Returns:
        Path to step output file, or None
    """
    file_map = {
        'extraction': os.path.splitext(video_path)[0] + '.wav',
        'whisper': video_path + '.whisper.json',
        'diarization': video_path + '.diarization.pyannote.json',
        'gemini': video_path + '.diarization.gemini.json',
        'merge': video_path + '.transcript.json'
    }

    return file_map.get(step_name)


def get_latest_completed_step(video_path: str) -> Optional[str]:
    """
    Get the latest (last) completed step in the transcription pipeline.

    This is the step that can safely be reset without causing inconsistency.

    Args:
        video_path: Path to video file

    Returns:
        Name of latest completed step, or None if no steps completed
    """
    steps = detect_transcription_progress(video_path)
    step_order = ['extraction', 'whisper', 'diarization', 'gemini', 'merge']

    # Find the last completed step (iterating backwards)
    for step_name in reversed(step_order):
        step = steps.get(step_name, {})
        if step.get('status') == 'completed':
            return step_name

    return None


def reset_step(video_path: str, step_name: str) -> bool:
    """
    Reset a specific transcription step by deleting its output file(s).

    This allows the step to be re-run. Only resets the specified step,
    not dependent steps (caller should handle that logic).

    Args:
        video_path: Path to video file
        step_name: Name of step to reset

    Returns:
        True if successful, False otherwise
    """
    file_path = get_step_file_path(video_path, step_name)
    if not file_path:
        return False

    try:
        # Handle special cases where multiple files need to be deleted
        files_to_delete = []

        if step_name == 'gemini':
            # Delete Gemini diarization file
            gemini_file = video_path + '.diarization.gemini.json'
            files_to_delete.append(gemini_file)
            # Also delete legacy diarization.json if it exists (might be Gemini version)
            legacy_path = video_path + '.diarization.json'
            if os.path.exists(legacy_path):
                files_to_delete.append(legacy_path)

        elif step_name == 'merge':
            # Delete final transcript (this will force re-merge)
            transcript_file = video_path + '.transcript.json'
            files_to_delete.append(transcript_file)
            # Also delete legacy diarization.json
            legacy_path = video_path + '.diarization.json'
            if os.path.exists(legacy_path):
                files_to_delete.append(legacy_path)

        else:
            # For other steps, just delete the main output file
            files_to_delete.append(file_path)

        # Delete files
        deleted_count = 0
        for f in files_to_delete:
            if os.path.exists(f):
                os.remove(f)
                deleted_count += 1
                print(f"[RESET] Deleted: {f}")

        return deleted_count > 0

    except Exception as e:
        print(f"[RESET] Error resetting step {step_name}: {e}")
        return False


def get_dependent_steps(step_name: str) -> list:
    """
    Get list of steps that depend on the given step.

    If a step is reset, all dependent steps must also be reset
    to maintain consistency.

    Args:
        step_name: Name of the step

    Returns:
        List of dependent step names
    """
    dependencies = {
        'extraction': ['whisper', 'diarization', 'gemini', 'merge'],
        'whisper': ['merge'],
        'diarization': ['gemini', 'merge'],
        'gemini': ['merge'],
        'merge': []
    }

    return dependencies.get(step_name, [])


def get_step_dependencies(step_name: str) -> list:
    """
    Get list of steps that this step depends on (prerequisites).

    A step can only run if all its dependencies are completed.

    Args:
        step_name: Name of the step

    Returns:
        List of prerequisite step names
    """
    prerequisites = {
        'extraction': [],  # No dependencies
        'whisper': ['extraction'],  # Needs WAV file
        'diarization': ['extraction'],  # Needs WAV file
        'gemini': ['diarization'],  # Needs pyannote diarization
        'merge': ['whisper', 'diarization']  # Needs both transcription and diarization
    }

    return prerequisites.get(step_name, [])


def can_run_step(video_path: str, step_name: str) -> tuple:
    """
    Check if a step can be run based on its dependencies.

    Args:
        video_path: Path to video file
        step_name: Name of step to check

    Returns:
        Tuple of (can_run: bool, reason: str)
    """
    steps = detect_transcription_progress(video_path)
    current_status = steps.get(step_name, {}).get('status')

    # Check if step is already completed
    if current_status == 'completed':
        return (True, 'Step already completed; reset this step to run it again')

    # Check if all dependencies are met
    dependencies = get_step_dependencies(step_name)

    for dep in dependencies:
        dep_status = steps.get(dep, {}).get('status')
        if dep_status != 'completed':
            return (False, f'Requires {dep} to be completed first')

    return (True, 'Ready to run')
