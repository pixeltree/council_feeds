#!/usr/bin/env python3
"""Script to clean up recordings with no associated files."""

import os
import sqlite3
from pathlib import Path

DB_PATH = "data/council_feeds.db"


def find_recordings_without_files():
    """Find all recordings where the file doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, file_path, status, file_size_bytes
        FROM recordings
    """)

    recordings_to_delete = []

    for row in cursor.fetchall():
        recording_id, file_path, status, file_size = row

        # Check if file exists
        if not os.path.exists(file_path):
            recordings_to_delete.append({
                'id': recording_id,
                'file_path': file_path,
                'status': status,
                'file_size': file_size
            })

    conn.close()
    return recordings_to_delete


def delete_recordings(recording_ids, dry_run=True):
    """Delete recordings and their associated data."""
    if not recording_ids:
        print("No recordings to delete.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for rec_id in recording_ids:
        if dry_run:
            print(f"[DRY RUN] Would delete recording {rec_id}")

            # Show what would be deleted
            cursor.execute("SELECT COUNT(*) FROM segments WHERE recording_id = ?", (rec_id,))
            segment_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM recording_logs WHERE recording_id = ?", (rec_id,))
            log_count = cursor.fetchone()[0]

            print(f"  - {segment_count} segments")
            print(f"  - {log_count} log entries")
        else:
            # Delete associated segments
            cursor.execute("DELETE FROM segments WHERE recording_id = ?", (rec_id,))

            # Delete associated logs
            cursor.execute("DELETE FROM recording_logs WHERE recording_id = ?", (rec_id,))

            # Delete the recording itself
            cursor.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))

            print(f"Deleted recording {rec_id}")

    if not dry_run:
        conn.commit()
        print(f"\nDeleted {len(recording_ids)} recordings from database.")

    conn.close()


def main():
    import sys

    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv
    dry_run_only = '--dry-run' in sys.argv

    print("Finding recordings without files...\n")

    recordings = find_recordings_without_files()

    if not recordings:
        print("No recordings found without files. Database is clean!")
        return

    print(f"Found {len(recordings)} recordings without files:\n")

    for rec in recordings:
        print(f"ID {rec['id']}: {rec['file_path']}")
        print(f"  Status: {rec['status']}, Size: {rec['file_size'] or 'NULL'}")

    print(f"\n{'='*60}")
    print("DRY RUN - No changes will be made")
    print(f"{'='*60}\n")

    recording_ids = [rec['id'] for rec in recordings]
    delete_recordings(recording_ids, dry_run=True)

    if dry_run_only:
        print("\nDry run complete. Use --yes to actually delete.")
        return

    print(f"\n{'='*60}")

    if auto_confirm:
        print("Auto-confirming deletion (--yes flag)")
        delete_recordings(recording_ids, dry_run=False)
        print("\nCleanup complete!")
    else:
        response = input("\nDelete these recordings? (yes/no): ")
        if response.lower() == 'yes':
            delete_recordings(recording_ids, dry_run=False)
            print("\nCleanup complete!")
        else:
            print("\nCancelled. No changes made.")


if __name__ == "__main__":
    main()
