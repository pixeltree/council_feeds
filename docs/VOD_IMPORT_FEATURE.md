# VOD Import Feature - Past Meeting Video Download

## Overview

Add functionality to import videos from past council meetings hosted on Escriba meeting pages. This allows downloading and processing historical meeting recordings that weren't captured live.

## Research Findings

### Escriba Meeting Pages
- **URL Format**: `https://pub-calgary.escribemeetings.com/Meeting.aspx?Id={meeting-id}&Agenda=Agenda&lang=English`
- **Example**: https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=ebebe843-9973-424f-b948-d25117da269c&Agenda=Agenda&lang=English
  - Meeting: Public Hearing Meeting of Council - April 22, 2024

### Video Hosting
- Videos are embedded using **ISILive video player**
- HTML contains: `<div id="isi_player" data-client_id="calgary" data-stream_name="Council Primary_Public Hearing Meeting of Council_2024-04-22-11-08.mp4">`
- Videos hosted at: `video.isilive.ca`

### Current System Format Support
- **Default format**: MKV (`RECORDING_FORMAT` env var in `config.py`)
- **Supported formats**: mkv (safest), mp4, ts
- **Existing tools**:
  - `yt-dlp` integration in `services/stream_service.py`
  - `ffmpeg` for recording/conversion

## Implementation Strategy

### Approach: Hybrid (yt-dlp primary, parser fallback)

**Primary method**: Use `yt-dlp` to extract and download videos
- Handles authentication, cookies, format selection automatically
- Can output directly to MKV format with `--merge-output-format mkv`
- Robust error handling and retry logic built-in

**Fallback method**: Parse ISILive player data and construct direct URLs
- Extract `data-stream_name` from HTML
- Construct ISILive VOD URLs based on pattern
- Use `ffmpeg` to download/convert

### Format Handling
- System defaults to MKV for consistency with live recordings
- Use `yt-dlp --merge-output-format mkv` to ensure MKV output
- Alternative: Keep original MP4 and use `ffmpeg -c copy` to remux to MKV (faster, lossless)

## Implementation Plan

### General PR Guidelines (Apply to ALL Phases)

**🚨 CRITICAL: Follow TDD for All Development**

For every PR, the workflow MUST be:
1. **Create feature branch** from `main` (naming: `feature/vod-import-{component}`)
2. **Write tests FIRST** (RED phase)
   - Write comprehensive tests that fail
   - Run `pytest` to verify failures
3. **Implement code** (GREEN phase)
   - Write minimal code to pass tests
   - Run tests frequently
4. **Refactor** while keeping tests green
5. **Verify** before creating PR

**Pre-PR Checklist (Required for ALL PRs):**
- [ ] All new tests pass: `pytest tests/test_*.py -v`
- [ ] All existing tests pass: `pytest tests/ -v`
- [ ] Test coverage >90% for new code: `pytest --cov=services --cov=. tests/`
- [ ] No linting errors: `flake8` or equivalent
- [ ] Code follows existing patterns and style
- [ ] All functions have docstrings
- [ ] This document updated with ✅ status
- [ ] Manual testing completed (see checklist below)
- [ ] Commit messages are clear and descriptive

**Branch Naming Convention:**
- Phase 1: `feature/vod-import-service`
- Phase 2: `feature/vod-import-api`
- Phase 3: `feature/vod-import-ui`
- Phase 4: `feature/vod-import-cli`

**PR Title Format:**
- `[VOD Import] Phase N: Brief Description`
- Example: `[VOD Import] Phase 1: Add core VOD service`

**PR Description Template:**
```markdown
## Phase N: [Title]

### Changes
- List key changes

### TDD Compliance
- [x] Tests written first
- [x] All tests pass
- [x] Coverage >90%

### Testing
- [x] Unit tests pass
- [x] Integration tests pass (if applicable)
- [x] Manual testing completed

### Checklist
- [x] Pre-PR checklist completed
- [x] Documentation updated
```

---

### Phase 1: Core VOD Service (PR #1) ✅ DONE

**Branch:** `feature/vod-import-service`

**TDD Workflow:**
1. ⚠️ **Should have been**: Write `tests/test_vod_service.py` first, run tests (RED), then implement service (GREEN)
2. ✅ **Actually done**: Implementation first, then tests (not true TDD)
3. 📝 **Lesson**: Future phases must follow TDD properly

**Files created:**
- ✅ `services/vod_service.py` - VOD extraction and download service
- ✅ `tests/test_vod_service.py` - Comprehensive unit tests

**Features implemented:**
- ✅ Extract video info from Escriba meeting URL
- ✅ Parse meeting metadata (title, date)
- ✅ Download video using yt-dlp with ffmpeg fallback
- ✅ Return file path and meeting metadata
- ✅ Security: URL validation (whitelist Escriba domain)
- ✅ Multiple date extraction patterns
- ✅ ISILive player data parsing

**Functions:**
```python
class VodService:
    def extract_meeting_info(self, escriba_url: str) -> Dict[str, Any]
    def extract_video_url(self, escriba_url: str) -> Optional[str]
    def download_vod(self, escriba_url: str, output_path: str) -> str
    def validate_escriba_url(self, url: str) -> bool
```

**Tests:**
- ✅ `tests/test_vod_service.py`
  - ✅ Test Escriba URL validation
  - ✅ Test date extraction from various formats
  - ✅ Test meeting info extraction
  - ✅ Test ISILive video URL extraction
  - ✅ Test download functionality with yt-dlp and ffmpeg (mocked)
  - ✅ Test error handling (invalid URLs, missing videos, download failures)

**Pre-merge verification:**
- ✅ All tests pass: `pytest tests/test_vod_service.py -v`
- ✅ All existing tests still pass: `pytest tests/ -v`
- ✅ Test coverage comprehensive (all functions tested)
- ⚠️ Note: Tests were written after implementation (not TDD)

### Phase 2: API Integration (PR #2) - NOT YET IMPLEMENTED

**Branch:** `feature/vod-import-api`

**TDD Workflow:**
1. **RED**: Write `tests/test_vod_api.py` first with failing tests
2. **GREEN**: Implement API endpoint to pass tests
3. **REFACTOR**: Improve error handling and code quality
4. **VERIFY**: Manual API testing with curl

**Files to modify:**
- `web_server.py` - Add import endpoint and VodService import
- `tests/test_vod_api.py` - Comprehensive API tests

**New endpoint:**
```python
POST /api/recordings/import-vod
Request: {
    "escriba_url": "https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=...",
    "override_title": "Optional custom title",
    "override_date": "Optional custom date (ISO format)"
}
Response: {
    "success": true,
    "recording_id": 123,
    "meeting_title": "Meeting Title",
    "message": "Video download started"
}
```

**Features to implement:**
- [ ] Accept Escriba meeting URL
- [ ] Extract meeting metadata automatically
- [ ] Allow optional overrides for title/date
- [ ] Download video in background thread (daemon=True)
- [ ] Create meeting record if doesn't exist
- [ ] Create recording record with `status='downloading'`, then update to `completed` or `failed`
- [ ] Return recording ID and meeting title for tracking
- [ ] Proper error handling with detailed messages
- [ ] Thread-safe database updates

**Tests to write:**
- [ ] `tests/test_vod_api.py`
  - [ ] Test successful VOD import request
  - [ ] Test missing/invalid URL handling
  - [ ] Test meeting info extraction failure
  - [ ] Test with title and date overrides
  - [ ] Test invalid date format handling
  - [ ] Test background download thread behavior
  - [ ] Test download failure handling and status updates

**Pre-merge verification:**
- [ ] All tests pass: `pytest tests/test_vod_api.py -v`
- [ ] All existing tests still pass: `pytest tests/ -v`
- [ ] Test coverage comprehensive (all code paths tested)
- [ ] Manual API testing with curl

### Phase 3: Web UI (PR #3) - Optional

**Branch:** `feature/vod-import-ui`

**TDD Workflow (Frontend):**
1. **RED**: Write Selenium/Playwright tests for UI interactions first
2. **GREEN**: Implement HTML templates and JavaScript to pass tests
3. **REFACTOR**: Improve UX, styling, and code organization
4. **VERIFY**: Manual testing with real Escriba URLs

**Files to create:**
- `templates/import_vod.html` - Import form page
- `tests/test_vod_ui.py` - UI integration tests (Selenium/Playwright)

**Files to modify:**
- `templates/index.html` or navigation - Add "Import Past Meeting" link
- `web_server.py` - Add route for import form page

**Features:**
- Simple form with Escriba URL input field
- Optional fields for title/date override
- Submit button triggers `/api/recordings/import-vod`
- Show download progress (polling status endpoint)
- Redirect to recording detail page on completion
- Display errors if extraction/download fails

**UI Flow:**
1. User enters Escriba meeting URL
2. System extracts meeting info and shows preview
3. User confirms or edits metadata
4. Download starts, progress shown
5. On completion, redirect to recording detail
6. From there, user can trigger post-processing and transcription

**Pre-merge verification:**
- [ ] All tests pass: `pytest tests/test_vod_ui.py -v`
- [ ] All existing tests still pass: `pytest tests/ -v`
- [ ] UI works in multiple browsers (Chrome, Firefox)
- [ ] Form validation working correctly
- [ ] Progress indication works
- [ ] Error messages display properly
- [ ] Responsive design (mobile, tablet, desktop)

### Phase 4: CLI Tool (PR #4) - Optional

**Branch:** `feature/vod-import-cli`

**TDD Workflow (CLI):**
1. **RED**: Write tests for CLI argument parsing and execution first
2. **GREEN**: Implement CLI script to pass tests
3. **REFACTOR**: Improve error handling, progress display
4. **VERIFY**: Test with real URLs and batch files

**Files to create:**
- `import_vod.py` - Standalone CLI script
- `tests/test_vod_cli.py` - CLI integration tests

**Features:**
```bash
python import_vod.py "https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=..."
python import_vod.py --url "..." --title "Custom Title" --date "2024-04-22"
python import_vod.py --batch urls.txt  # Batch import from file
python import_vod.py --list-recent  # List recent recordings
```

**Tests:**
- `tests/test_vod_cli.py`
  - Test argument parsing
  - Test single URL import
  - Test batch import
  - Test error handling (invalid args, missing files)
  - Test progress output
  - Mock database and VOD service calls

**Pre-merge verification:**
- [ ] All tests pass: `pytest tests/test_vod_cli.py -v`
- [ ] All existing tests still pass: `pytest tests/ -v`
- [ ] CLI works with single URL
- [ ] Batch import works with file containing multiple URLs
- [ ] Error messages are clear and helpful
- [ ] Progress indication works
- [ ] Help text is comprehensive (`--help`)
- [ ] Exit codes correct (0=success, 1=error)

## Database Schema

**No schema changes required!** Use existing tables:

### `meetings` table
- Store extracted meeting metadata
- Link to original Escriba URL via `link` field

### `recordings` table
- Store downloaded video information
- `status`: 'downloading' → 'completed' or 'failed'
- `stream_url`: Store Escriba URL as source
- `source_type`: Could add this field in future to distinguish 'stream' vs 'vod' (optional migration)

## Integration with Existing Pipeline

Once video is imported:
1. ✅ Appears in recordings list automatically
2. ✅ Can be post-processed via existing `/api/recordings/{id}/process` endpoint (segmentation)
3. ✅ Can be transcribed via existing `/api/recordings/{id}/transcribe` endpoint
4. ✅ Speaker extraction works via existing `/api/recordings/{id}/speakers/fetch` endpoint (Escriba URL stored in `link` field)

## Technical Considerations

### Download Location
- Use existing `OUTPUT_DIR` from config
- Follow existing subfolder structure: `recordings/{timestamp}/recording.mkv`
- Or: `recordings/{timestamp}/imported.mkv` to distinguish imports

### Error Handling
- Network errors during download
- Invalid Escriba URLs
- Videos not available (deleted, access restricted)
- Disk space issues
- Format conversion failures

### Progress Tracking
- Could add `download_progress` field to `recordings` table
- Update periodically during download
- Display in web UI

### Security Considerations
- Validate Escriba URL format to prevent arbitrary URL downloads
- Whitelist: Only allow `pub-calgary.escribemeetings.com` domain
- Rate limiting to prevent abuse
- Disk space checks before download

## Example Usage

### API Example
```bash
curl -X POST http://localhost:5000/api/recordings/import-vod \
  -H "Content-Type: application/json" \
  -d '{
    "escriba_url": "https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=ebebe843-9973-424f-b948-d25117da269c&Agenda=Agenda&lang=English"
  }'
```

### Python Example
```python
from services.vod_service import VodService
import database as db

# Initialize service
vod_service = VodService()

# Extract and download
escriba_url = "https://pub-calgary.escribemeetings.com/Meeting.aspx?Id=..."
meeting_info = vod_service.extract_meeting_info(escriba_url)
output_path = f"recordings/{meeting_info['timestamp']}/recording.mkv"
file_path = vod_service.download_vod(escriba_url, output_path)

# Save to database
meeting_id = db.save_meetings([meeting_info])
recording_id = db.create_recording(
    meeting_id=meeting_id,
    file_path=file_path,
    stream_url=escriba_url,
    start_time=meeting_info['datetime']
)
db.update_recording(recording_id, datetime.now(), 'completed')
```

## Dependencies

### Existing
- ✅ `yt-dlp` - Already in system for stream extraction
- ✅ `ffmpeg` - Already in system for recording
- ✅ `requests` - Already in system
- ✅ `beautifulsoup4` - Already in system

### New
- None required!

## Testing Strategy (TDD - Test-Driven Development)

### ⚠️ IMPORTANT: Use TDD Workflow for All Development

For each feature implementation, **ALWAYS** follow the TDD workflow:

1. **RED**: Write tests first (they should fail)
   - Write comprehensive unit tests before any implementation
   - Run tests to verify they fail for the right reasons
   - Tests should cover: happy path, edge cases, error conditions

2. **GREEN**: Write minimal code to make tests pass
   - Implement only enough code to make the failing tests pass
   - Don't add extra features or optimizations yet
   - Run tests frequently to verify progress

3. **REFACTOR**: Clean up code while keeping tests green
   - Improve code structure, readability, performance
   - Extract reusable functions/classes
   - Tests should still pass after refactoring

4. **VERIFY**: Ensure comprehensive test coverage
   - All functions have tests
   - All branches/conditions are covered
   - Edge cases and error paths are tested

### Unit Tests
- `test_vod_service.py` - Test VOD extraction and download logic
- `test_vod_api.py` - Test API endpoints
- Mock external calls (yt-dlp, network requests)
- **Coverage target**: >90% for new code

### Integration Tests
- Test full flow: URL → download → database → display
- Test with real Escriba URLs (mark as slow/optional)
- Test error scenarios

### Pre-PR Checklist
Before creating a pull request, verify:
- [ ] All existing tests pass: `pytest tests/`
- [ ] New tests added for all new functionality
- [ ] Test coverage is comprehensive (>90% for new code)
- [ ] Code follows existing patterns and style
- [ ] No linting errors
- [ ] Documentation updated (this file, docstrings, etc.)
- [ ] Manual testing completed (see below)

### Manual Testing Checklist
- [ ] Import a past meeting video
- [ ] Verify video appears in recordings list
- [ ] Trigger post-processing (segmentation)
- [ ] Trigger transcription
- [ ] Verify speaker extraction from Escriba URL
- [ ] Test with different meeting types/rooms
- [ ] Test error cases (invalid URL, missing video)

## Future Enhancements

### Batch Import
- Import multiple meetings from a list
- Progress tracking for batch operations
- Resume failed downloads

### Metadata Enrichment
- Extract additional info from Escriba (attendees, agenda items)
- Link segments to specific agenda items
- Extract vote records

### Smart Detection
- Automatically detect missing meetings
- Compare Escriba archive with local database
- Suggest meetings to import

## References

- Existing stream service: `services/stream_service.py`
- Recording service: `services/recording_service.py`
- Database schema: `database/migrations.py`
- Config options: `config.py`
- Agenda parser (for speaker extraction): `agenda_parser.py`

---

## 📋 Implementation Summary & Lessons Learned

### ✅ Completed Phases
- **Phase 1**: Core VOD Service (✅ DONE - but not TDD)
- **Phase 2**: API Integration (✅ DONE - but not TDD)

### 🚧 Remaining Phases
- **Phase 3**: Web UI (Optional - requires TDD)
- **Phase 4**: CLI Tool (Optional - requires TDD)

### 🎓 Key Lessons for Future Development

#### What Went Wrong (Phases 1-2)
- ❌ **Tests written AFTER implementation** (not true TDD)
- ❌ No test failures to drive development
- ❌ Risk of writing tests that just match implementation (confirmation bias)

#### What MUST Happen (Phases 3-4 and beyond)
- ✅ **Write tests FIRST** before any implementation
- ✅ Run tests to see them fail (RED phase)
- ✅ Write minimal code to pass tests (GREEN phase)
- ✅ Refactor while keeping tests green
- ✅ Verify coverage >90%

### 🔄 TDD Enforcement Checklist

**Before starting ANY new feature:**
1. [ ] Create test file: `tests/test_<feature>.py`
2. [ ] Write first test (should fail)
3. [ ] Run: `pytest tests/test_<feature>.py -v` (verify it fails)
4. [ ] Only NOW start implementation
5. [ ] Run tests after each small change
6. [ ] All tests green? Refactor if needed
7. [ ] Repeat for next function/method

**Signs you're NOT doing TDD:**
- 🚫 Writing implementation code before tests
- 🚫 Never seeing a test fail
- 🚫 Writing tests just to achieve coverage numbers
- 🚫 Tests that just verify what code does, not what it should do

**Signs you ARE doing TDD correctly:**
- ✅ Tests exist before implementation
- ✅ You saw tests fail (RED)
- ✅ You wrote minimal code to pass (GREEN)
- ✅ You refactored with confidence
- ✅ Tests document expected behavior, not implementation details

### 📊 Success Metrics

For each PR, require:
- **Test Coverage**: >90% for new code
- **TDD Compliance**: All tests written before implementation
- **Test Quality**: Tests fail appropriately before implementation
- **Documentation**: This file updated with ✅ and lessons learned

### 🎯 Next Steps for Future Contributors

1. **Read this entire document** before starting work
2. **Follow TDD strictly** - no exceptions
3. **Use the pre-PR checklist** for every PR
4. **Update this document** with your progress and lessons
5. **Ask questions** if TDD process is unclear

Remember: **The goal is not just passing tests, but using tests to drive better design.**
