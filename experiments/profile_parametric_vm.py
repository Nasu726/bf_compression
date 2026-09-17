from __future__ import annotations

"""Measure compiler-template sharing after separating VM opcode skeletons/parameters.

Concrete semantic VM tokens such as ``M(+97)`` and ``M(+132)`` are different
terminals to an ordinary grammar, even when they occur at the same slot of the
same compiler-generated template.  A parameterized macro should share the
opcode skeleton and carry the differing numeric operands at each call site.

This profiler gives a conservative *representation* test for that idea:

1. derive exact semantic VM tokens using ``profile_semantic_vm``;
2. split each token into a small structural skeleton and an explicit parameter
   tuple -- no numeric information is discarded;
3. BPE-compress only the skeleton stream;
4. serialize every parameter occurrence separately, with exact signed/delta
   integer codes;
5. report exact BF-native literal-loader cost for the combined representation.

Because parameters are still stored for every original token occurrence, this
is *not* a free-parameter oracle.  A future macro system can only beat it by
finding relations among parameters (e.g. shared base + fixed relative offsets).
The compressed-size columns are information proxies, not achieved BF source.
"""

import argparse
import bz2
from collections import Counter, defaultdict
import json
import lzma
from pathlib import Path
import sys
import zlib
from typing import Hashable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import loader_source_for_bytes
from profile_semantic_vm import (
    encode_uleb,
    semantic_tokens,
    zigzag,
)
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf

Token = tuple[Hashable, ...]
Skeleton = tuple[Hashable, ...]


def split_token(token: Token) -> tuple[Skeleton, tuple[int, ...]]:
    kind = str(token[0])
    if kind in ("M", "SCAN"):
        return (kind,), (int(token[1]),)
    if kind == "A":
        return (kind,), (int(token[1]),)
    if kind in ("AFFINE", "LINEAR_LOOP"):
        pairs = token[1]
        assert isinstance(pairs, tuple)
        params: list[int] = []
        # Arity is structural: a VM dispatch can select a tight arity-specific
        # inner loop, while offsets/coefficients remain explicit call data.
        for off, coeff in pairs:
            params.extend((int(off), int(coeff)))
        return (kind, len(pairs)), tuple(params)
    return (kind,), ()


def encode_signed(value: int) -> bytes:
    return encode_uleb(zigzag(value))


def parameter_stream(tokens: list[Token], *, context_delta: bool) -> bytes:
    """Serialize all parameters without hiding any values.

    context_delta keeps one previous value per (kind, parameter-slot) and stores
    the signed difference.  This is a tiny-state model suitable for a BF VM and
    tests whether compiler templates mostly shift together through the tape.
    """
    out = bytearray()
    previous: dict[tuple[str, int, int], int] = defaultdict(int)
    for token in tokens:
        skeleton, params = split_token(token)
        kind = str(skeleton[0])
        arity = int(skeleton[1]) if len(skeleton) > 1 else 0
        for slot, value in enumerate(params):
            if context_delta:
                key = (kind, arity, slot)
                delta = value - previous[key]
                previous[key] = value
                out += encode_signed(delta)
            else:
                out += encode_signed(value)
    return bytes(out)


def skeleton_definition(sk: Skeleton) -> bytes:
    kinds = {
        "M": 0,
        "A": 1,
        "OUT": 2,
        "IN": 3,
        "CLEAR": 4,
        "SCAN": 5,
        "AFFINE": 6,
        "LINEAR_LOOP": 7,
        "LOOP_BEGIN": 8,
        "LOOP_END": 9,
    }
    out = bytearray([kinds[str(sk[0])]])
    if len(sk) > 1:
        out += encode_uleb(int(sk[1]))
    return bytes(out)


def bpe_skeleton_payload(skeletons: list[Skeleton], max_rules: int) -> bytes:
    terminal_ids: dict[Skeleton, int] = {}
    terminals: list[Skeleton] = []
    seq: list[int] = []
    for sk in skeletons:
        sid = terminal_ids.get(sk)
        if sid is None:
            sid = len(terminals)
            terminal_ids[sk] = sid
            terminals.append(sk)
        seq.append(sid)

    rules: list[tuple[int, int]] = []
    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter(zip(seq, seq[1:]))
        pair, freq = counts.most_common(1)[0]
        if freq <= 2:
            break
        new_id = len(terminals) + len(rules)
        a, b = pair
        new_seq: list[int] = []
        i = 0
        replaced = 0
        while i < len(seq):
            if i + 1 < len(seq) and seq[i] == a and seq[i + 1] == b:
                new_seq.append(new_id)
                replaced += 1
                i += 2
            else:
                new_seq.append(seq[i])
                i += 1
        if replaced <= 2:
            break
        rules.append((a, b))
        seq = new_seq

    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for sk in terminals:
        d = skeleton_definition(sk)
        out += encode_uleb(len(d))
        out += d
    for a, b in rules:
        out += encode_uleb(a)
        out += encode_uleb(b)
    for sym in seq:
        out += encode_uleb(sym)
    return bytes(out)


def codecs(blob: bytes) -> dict[str, int]:
    return {
        "zlib9": len(zlib.compress(blob, 9)),
        "bz2_9": len(bz2.compress(blob, compresslevel=9)),
        "lzma9": len(lzma.compress(blob, preset=9)),
    }


def loader(blob: bytes) -> int:
    return len(loader_source_for_bytes(blob)[0])


def profile_text(text: str) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    skeletons = [split_token(t)[0] for t in tokens]
    param_count = sum(len(split_token(t)[1]) for t in tokens)
    absolute = parameter_stream(tokens, context_delta=False)
    delta = parameter_stream(tokens, context_delta=True)

    rows = []
    for rules in (0, 16, 32, 64, 128, 256, 512, 1024):
        skeleton = bpe_skeleton_payload(skeletons, rules)
        for mode, params in (("absolute", absolute), ("context_delta", delta)):
            # Length prefix makes the concatenation unambiguous to a decoder.
            combined = encode_uleb(len(skeleton)) + skeleton + params
            rows.append({
                "max_rules": rules,
                "parameter_mode": mode,
                "skeleton_bytes": len(skeleton),
                "parameter_bytes": len(params),
                "combined_bytes": len(combined),
                "bf_native_loader_chars": loader(combined),
                "compressed_bytes": codecs(combined),
            })

    best = min(rows, key=lambda r: r["bf_native_loader_chars"])
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "parameter_occurrences": param_count,
        "distinct_skeletons": len(set(skeletons)),
        "absolute_parameter_bytes": len(absolute),
        "context_delta_parameter_bytes": len(delta),
        "sweep": rows,
        "best_direct": best,
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
        for r in rows:
            b = r["best_direct"]
            print(
                f"{r['name']}: bf={r['bf_bytes']:,} tokens={r['semantic_tokens']:,} "
                f"params={r['parameter_occurrences']:,} direct={b['combined_bytes']:,}B/"
                f"{b['bf_native_loader_chars']:,}BF @R{b['max_rules']} {b['parameter_mode']}"
            )


if __name__ == "__main__":
    main()
