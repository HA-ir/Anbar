"""Object layer: chunking, manifests, object ids.

The chunker is backend-agnostic: it yields fixed-size chunks from an async
byte stream while maintaining an incremental SHA-256 over the joined bytes.
Small files produce a single-element manifest — one code path for all sizes.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

# base62 alphabet, no ambiguous chars (0/O, 1/I/l)
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_ID_LEN = 12


def new_object_id() -> str:
    """Cryptography-random base62 id (12 chars ≈ 68 bits)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_ID_LEN))


@dataclass
class Chunk:
    index: int
    size: int
    file_id: str = ""  # filled by the storage layer
    message_id: int | None = None  # bot backend: channel message holding the blob


@dataclass
class Manifest:
    """Ordered chunk list persisted as JSON in the objects table."""

    chunks: list[Chunk] = field(default_factory=list)
    total_size: int = 0

    def to_json(self) -> str:
        import json

        chunks = [
            {"i": c.index, "s": c.size, "f": c.file_id, "m": c.message_id}
            for c in self.chunks
        ]
        return json.dumps({"chunks": chunks, "size": self.total_size}, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> Manifest:
        import json

        d = json.loads(raw)
        return cls(
            chunks=[
                Chunk(index=c["i"], size=c["s"], file_id=c["f"],
                      message_id=c.get("m"))
                for c in d["chunks"]
            ],
            total_size=d["size"],
        )

    def prefix_sizes(self) -> list[int]:
        """End offset of each chunk: prefix_sizes[i] == offset of chunk i+1."""
        out: list[int] = []
        acc = 0
        for c in self.chunks:
            acc += c.size
            out.append(acc)
        return out

    def map_range(self, start: int, end: int) -> list[tuple[int, int, int]]:
        """Map byte range [start, end) to (chunk_index, chunk_offset, length).

        `end` is exclusive; pass manifest.total_size for "to end of file".
        """
        if not (0 <= start < end <= self.total_size):
            raise ValueError(f"range {start}-{end} outside object of {self.total_size} bytes")
        ends = self.prefix_sizes()
        out: list[tuple[int, int, int]] = []
        pos = start
        while pos < end:
            # chunk index = first i with ends[i] > pos
            i = next(i for i, e in enumerate(ends) if e > pos)
            chunk_start = ends[i - 1] if i > 0 else 0
            off = pos - chunk_start
            take = min(ends[i] - pos, end - pos)
            out.append((i, off, take))
            pos += take
        return out


async def chunk_stream(
    stream,
    chunk_size: int,
    on_chunk,
) -> tuple[int, str]:
    """Drain an async byte stream, calling `on_chunk(bytes) -> file_id` per part.

    Returns (total_size, sha256_hex). Memory usage is bounded by chunk_size.
    """
    h = hashlib.sha256()
    total = 0
    index = 0
    while True:
        buf = bytearray()
        while len(buf) < chunk_size:
            piece = await stream.read(chunk_size - len(buf))
            if not piece:
                break
            buf.extend(piece)
        if not buf:
            break
        await on_chunk(bytes(buf))
        h.update(buf)
        total += len(buf)
        index += 1
    return total, h.hexdigest()


def verify_signature(secret: bytes, payload: bytes, sig: str) -> bool:
    """HMAC-SHA256 constant-time comparison (used for signed URLs, F4)."""
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)