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

## Previous Versions

### v0.15.45
Deployed: 2026-09-07 (previous release)
Commit: be4db29
