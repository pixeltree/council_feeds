#!/usr/bin/env python3
"""
Script to post-process recordings that haven't been processed yet.
Can be run manually or scheduled via cron.
"""

import os
import sys
import logging
from typing import Dict, Any
from post_processor import PostProcessor
import database as db
from config import POST_PROCESS_SILENCE_THRESHOLD_DB, POST_PROCESS_MIN_SILENCE_DURATION

logger = logging.getLogger(__name__)


def process_unprocessed_recordings(limit: int = 50) -> Dict[str, Any]:
    """
    Find and process all recordings that haven't been post-processed yet.

    Args:
        limit: Maximum number of recordings to process

    Returns:
        Dictionary with processing statistics
    """
    logger.info("=" * 60)
    logger.info("POST-PROCESSING UNPROCESSED RECORDINGS")
    logger.info("=" * 60)

    # Get unprocessed recordings
    recordings = db.get_unprocessed_recordings(limit=limit)

    if not recordings:
        logger.info("No unprocessed recordings found.")
        return {
            "total": 0,
            "processed": 0,
            "failed": 0,
            "skipped": 0
        }

    logger.info(f"Found {len(recordings)} unprocessed recording(s)")

    # Initialize post-processor
    processor = PostProcessor(
        silence_threshold_db=POST_PROCESS_SILENCE_THRESHOLD_DB,
        min_silence_duration=POST_PROCESS_MIN_SILENCE_DURATION
    )

    stats = {
        "total": len(recordings),
        "processed": 0,
        "failed": 0,
        "skipped": 0
    }

    for i, recording in enumerate(recordings, 1):
        logger.info(f"[{i}/{len(recordings)}] Processing recording ID {recording['id']}")
        logger.info(f"  File: {recording['file_path']}")
        logger.info(f"  Meeting: {recording['meeting_title'] or 'Unknown'}")

        # Check if file exists
        if not os.path.exists(recording['file_path']):
            logger.warning(f"  File not found - skipping")
            db.update_post_process_status(recording['id'], 'failed', 'File not found')
            stats['failed'] += 1
            continue

        # Process the recording
        try:
            result = processor.process_recording(
                recording['file_path'],
                recording_id=recording['id']
            )

            if result.get('success'):
                stats['processed'] += 1
                logger.info(f"  Successfully processed - {result.get('segments_created', 0)} segments created")
            elif result.get('deleted'):
                stats['processed'] += 1
                logger.info(f"  Processed - recording removed (no audio)")
            else:
                stats['failed'] += 1
                logger.error(f"  Processing failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"  Exception during processing: {e}", exc_info=True)
            db.update_post_process_status(recording['id'], 'failed', str(e))
            stats['failed'] += 1

    # Print summary
    logger.info("=" * 60)
    logger.info("PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total recordings:    {stats['total']}")
    logger.info(f"Successfully processed: {stats['processed']}")
    logger.info(f"Failed:              {stats['failed']}")
    logger.info(f"Skipped:             {stats['skipped']}")
    logger.info("=" * 60)

    return stats


if __name__ == '__main__':
    # Configure logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Parse command line arguments
    limit = 50
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            logger.error(f"Usage: {sys.argv[0]} [limit]")
            logger.error(f"  limit: Maximum number of recordings to process (default: 50)")
            sys.exit(1)

    # Run processing
    stats = process_unprocessed_recordings(limit=limit)

    # Exit with appropriate code
    sys.exit(0 if stats['failed'] == 0 else 1)
