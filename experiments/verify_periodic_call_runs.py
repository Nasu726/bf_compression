from __future__ import annotations

"""Verify exact decoding of affine and periodic macro-call records."""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_periodic_call_runs import encode_start_optimal
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


def read_signed(data: bytes, pos: int):
    value, pos = read_uleb(data, pos)
    return (value >> 1) ^ -(value & 1), pos


def read_args(data: bytes, pos: int, arity: int):
    out = []
    for _ in range(arity):
        value, pos = read_signed(data, pos)
        out.append(value)
    return tuple(out), pos


def decode_start(data: bytes, expected: int, escape_run: int, escape_pattern: int, arities: list[int]):
    out = []
    pos = 0
    while len(out) < expected:
        symbol, pos = read_uleb(data, pos)
        if symbol < escape_run:
            args, pos = read_args(data, pos, arities[symbol])
            out.append(Occ(symbol, args))
            continue
        if symbol == escape_run:
            target, pos = read_uleb(data, pos)
            count, pos = read_uleb(data, pos)
            base, pos = read_args(data, pos, arities[target])
            delta, pos = read_args(data, pos, arities[target])
            cur = base
            for _ in range(count):
                out.append(Occ(target, cur))
                cur = tuple(x + d for x, d in zip(cur, delta))
            continue
        assert symbol == escape_pattern
        period, pos = read_uleb(data, pos)
        repeats, pos = read_uleb(data, pos)
        slots = []
        for _ in range(period):
            target, pos = read_uleb(data, pos)
            base, pos = read_args(data, pos, arities[target])
            delta, pos = read_args(data, pos, arities[target])
            slots.append((target, base, delta))
        for k in range(repeats):
            for target, base, delta in slots:
                args = tuple(x + k * d for x, d in zip(base, delta))
                out.append(Occ(target, args))
    assert len(out) == expected
    assert pos == len(data)
    return out


def verify_tokens(tokens, max_rules=128, max_period=8):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    e0 = len(terminals) + len(rules)
    data, runs, patterns, covered = encode_start_optimal(seq, e0, e0 + 1, max_period)
    recovered = decode_start(data, len(seq), e0, e0 + 1, arities)
    assert recovered == seq
    return len(seq), runs, patterns, covered


def tokens_from_text(text: str):
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    synthetic = []
    for k in range(20):
        synthetic += [("M", 10 + 7*k), ("A", 3 + 2*k)]
    n, runs, patterns, covered = verify_tokens(synthetic, max_rules=0)
    assert patterns >= 1 and covered == n

    for name in args.files:
        tokens = tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore"))
        n, runs, patterns, covered = verify_tokens(tokens)
        print(f"{name}: periodic-run round-trip ok start={n:,} affine={runs:,} patterns={patterns:,} covered={covered:,}")
    print("periodic macro call reconstruction: ok")


if __name__ == "__main__":
    main()
