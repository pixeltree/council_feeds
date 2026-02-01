# Segmentation/Post-Processing Removal - Part 2

## Context

We're removing the segmentation/post-processing feature from the codebase because:
1. We now use cloud-based pyannote transcription on full recordings
2. Segmentation by silence detection is no longer needed
3. It's unused code that adds maintenance burden

**Part 1 (COMPLETED):** Removed core files, config, database schema, and main.py references (940 lines)

**Part 2 (TODO):** Remove remaining references from web_server.py, templates, and tests

## Current State

Part 1 commits on branch `feature/pyannote-cloud-api`:
- `0e180f8` - WIP: Remove segmentation/post-processing feature (part 1)
- `092da43` - Fix syntax errors from segmentation removal

## Part 2 Tasks

### 1. web_server.py Changes

Remove these items from `web_server.py`:

#### Imports (line 19)
```python
from post_processor import PostProcessor  # REMOVE
```

#### Global function (line 42)
```python
def set_post_processor(processor: Any) -> None:  # REMOVE ENTIRE FUNCTION
    """Set the post processor for the web server."""
    global post_processor_service
    post_processor_service = processor
```

#### API Endpoints to REMOVE

1. **`/api/recordings/<int:recording_id>/process`** (~line 1065)
   - POST endpoint to trigger post-processing/segmentation
   - Returns error if already segmented

2. **`/api/recordings/<int:recording_id>/segment`** (~line 398-419)
   - Legacy endpoint (redirects to /process)

3. **`/download/transcript/segment/<int:segment_id>`** (~line 419-440)
   - Download transcript for a segment

4. **`/download/diarization/segment/<int:segment_id>`** (~line 540-573)
   - Download diarization data for a segment

5. **`/download/diarization/pyannote/segment/<int:segment_id>`** (~line 574-595)
   - Download pyannote diarization for segment

6. **`/download/diarization/gemini/segment/<int:segment_id>`** (~line 596-617)
   - Download Gemini diarization for segment

#### Template Routes to UPDATE

1. **`/recordings`** (~line 133)
   - Remove segment info from recordings list
   - Remove: `segments = db.get_segments_by_recording(rec['id'])`
   - Remove: `'segments': segments` from context

2. **`/recording/<int:recording_id>`** (~line 202)
   - Remove: `segments = db.get_segments_by_recording(recording_id)`
   - Remove segment diarization checks (lines 217-234)
   - Remove: `segments=segments` from render_template context

#### VOD Import Auto-processing (~line 847)
```python
# Remove this block:
from config import ENABLE_POST_PROCESSING, POST_PROCESS_SILENCE_THRESHOLD_DB, POST_PROCESS_MIN_SILENCE_DURATION
if ENABLE_POST_PROCESSING and post_processor_service:
    result = post_processor_service.process_recording(output_path, recording_id)
```

#### Transcription Service (~line 1166-1210)
Remove the segment-based transcription logic:
```python
# Remove this entire block:
segments = db.get_segments_by_recording(recording_id)
if segments and recording['is_segmented']:
    # Transcribe each segment
    for idx, segment in enumerate(segments, 1):
        # ... transcription code for segments ...
```

Keep only the "transcribe original recording" path.

#### Global Variables
Remove:
```python
post_processor_service = None  # Line ~38
```

### 2. Template Changes

File: `templates/recording_detail.html`

Remove segment-related UI:
- Segment list display
- Segment download buttons
- Segment transcript/diarization links
- "Process Recording" / "Segment" buttons

### 3. Test File Removals

Remove entire test file:
```bash
git rm tests/test_post_processor.py
```

### 4. Integration Test Updates

File: `tests/test_integration.py`

Remove these test classes/methods:
- `TestPostProcessingIntegration`
- `TestVODImportPostProcessing`
- Any tests that reference segmentation

### 5. Docker Compose (if needed)

Check `docker-compose.yml` for any ENABLE_POST_PROCESSING references (already removed in Part 1).

## Commands to Run

```bash
# Remove test file
git rm tests/test_post_processor.py

# After making changes, test
pytest -x

# Commit
git add -A
git commit -m "Remove segmentation/post-processing feature (part 2)

- Removed post_processor endpoints from web_server.py
- Removed segment UI from templates
- Removed segment download endpoints
- Removed segment-based transcription logic
- Removed test_post_processor.py tests
- Removed segmentation integration tests

Segmentation is no longer needed with cloud transcription.
All transcription now happens on full recordings.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

## Testing Checklist

After Part 2:
- [ ] `pytest` passes (tests collect and run)
- [ ] Web server starts without errors
- [ ] Can view recordings list
- [ ] Can view individual recording details
- [ ] Can trigger transcription on full recordings
- [ ] VOD import works
- [ ] No references to "segment" in error logs

## Estimated Impact

Part 2 will remove approximately:
- ~400-500 lines from web_server.py
- ~200 lines from test_post_processor.py
- ~100 lines from test_integration.py
- ~100-200 lines from templates
- **Total: ~800-1000 additional lines removed**

Combined with Part 1 (940 lines), total removal: **~1,800-2,000 lines**

## Notes

- The `is_segmented` column remains in the database for backwards compatibility (SQLite doesn't support DROP COLUMN easily)
- It's safe to leave it as a dead column
- Migration automatically drops the `segments` table on next run
- This is part of the pyannote cloud API migration (PR #37)
