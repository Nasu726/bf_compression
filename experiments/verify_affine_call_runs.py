from __future__ import annotations

"""Verify exact reconstruction of affine RUN records."""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_affine_call_runs import encode_start_optimal
from profile_relational_macro_grammar import Occ, build_grammar
from profile_semantic_vm import semantic_tokens
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def read_uleb(data: bytes, pos: int):
    value = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        value |= (b & 127) << shift
        if not (b & 128):
            return value, pos
        shift += 7


def unzigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def read_signed(data: bytes, pos: int):
    value, pos = read_uleb(data, pos)
    return unzigzag(value), pos


def decode_start(data: bytes, expected: int, escape: int, arities: list[int]):
    out = []
    pos = 0
    while len(out) < expected:
        symbol, pos = read_uleb(data, pos)
        if symbol != escape:
            arity = arities[symbol]
            args = []
            for _ in range(arity):
                value, pos = read_signed(data, pos)
                args.append(value)
            out.append(Occ(symbol, tuple(args)))
            continue
        symbol, pos = read_uleb(data, pos)
        count, pos = read_uleb(data, pos)
        arity = arities[symbol]
        base = []
        delta = []
        for _ in range(arity):
            value, pos = read_signed(data, pos)
            base.append(value)
        for _ in range(arity):
            value, pos = read_signed(data, pos)
            delta.append(value)
        cur = tuple(base)
        for _ in range(count):
            out.append(Occ(symbol, cur))
            cur = tuple(x + d for x, d in zip(cur, delta))
    assert len(out) == expected
    assert pos == len(data)
    return out


def verify_tokens(tokens, max_rules=128):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    escape = len(terminals) + len(rules)
    data, runs, covered = encode_start_optimal(seq, escape)
    recovered = decode_start(data, len(seq), escape, arities)
    assert recovered == seq
    return len(seq), runs, covered


def tokens_from_text(text: str):
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    synthetic = [("M", 10 + 7 * i) for i in range(40)]
    n, runs, covered = verify_tokens(synthetic, max_rules=0)
    assert runs == 1 and covered == n
    for name in args.files:
        tokens = tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore"))
        n, runs, covered = verify_tokens(tokens)
        print(f"{name}: affine-run round-trip ok start={n:,} runs={runs:,} covered={covered:,}")
    print("affine call run reconstruction: ok")


if __name__ == "__main__":
    main()
