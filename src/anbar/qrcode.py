"""Minimal QR code generator (pure Python, no deps).

Generates a byte-mode, ECC-L, version 1-10 QR code as SVG path data.
Sufficient for URLs up to ~270 chars. Based on the QR spec (ISO/IEC
18004) with the standard Reed-Solomon ECC over GF(256).
"""
from __future__ import annotations

# ── GF(256) tables ──────────────────────────────────────────────────────────
_EXP = [0] * 512
_LOG = [0] * 256


def _init_gf() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_gf()


def _gmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_gen_poly(nsym: int) -> list[int]:
    g = [1]
    for i in range(nsym):
        g = _poly_mul(g, [1, _EXP[i]])
    return g


def _poly_mul(p1: list[int], p2: list[int]) -> list[int]:
    out = [0] * (len(p1) + len(p2) - 1)
    for i, c1 in enumerate(p1):
        for j, c2 in enumerate(p2):
            out[i + j] ^= _gmul(c1, c2)
    return out


def _rs_encode(data: bytes, nsym: int) -> bytearray:
    gen = _rs_gen_poly(nsym)
    res = bytearray(data) + bytearray(nsym)
    for i in range(len(data)):
        coef = res[i]
        if coef:
            for j in range(len(gen)):
                res[i + j] ^= _gmul(gen[j], coef)
    return bytearray(res[len(data):])


# ── QR matrix construction ──────────────────────────────────────────────────
def _version_for(nbits: int) -> tuple[int, int]:
    """Return (version, data capacity bits) for ECC-L byte mode."""
    caps = {1: 19 * 8, 2: 34 * 8, 3: 55 * 8, 4: 80 * 8,
            5: 108 * 8, 6: 136 * 8, 7: 156 * 8, 8: 194 * 8,
            9: 232 * 8, 10: 274 * 8}
    for v, cap in caps.items():
        if nbits <= cap:
            return v, cap
    raise ValueError("payload too long for versions 1-10 (use shorter URL)")


_EC_PER_BLOCK = {1: 7, 2: 10, 3: 15, 4: 20, 5: 26, 6: 18, 7: 20, 8: 24,
                 9: 30, 10: 18}


def _build_matrix(payload: bytes) -> list[list[bool]]:
    # mode + length + data
    ver, _cap = _version_for(4 + (16 if len(payload) > 255 // 1 else 8) + 8 * len(payload))
    bits: list[int] = []
    bits += [1, 0, 0]  # byte mode (0100) → first 4 bits
    bits += [(4 >> 3) & 1, (4 >> 2) & 1, (4 >> 1) & 1, 4 & 1]
    cnt_bits = 8 if ver < 10 else 16
    for i in range(cnt_bits - 1, -1, -1):
        bits.append((len(payload) >> i) & 1)
    for byte in payload:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)

    ec = _EC_PER_BLOCK[ver]
    total_data = {1: 19, 2: 34, 3: 55, 4: 80, 5: 108,
                  6: 136, 7: 156, 8: 194, 9: 232, 10: 274}[ver]
    # terminator + pad to byte boundary
    bits += [0] * min(4, max(0, total_data * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    data_bytes = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        data_bytes.append(b)
    pad = [0xEC, 0x11]
    pi = 0
    while len(data_bytes) < total_data:
        data_bytes.append(pad[pi % 2])
        pi += 1

    # single block layout for v1-10 L (all use 1 block per group here)
    ecc = _rs_encode(bytes(data_bytes), ec)
    final = bytes(data_bytes) + bytes(ecc)

    size = 21 + (ver - 1) * 4
    m: list[list[bool | None]] = [[None] * size for _ in range(size)]  # None=unset

    def set_finder(row: int, col: int) -> None:
        """7x7 finder rings + 1-module white separator around them."""
        for r in range(7):
            for c in range(7):
                ring = r in (0, 6) or c in (0, 6)
                core = 2 <= r <= 4 and 2 <= c <= 4
                m[row + r][col + c] = ring or core
        for r in range(-1, 8):
            for c in range(-1, 8):
                if not (0 <= r <= 6 and 0 <= c <= 6):
                    rr, cc = row + r, col + c
                    if 0 <= rr < size and 0 <= cc < size:
                        m[rr][cc] = False

    set_finder(0, 0)
    set_finder(0, size - 7)
    set_finder(size - 7, 0)

    # timing patterns
    for i in range(8, size - 8):
        m[6][i] = i % 2 == 0
        m[i][6] = i % 2 == 0

    # alignment patterns for v>=2 (simplified: only the standard centers)
    if ver >= 2:
        align_pos = {2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
                     6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
                     9: [6, 26, 46], 10: [6, 28, 50]}[ver]
        for r in align_pos:
            for c in align_pos:
                if m[r][c] is not None:
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        ring = dr in (-2, 2) or dc in (-2, 2)
                        core = dr == 0 and dc == 0
                        m[r + dr][c + dc] = ring or core

    # dark module
    m[size - 8][8] = True

    # reserve format info areas (will fill later); mark as set with False
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(size - 8, size):
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False

    # place data with mask 0 (checkerboard) using the standard zigzag
    data_bits = "".join(f"{b:08b}" for b in final)
    bit_i = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # skip timing column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if m[row][c] is not None:
                    continue
                bit = False
                if bit_i < len(data_bits):
                    bit = data_bits[bit_i] == "1"
                bit_i += 1
                # mask 0: (row+col)%2==0 → invert
                if (row + c) % 2 == 0:
                    bit = not bit
                m[row][c] = bit
        upward = not upward
        col -= 2

    # format info: EC level L (01) + mask 0 (00) → 111011111000100 precomputed
    fmt = "111011111000100"
    # top-left: around (8,0..8) and (0..8,8)
    idx = 0
    for c in range(0, 6):
        m[8][c] = fmt[idx] == "1"
        idx += 1
    m[8][7] = fmt[6] == "1"
    m[8][8] = fmt[7] == "1"
    m[8][8] = fmt[7] == "1"
    m[7][8] = fmt[8] == "1"
    for r in range(5, -1, -1):
        m[r][8] = fmt[9 + (5 - r)] == "1"
    # bottom-right copy
    idx = 0
    for r in range(size - 1, size - 8, -1):
        m[r][8] = fmt[idx] == "1"
        idx += 1
    for c in range(size - 8, size):
        m[8][c] = fmt[idx] == "1"
        idx += 1
    return m


def qr_svg(text: str, box_px: int = 160) -> str:
    """Render text as a standalone SVG string (dark modules = currentColor)."""
    m = _build_matrix(text.encode("utf-8"))
    n = len(m)
    quiet = 2
    dim = (n + quiet * 2) * 4
    rects = []
    for r in range(n):
        for c in range(n):
            if m[r][c]:
                rects.append(
                    f'<rect x="{(c + quiet) * 4}" y="{(r + quiet) * 4}" width="4" height="4"/>')
    body = "".join(rects)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
            f'width="{box_px}" height="{box_px}" shape-rendering="crispEdges">'
            f'<rect width="{dim}" height="{dim}" fill="#fff"/>{body}</svg>')
