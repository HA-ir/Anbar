# BUG-28: Deploy v0.15.46 UI/UX Revamp to Falkenstein

## Status: COMPLETED

## Deployment Summary

- **Version**: v0.15.46 (commit 90c9271)
- **Server**: Falkenstein (dl.amiri-dev.ir)
- **Path**: /root/anbar
- **Port**: 8318
- **Container**: anbar-anbar-1 (healthy)

## Verification

```bash
curl http://127.0.0.1:8318/healthz
# Response: {"status":"ok","service":"anbar","version":"0.15.46"}
```

## Actions Taken

1. Pulled latest code from origin/main (commit 90c9271)
2. Built Docker image: anbar:prod
3. Deployed via docker compose up -d
4. Verified health check and version

## Time Completed

2026-09-07T21:35Z

---

## BUG-36: Deploy v0.15.50 to Falkenstein (gallery card size + Persian date fix)

### Status: DONE

### Deployment Summary

- **Version**: v0.15.50 (commit 3d7b0db, tag v0.15.50)
- **Server**: Falkenstein (dl.amiri-dev.ir)
- **Path**: /root/anbar
- **Port**: 8318
- **Container**: anbar-anbar-1 (healthy)

### What Changed

- Gallery cards slightly larger: minmax 150px→180px, thumbnail height 110px→130px
- Persian date in table view no longer shows "ساعت" — compact format: "۱۸ شهریور، ۱۲:۲۵"

### Verification

```bash
curl https://dl.amiri-dev.ir/healthz
# Response: {"status":"ok","service":"anbar","version":"0.15.50"}
```

### Actions Taken

1. Pulled latest code from origin/main (commit 3d7b0db)
2. Discovered __init__.py had stale __version__ = "0.15.49" — fixed to "0.15.50"
3. Built Docker image: anbar:prod
4. Removed old container and started fresh with anbar:prod image
5. Verified health check returns version 0.15.50

### Time Completed

2026-09-09T16:52Z

---

## Previous Versions

### v0.15.49
Deployed: 2026-09-07
Commit: fb84161
Note: __version__ mismatch bug — pyproject.toml said 0.15.50 but __init__.py had 0.15.49

### v0.15.46
Deployed: 2026-09-07 (previous release)
Commit: 90c9271
