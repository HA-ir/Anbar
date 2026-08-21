"""Upload endpoints (F2). F1: skeleton with 501 responses."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/upload")
async def upload_multipart():
    raise HTTPException(501, "multipart upload lands in F2")


@router.post("/upload/raw")
async def upload_raw():
    raise HTTPException(501, "raw streaming upload lands in F2")