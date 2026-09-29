from __future__ import annotations

"""Measure deliberately tiny, BF-plausible LZSS codecs on semantic VM payloads.

Both formats use groups of eight items with one control byte (1=literal,
0=back-reference) and a 4096-byte window.

``fixed18``:
  every match is two bytes: 12-bit distance + 4-bit length 3..18.

``ext273``:
  length nibble 0..14 means 3..17; nibble 15 means an extra byte follows and
  the match length is 18..273.  This adds only one conditional read to a future
  BF decoder while allowing long repeated grammar fragments to collapse.

There are no Huffman tables/adaptive models.  The reported BF-native source cost
is the actual literal payload-constructor cost.  Decoder/semantic-VM source is
still extra.
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
FIXED_MAX = 18
EXT_MAX = 273
MAX_CANDIDATES = 96


def _encode(data: bytes, *, extended: bool) -> bytes:
    out = bytearray(encode_uleb(len(data)))
    positions: dict[bytes, deque[int]] = defaultdict(deque)
    i = 0
    n = len(data)
    max_match = EXT_MAX if extended else FIXED_MAX

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
                        limit = min(max_match, n - i)
                        length = MIN_MATCH
                        while length < limit and data[pos + length] == data[i + length]:
                            length += 1
                        if length > best_len:
                            best_len = length
                            best_dist = dist
                            if length == limit:
                                break
            if best_len >= MIN_MATCH:
                if extended and best_len >= 18:
                    nibble = 15
                else:
                    nibble = best_len - MIN_MATCH
                code = ((best_dist - 1) << 4) | nibble
                items.append(code & 255)
                items.append((code >> 8) & 255)
                if extended and nibble == 15:
                    items.append(best_len - 18)
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


def tiny_lzss_encode(data: bytes) -> bytes:
    return _encode(data, extended=False)


def tiny_lzss_ext_encode(data: bytes) -> bytes:
    return _encode(data, extended=True)


def decode_uleb(blob: bytes, pos: int = 0) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = blob[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7


def _decode(blob: bytes, *, extended: bool) -> bytes:
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
                nibble = code & 0xF
                if extended and nibble == 15:
                    length = 18 + blob[pos]
                    pos += 1
                else:
                    length = nibble + MIN_MATCH
                if dist > len(out):
                    raise ValueError("invalid back-reference")
                for _ in range(length):
                    out.append(out[-dist])
                    if len(out) >= target:
                        break
    return bytes(out)


def tiny_lzss_decode(blob: bytes) -> bytes:
    return _decode(blob, extended=False)


def tiny_lzss_ext_decode(blob: bytes) -> bytes:
    return _decode(blob, extended=True)


def loader_chars(blob: bytes) -> int:
    return len(loader_source_for_bytes(blob)[0])


def profile_text(text: str) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    rows = []
    for rules in (0, 16, 32, 64, 128, 256, 512, 1024):
        payload, meta = bpe_payload(tokens, rules)
        for fmt, encoder, decoder in (
            ("fixed18", tiny_lzss_encode, tiny_lzss_decode),
            ("ext273", tiny_lzss_ext_encode, tiny_lzss_ext_decode),
        ):
            encoded = encoder(payload)
            assert decoder(encoded) == payload
            rows.append({
                "format": fmt,
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
                f"lzss={b['lzss_bytes']:,} loader={b['bf_native_loader_chars']:,} "
                f"{b['format']} @R{b['max_rules']}"
            )


if __name__ == "__main__":
    main()
