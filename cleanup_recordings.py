#!/usr/bin/env python3
"""Script to clean up recordings with no associated files."""

import sys
from database.repositories.recordings import get_stale_recordings, delete_recording


def main():
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv
    dry_run_only = '--dry-run' in sys.argv

    print("Finding stale recordings...\n")

    recordings = get_stale_recordings()

    if not recordings:
        print("No stale recordings found. Database is clean!")
        return

    print(f"Found {len(recordings)} stale recordings:\n")

    for rec in recordings:
        print(f"ID {rec['id']}: {rec['file_path']}")
        print(f"  Status: {rec['status']}, Size: {rec['file_size_bytes'] or 'NULL'}")
        print(f"  File exists: {rec['file_exists']}, Actual size: {rec['actual_file_size']}")

    print(f"\n{'='*60}")
    print("DRY RUN - No changes will be made")
    print(f"{'='*60}\n")

    # Show what would be deleted
    for rec in recordings:
        print(f"[DRY RUN] Would delete recording {rec['id']}")

    if dry_run_only:
        print("\nDry run complete. Use --yes to actually delete.")
        return

    print(f"\n{'='*60}")

    if auto_confirm:
        print("Auto-confirming deletion (--yes flag)")
        for rec in recordings:
            delete_recording(rec['id'])
            print(f"Deleted recording {rec['id']}")
        print(f"\nDeleted {len(recordings)} recordings from database.")
        print("\nCleanup complete!")
    else:
        response = input("\nDelete these recordings? (yes/no): ")
        if response.lower() == 'yes':
            for rec in recordings:
                delete_recording(rec['id'])
                print(f"Deleted recording {rec['id']}")
            print(f"\nDeleted {len(recordings)} recordings from database.")
            print("\nCleanup complete!")
        else:
            print("\nCancelled. No changes made.")


if __name__ == "__main__":
    main()
