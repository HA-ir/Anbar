# Quickstart & Validation Guide: Anbar Stabilization

This guide provides runnable scenarios to verify each stabilization area locally and in automated CI.

## Prerequisites
- Python 3.10+ with active `.venv`
- System tools: `ffmpeg` (for media handling tests)
- Node.js (for syntax validation of UI scripts: `node --check`)
- Playwright browsers: `playwright install chromium`

---

## 1. Automated Test Suite Execution

### Full Unit & Integration Test Suite
```bash
pytest -v
```
*Expected Outcome*: All tests pass (including existing 394+ tests and new stabilization unit tests).

### Playwright E2E Browser Suite
```bash
pytest -v tests/test_e2e_playwright.py
```
*Expected Outcome*: All browser journeys pass in headless Chromium, including multi-select, search, and modal interactions.

### Static Analysis & Linter Verification
```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/anbar/api/
```
*Expected Outcome*: Zero violations.

---

## 2. Interactive Browser Validation Scenarios

### Scenario A: Large File Selection (Freeze-Free)
1. Run local development server:
   ```bash
   python -m anbar.main
   ```
2. Navigate to `http://127.0.0.1:8567/` and log in with admin key.
3. Upload or generate a test directory with 100+ files.
4. Toggle "Select All" and "Deselect All" repeatedly.
5. *Verification*: The UI updates instantly (<50ms) without freezing, stuttering, or layout thrashing.

### Scenario B: File Move Progress & Validation
1. Select one or more files in the UI.
2. Click "Move" to open the move modal.
3. Attempt to move a folder into its own subfolder.
   *Verification*: The modal displays an immediate validation error and blocks the submission.
4. Select a valid destination (e.g. Root or target folder) and click confirm.
   *Verification*: The modal displays an active loading spinner, buttons are disabled, and upon completion the view refreshes automatically with a success toast.

### Scenario C: Search Clearing & Stability
1. Type a search query in `#fSearch` (e.g. "sample").
2. Verify matching items appear.
3. Click the clear button ("×") or backspace all text.
4. Wait 5-10 seconds.
5. *Verification*: The search input remains empty and full folder contents remain visible without the query resurrecting.

### Scenario D: Native MKV Playback
1. Upload an MKV file containing H.264/AAC video.
2. Open the file preview modal.
3. *Verification*: Video streams natively via HTTP Range requests in Chromium without displaying "امکان پخش فایل MKV در این مرورگر وجود ندارد".

### Scenario E: Cold Restart Verification
1. Stop the running server (`Ctrl+C`).
2. Start the server again.
3. Reload or navigate to `http://127.0.0.1:8567/`.
4. *Verification*: The file list populates immediately on the root dashboard without navigating into Settings -> Telegram Auth.
