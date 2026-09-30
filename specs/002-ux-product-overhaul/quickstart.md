# Quickstart & Validation Guide: Product Quality & UX Overhaul

## Runnable Validation Scenarios

### Scenario 1: Deep Visual Folder Move Navigation (5 Levels Deep)
1. Launch local dev server: `python -m anbar.main`.
2. Seed test folder hierarchy:
   ```bash
   curl -X POST http://127.0.0.1:8567/api/v1/admin/folders/create -H "Authorization: Bearer test-admin-key" -d '{"path":"a/b/c/d/e"}'
   ```
3. Open `http://127.0.0.1:8567/` in browser.
4. Select a root file and click "Move".
5. In the move modal:
   - Click folder `a` → view drills down to show folder `b`.
   - Click folder `b` → view drills down to show folder `c`.
   - Click folder `c` → view drills down to show folder `d`.
   - Click breadcrumb segment `b` → view ascends back to `a/b/`.
   - Click "Move Here".
6. *Outcome*: File is moved to `a/b/` with zero manual keyboard typing.

### Scenario 2: Responsive Toolbar Layout Check (Desktop vs Mobile)
1. Open Playwright Chromium browser.
2. Emulate Desktop (1280×800):
   - Verify toolbars align into 2 distinct rows without fragmented line breaks.
3. Emulate Mobile (375×667):
   - Verify buttons collapse secondary text labels, wrap cleanly, and all touch targets measure ≥36px height.
   - Verify zero horizontal page scrolling.

### Scenario 3: Async Operation Guarding Under Latency
1. Throttle API responses with 500ms delay.
2. Rapidly double-click "New Folder" or "Move Here".
3. *Outcome*: The first click immediately disables the button and displays a spinner; the second click is ignored, preventing duplicate folder creation or duplicate move dispatch.
