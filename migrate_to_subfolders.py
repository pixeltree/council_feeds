#!/usr/bin/env python3
"""
Migration script to reorganize recordings from flat structure to subfolders.

This script:
1. Scans the recordings directory for all files
2. Groups files by recording base name (e.g., council_meeting_20260128_093208)
3. Creates a subfolder for each recording
4. Moves all related files into the subfolder
5. Updates database paths for recordings and segments
"""

import os
import sys
import shutil
import logging
import re
from typing import Dict, List, Set
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db
from config import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_recording_base_name(filename: str) -> str:
    """Extract the base recording name from a filename.

    Examples:
        council_meeting_20260128_093208.mkv -> council_meeting_20260128_093208
        council_meeting_20260128_093208.mkv.transcript.json -> council_meeting_20260128_093208
        council_meeting_20260128_093208_segment_029.mkv -> council_meeting_20260128_093208
    """
    # Remove any file extensions first
    base = filename

    # Handle segment files
    segment_match = re.match(r'(council_meeting_\d{8}_\d{6})_segment_\d+', base)
    if segment_match:
        return segment_match.group(1)

    # Handle regular recordings with extensions
    match = re.match(r'(council_meeting_\d{8}_\d{6})', base)
    if match:
        return match.group(1)

    return base


def group_files_by_recording(recordings_dir: str) -> Dict[str, List[str]]:
    """Group all files in recordings directory by their recording base name.

    Returns:
        Dictionary mapping recording base name to list of full file paths
    """
    groups: Dict[str, List[str]] = defaultdict(list)

    if not os.path.exists(recordings_dir):
        logger.warning(f"Recordings directory not found: {recordings_dir}")
        return groups

    # Scan all files in recordings directory (flat structure only)
    for filename in os.listdir(recordings_dir):
        file_path = os.path.join(recordings_dir, filename)

        # Skip directories (already migrated or segments folders)
        if os.path.isdir(file_path):
            logger.debug(f"Skipping directory: {filename}")
            continue

        # Skip hidden files
        if filename.startswith('.'):
            continue

        # Extract recording base name
        base_name = extract_recording_base_name(filename)
        if base_name:
            groups[base_name].append(file_path)
        else:
            logger.warning(f"Could not determine recording base name for: {filename}")

    return groups


def migrate_recording_group(base_name: str, file_paths: List[str], recordings_dir: str, dry_run: bool = False) -> bool:
    """Migrate a group of related files into a subfolder.

    Args:
        base_name: Recording base name (e.g., council_meeting_20260128_093208)
        file_paths: List of full file paths to migrate
        recordings_dir: Base recordings directory
        dry_run: If True, only log what would be done without making changes

    Returns:
        True if successful, False otherwise
    """
    # Create subfolder path
    subfolder = os.path.join(recordings_dir, base_name)

    logger.info(f"\nMigrating {len(file_paths)} file(s) for: {base_name}")

    if not dry_run:
        # Create subfolder
        try:
            os.makedirs(subfolder, exist_ok=True)
            logger.info(f"  Created subfolder: {subfolder}")
        except Exception as e:
            logger.error(f"  Failed to create subfolder {subfolder}: {e}")
            return False
    else:
        logger.info(f"  [DRY RUN] Would create subfolder: {subfolder}")

    # Track path mappings for database updates
    path_mappings: Dict[str, str] = {}

    # Move each file
    for old_path in file_paths:
        filename = os.path.basename(old_path)
        new_path = os.path.join(subfolder, filename)

        if not dry_run:
            try:
                shutil.move(old_path, new_path)
                logger.info(f"  Moved: {filename}")
                path_mappings[old_path] = new_path
            except Exception as e:
                logger.error(f"  Failed to move {filename}: {e}")
                return False
        else:
            logger.info(f"  [DRY RUN] Would move: {filename}")
            path_mappings[old_path] = new_path

    # Update database paths
    if not dry_run and path_mappings:
        update_database_paths(path_mappings)

    return True


def update_database_paths(path_mappings: Dict[str, str]) -> None:
    """Update database with new file paths.

    Args:
        path_mappings: Dictionary mapping old path to new path
    """
    logger.info("  Updating database paths...")

    with db.get_db_connection() as conn:
        cursor = conn.cursor()

        # Update recordings table
        for old_path, new_path in path_mappings.items():
            # Update main file_path
            cursor.execute("""
                UPDATE recordings
                SET file_path = ?
                WHERE file_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated recording: {os.path.basename(old_path)}")

            # Update transcript_path
            cursor.execute("""
                UPDATE recordings
                SET transcript_path = ?
                WHERE transcript_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated transcript path: {os.path.basename(old_path)}")

            # Update wav_path
            cursor.execute("""
                UPDATE recordings
                SET wav_path = ?
                WHERE wav_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated wav path: {os.path.basename(old_path)}")

            # Update diarization paths
            cursor.execute("""
                UPDATE recordings
                SET diarization_pyannote_path = ?
                WHERE diarization_pyannote_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated pyannote path: {os.path.basename(old_path)}")

            cursor.execute("""
                UPDATE recordings
                SET diarization_gemini_path = ?
                WHERE diarization_gemini_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated gemini path: {os.path.basename(old_path)}")

            # Update segments table
            cursor.execute("""
                UPDATE segments
                SET file_path = ?
                WHERE file_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated segment: {os.path.basename(old_path)}")

            # Update segment transcript_path
            cursor.execute("""
                UPDATE segments
                SET transcript_path = ?
                WHERE transcript_path = ?
            """, (new_path, old_path))
            if cursor.rowcount > 0:
                logger.info(f"    Updated segment transcript: {os.path.basename(old_path)}")


def main():
    """Main migration function."""
    import argparse

    parser = argparse.ArgumentParser(description='Migrate recordings to subfolder structure')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--recordings-dir', default=OUTPUT_DIR,
                       help=f'Recordings directory (default: {OUTPUT_DIR})')

    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Recording Structure Migration")
    logger.info("=" * 70)
    logger.info(f"Recordings directory: {args.recordings_dir}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info("=" * 70)

    if args.dry_run:
        logger.info("\nDRY RUN MODE - No changes will be made\n")
    else:
        logger.warning("\nLIVE MODE - Files and database will be modified!")
        response = input("Continue? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Migration cancelled.")
            return

    # Group files by recording
    logger.info("\nScanning recordings directory...")
    groups = group_files_by_recording(args.recordings_dir)

    if not groups:
        logger.info("No files found to migrate.")
        return

    logger.info(f"Found {len(groups)} recording(s) to migrate")

    # Migrate each group
    success_count = 0
    failed_count = 0

    for base_name, file_paths in sorted(groups.items()):
        if migrate_recording_group(base_name, file_paths, args.recordings_dir, args.dry_run):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("Migration Summary")
    logger.info("=" * 70)
    logger.info(f"Successfully migrated: {success_count}")
    logger.info(f"Failed: {failed_count}")

    if args.dry_run:
        logger.info("\nDRY RUN complete. Run without --dry-run to apply changes.")
    else:
        logger.info("\nMigration complete!")

    logger.info("=" * 70)


if __name__ == '__main__':
    main()
