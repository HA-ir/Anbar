"""Download endpoints (F3). F1: skeleton with 501 responses."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{obj_id}")
async def download(obj_id: str):
    raise HTTPException(501, "streaming download lands in F3")


@router.get("/{obj_id}/info")
async def info(obj_id: str):
    raise HTTPException(501, "object info lands in F2")