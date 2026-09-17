from __future__ import annotations

"""Measure a deliberately tiny, BF-plausible LZSS codec on semantic VM payloads.

The format is intentionally much simpler than DEFLATE/LZMA:

* ULEB uncompressed length;
* groups of up to eight items, preceded by one control byte;
* control bit 1 = one literal byte;
* control bit 0 = a two-byte back-reference;
* back-reference: 12-bit distance 1..4096 and 4-bit length code 3..18.

A decoder therefore needs only: control-bit iteration, literal append, and a
bounded backwards copy.  There are no Huffman tables or adaptive models.  The
reported BF-native source cost is the *actual literal payload-constructor* cost
under ``profile_bf_native_channel``.  Decoder/VM source is still extra.
"""

from collections import defaultdict, deque, Counter
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import loader_source_for_bytes
from profile_semantic_vm import bpe_payload, encode_uleb, semantic_tokens
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf

WINDOW = 4096
MIN_MATCH = 3
MAX_MATCH = 18
MAX_CANDIDATES = 96


def tiny_lzss_encode(data: bytes) -> bytes:
    out = bytearray(encode_uleb(len(data)))
    positions: dict[bytes, deque[int]] = defaultdict(deque)
    i = 0
    n = len(data)

    def add_pos(pos: int) -> None:
        if pos + MIN_MATCH > n:
            return
        key = data[pos:pos + MIN_MATCH]
        q = positions[key]
        q.append(pos)
        while q and pos - q[0] > WINDOW:
            q.popleft()
        while len(q) > MAX_CANDIDATES:
            q.popleft()

    while i < n:
        control_pos = len(out)
        out.append(0)
        control = 0
        items = bytearray()
        for bit in range(8):
            if i >= n:
                break
            best_len = 0
            best_dist = 0
            if i + MIN_MATCH <= n:
                key = data[i:i + MIN_MATCH]
                q = positions.get(key)
                if q:
                    for pos in reversed(q):
                        dist = i - pos
                        if dist <= 0 or dist > WINDOW:
                            continue
                        limit = min(MAX_MATCH, n - i)
                        length = MIN_MATCH
                        while length < limit and data[pos + length] == data[i + length]:
                            length += 1
                        if length > best_len:
                            best_len = length
                            best_dist = dist
                            if length == limit:
                                break
            if best_len >= MIN_MATCH:
                code = ((best_dist - 1) << 4) | (best_len - MIN_MATCH)
                items.append(code & 255)
                items.append((code >> 8) & 255)
                start = i
                i += best_len
                for p in range(start, i):
                    add_pos(p)
            else:
                control |= 1 << bit
                items.append(data[i])
                add_pos(i)
                i += 1
        out[control_pos] = control
        out += items
    return bytes(out)


def decode_uleb(blob: bytes, pos: int = 0) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = blob[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7


def tiny_lzss_decode(blob: bytes) -> bytes:
    target, pos = decode_uleb(blob)
    out = bytearray()
    while len(out) < target:
        control = blob[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= target:
                break
            if control & (1 << bit):
                out.append(blob[pos])
                pos += 1
            else:
                code = blob[pos] | (blob[pos + 1] << 8)
                pos += 2
                dist = (code >> 4) + 1
                length = (code & 0xF) + MIN_MATCH
                if dist > len(out):
                    raise ValueError("invalid back-reference")
                for _ in range(length):
                    out.append(out[-dist])
                    if len(out) >= target:
                        break
    return bytes(out)


def loader_chars(blob: bytes) -> int:
    return len(loader_source_for_bytes(blob)[0])


def profile_text(text: str) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    rows = []
    for rules in (0, 16, 32, 64, 128, 256, 512, 1024):
        payload, meta = bpe_payload(tokens, rules)
        encoded = tiny_lzss_encode(payload)
        assert tiny_lzss_decode(encoded) == payload
        rows.append({
            "max_rules": rules,
            "payload_bytes": len(payload),
            "lzss_bytes": len(encoded),
            "lzss_ratio": len(encoded) / len(payload) if payload else 0.0,
            "bf_native_loader_chars": loader_chars(encoded),
            **meta,
        })
    best = min(rows, key=lambda r: r["bf_native_loader_chars"])
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "sweep": rows,
        "best": best,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        p = Path(name)
        rows.append({"name": str(p), **profile_text(p.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            b = row["best"]
            print(
                f"{row['name']}: bf={row['bf_bytes']:,} payload={b['payload_bytes']:,} "
                f"lzss={b['lzss_bytes']:,} loader={b['bf_native_loader_chars']:,} @R{b['max_rules']}"
            )


if __name__ == "__main__":
    main()
