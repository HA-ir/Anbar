# Interface & Client Component Contracts: Product Quality & UX Overhaul

## 1. Move Browser Interaction Contract

### State Transitions & Methods
- **`initMoveBrowser(ids: string[]): void`**
  - Scans `files` and extracts all unique folder prefixes.
  - Detects source prefix of `ids`.
  - Sets `currentBrowsePrefix = ""` (Root) or parent folder.
  - Renders child folders and breadcrumb trail.
- **`moveBrowseInto(folderPath: string): void`**
  - Updates `currentBrowsePrefix = folderPath`.
  - Re-renders breadcrumbs (`Root / ... / folderName`).
  - Re-renders child folders within `folderPath`.
  - Updates target label: `Target: /${folderPath}`.
  - Validates legality of moving to `currentBrowsePrefix`.
- **`moveBrowseAscend(toPath: string): void`**
  - Resets `currentBrowsePrefix = toPath`.
  - Updates view to show ancestor level.
- **`confirmMove(): Promise<void>`**
  - Validates `currentBrowsePrefix !== sourcePrefix`.
  - Displays spinner on submit button, disables cancel button.
  - Calls `api("/api/v1/admin/objects/move")` or folder rename endpoint.
  - On success: closes modal, clears selection, refreshes file list, displays toast.
  - On error: re-enables buttons, renders inline error message.

---

## 2. Toolbar & Layout Styling Contract

### CSS Class Hierarchy
```css
/* Semantic Groups */
.toolbar-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-sm);
  align-items: center;
  justify-content: space-between;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: var(--sp-xs);
  flex-wrap: wrap;
}

/* Responsive Rules (<480px) */
@media (max-width: 480px) {
  .btn-label-collapse span {
    display: none;
  }
  .btn-label-collapse svg {
    margin: 0;
  }
}
```

---

## 3. Empty State Component Contract

### DOM Layout
```html
<div class="empty-state-box">
  <div class="empty-icon-wrap">
    <!-- SVG illustration -->
  </div>
  <h4 class="empty-title">این پوشه خالی است</h4>
  <p class="empty-desc">فایل‌های خود را به اینجا بکشید یا دکمه آپلود را بزنید.</p>
  <button class="btn btn-primary empty-action-btn">آپلود فایل</button>
</div>
```
