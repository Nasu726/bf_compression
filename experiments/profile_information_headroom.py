from __future__ import annotations

"""Profile whole-program information/bytecode compression headroom.

This intentionally ignores executability at first.  The goal is to answer a
more global question than peephole or tape-layout optimization:

    how much information is actually present in the already-optimized BF text?

If ordinary dictionary compressors reduce compiler BF to a tiny payload, then a
standard-BF self-expanding bytecode/VM is a plausible source-size direction even
when direct source-to-source rewrites stall.

The binary sizes reported here are *not* directly achievable BF source sizes.
They are entropy/grammar proxies and must not be presented as an executable
compression result.
"""

import argparse
import bz2
import json
import lzma
from pathlib import Path
import zlib

BF = frozenset("><+-.,[]")


def strip_bf(text: str) -> str:
    return "".join(ch for ch in text if ch in BF)


def uleb_size(value: int) -> int:
    assert value >= 0
    out = 1
    while value >= 128:
        value >>= 7
        out += 1
    return out


def semantic_rle_size(code: str) -> tuple[int, int]:
    """Return (token_count, binary bytes) for a tiny semantic RLE bytecode.

    Pointer runs become one signed-displacement token and arithmetic runs become
    one modulo-256 delta token.  Brackets and I/O remain one-byte opcodes.  A
    run token is charged one opcode byte plus unsigned LEB128 magnitude bytes.
    This is deliberately a simple bytecode estimate, not a finalized VM format.
    """
    i = 0
    tokens = 0
    size = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch in "><":
            delta = 0
            while i < n and code[i] in "><":
                delta += 1 if code[i] == ">" else -1
                i += 1
            if delta:
                tokens += 1
                size += 1 + uleb_size(abs(delta))
            continue
        if ch in "+-":
            delta = 0
            while i < n and code[i] in "+-":
                delta += 1 if code[i] == "+" else -1
                i += 1
            delta &= 255
            if delta:
                mag = min(delta, 256 - delta)
                tokens += 1
                size += 1 + uleb_size(mag)
            continue
        tokens += 1
        size += 1
        i += 1
    return tokens, size


def build_rle_stream(code: str) -> bytes:
    """Materialize the same simple bytecode for compressor comparison."""
    out = bytearray()
    i = 0
    n = len(code)

    def emit_uleb(value: int) -> None:
        while True:
            b = value & 0x7F
            value >>= 7
            if value:
                out.append(b | 0x80)
            else:
                out.append(b)
                return

    while i < n:
        ch = code[i]
        if ch in "><":
            delta = 0
            while i < n and code[i] in "><":
                delta += 1 if code[i] == ">" else -1
                i += 1
            if delta:
                out.append(0 if delta > 0 else 1)
                emit_uleb(abs(delta))
            continue
        if ch in "+-":
            delta = 0
            while i < n and code[i] in "+-":
                delta += 1 if code[i] == "+" else -1
                i += 1
            delta &= 255
            if delta:
                if delta <= 128:
                    out.append(2)
                    emit_uleb(delta)
                else:
                    out.append(3)
                    emit_uleb(256 - delta)
            continue
        out.append({"[": 4, "]": 5, ".": 6, ",": 7}[ch])
        i += 1
    return bytes(out)


def compressed_sizes(data: bytes) -> dict[str, int]:
    return {
        "zlib9": len(zlib.compress(data, 9)),
        "bz2_9": len(bz2.compress(data, 9)),
        "lzma9": len(lzma.compress(data, preset=9)),
    }


def profile_text(text: str) -> dict[str, object]:
    code = strip_bf(text)
    raw = code.encode("ascii")
    token_count, rle_bytes = semantic_rle_size(code)
    rle = build_rle_stream(code)
    assert len(rle) == rle_bytes
    packed_3bit_bytes = (3 * len(code) + 7) // 8
    return {
        "bf_bytes": len(code),
        "ascii_compressed": compressed_sizes(raw),
        "three_bit_packed_bytes": packed_3bit_bytes,
        "semantic_rle": {
            "token_count": token_count,
            "binary_bytes": rle_bytes,
            "compressed": compressed_sizes(rle),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        path = Path(name)
        rows.append({"name": str(path), **profile_text(path.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            comp = row["ascii_compressed"]
            rle = row["semantic_rle"]
            print(
                f"{row['name']}: bf={row['bf_bytes']:,} "
                f"lzma={comp['lzma9']:,} "
                f"rle={rle['binary_bytes']:,} "
                f"rle_lzma={rle['compressed']['lzma9']:,}"
            )


if __name__ == "__main__":
    main()
