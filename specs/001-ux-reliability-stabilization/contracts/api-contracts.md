# Interface & State Machine Contracts: Anbar Stabilization

## 1. REST API Contracts

### POST /api/v1/admin/objects/move
Moves multiple objects to a destination directory prefix.
- **Request Body**:
  ```json
  {
    "ids": ["FuYGddJNWTGh", "kd2qu7aYzWfv"],
    "dest": "documents/archive"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "moved": 2,
    "skipped": []
  }
  ```
- **Errors**:
  - `401 Unauthorized`: Missing or invalid admin session/key.
  - `400 Bad Request`: Invalid payload shape.

### POST /api/v1/admin/folders/rename
Renames a folder prefix across all descendant objects.
- **Request Body**:
  ```json
  {
    "old_path": "documents/temp",
    "new_path": "documents/archive"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "status": "ok",
    "renamed": 5
  }
  ```

### GET /api/v1/admin/objects
Lists objects from the SQLite database (unbounded by Telegram readiness).
- **Query Parameters**:
  - `limit`: `int` (default 50, max 500)
  - `offset`: `int` (default 0)
  - `prefix`: `string` (optional folder prefix filter)
- **Response (200 OK)**:
  ```json
  {
    "objects": [
      {
        "id": "FuYGddJNWTGh",
        "filename": "video.mkv",
        "size": 16777216,
        "content_type": "video/x-matroska",
        "created_at": 1727712000,
        "hasThumb": false,
        "downloaded": 12
      }
    ],
    "count": 1
  }
  ```

### GET /f/{id} (Media Streaming & Range)
Streams object bytes with HTTP Range support.
- **Request Headers**:
  - `Range`: `bytes=0-1048575` (optional)
- **Response Headers**:
  - `Content-Type`: `video/x-matroska` (or appropriate media type)
  - `Accept-Ranges`: `bytes`
  - `Content-Disposition`: `inline` (when previewing media)
  - `Content-Range`: `bytes 0-1048575/16777216` (on 206 Partial Content)

---

## 2. Frontend State Machine & Client Contracts

### Selection Manager Contract
- **Method**: `toggleSelection(id: string): void`
  - Mutates `selSet`.
  - Toggles `.selected` on the single corresponding row/card element.
  - Updates checkbox `.checked` directly.
  - Updates selection counter in toolbar using `selSet.size`.
- **Method**: `selectAll(visibleList: FileObject[]): void`
  - Adds all visible IDs to `selSet`.
  - Batch toggles `.selected` class on all existing child DOM nodes in `#rows` / `.gallery`.
  - Sets all `.selbox` checkboxes to `checked = true`.
  - **Invariant**: MUST NOT call `renderRows()` or `renderGallery()`.
- **Method**: `deselectAll(): void`
  - Clears `selSet`.
  - Removes `.selected` from all DOM nodes; sets checkboxes to `checked = false`.
  - **Invariant**: MUST NOT call `renderRows()` or `renderGallery()`.

### Move Workflow Contract
- **State**: `in_flight`
  - `#moveOk` button disabled and shows loading indicator (`"انتقال …"` / spinner).
  - `#moveCancel` button disabled.
  - `#moveModal` remains open.
- **Validation**:
  - `dest.startsWith(sourceFolder + "/")` → Reject with inline warning: "Cannot move a folder into itself".
  - `dest === currentFolder` → Reject with inline warning: "Items are already in this destination".

### Search Synchronizer Contract
- **Method**: `clearSearch(): void`
  - `clearTimeout(searchDebounceTimer)`.
  - `fQuery = ""`.
  - `$("#fSearch").value = ""`.
  - `evictFolderViewCache()`.
  - `renderRows()`.

### ApiClient Retry Contract
- **On 401 Response**:
  - If `_apiKey` is available:
    - If `reLoginPromise` is null: start `fetch("/ui/login")` and store promise.
    - Await `reLoginPromise`.
    - If re-login succeeded: transparently retry the original `fetch(path, opt)` once and return its response.
    - If re-login failed or retry 401s: clear credentials, flip `authed = false`, show login.
