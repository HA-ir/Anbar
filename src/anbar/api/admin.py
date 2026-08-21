"""Admin endpoints (F4). F1: status skeleton."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/admin/status")
async def status(request: Request):
    s = request.app.state.settings
    db = request.app.state.db
    backend = request.app.state.backend
    return {
        "status": "ok",
        "backend": getattr(backend, "name", s.backend.value),
        "auth_enabled": s.auth_enabled,
        "objects": len(db.list_objects(limit=1000)),
        "time": int(time.time()),
    }