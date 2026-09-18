from __future__ import annotations

"""Profile affine periodic runs in relational semantic-macro call streams.

This generalizes single-symbol affine RUN records to a short repeated pattern.
For period p, block k must have the same symbol/arity pattern as block 0 and
its argument vector at each pattern slot must be base + k*delta.  Periods 2..8
and at least three repetitions are considered.  A dynamic program chooses the
cheapest exact mixture of literals, single-symbol RUNs, and PATTERN_RUN records.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_affine_call_runs import affine_endpoints, literal_bytes, run_bytes
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_parametric_vm import skeleton_definition
from profile_signed_relational_macro_grammar import ADD, CONST, NEGADD, Occ, RuleDef, build_grammar, enc_signed, pack_kinds
from profile_semantic_vm import encode_uleb, semantic_tokens
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def pattern_bytes(escape: int, period: int, repeats: int, first: list[Occ], deltas: list[tuple[int, ...]]) -> bytes:
    out = bytearray()
    out += encode_uleb(escape)
    out += encode_uleb(period)
    out += encode_uleb(repeats)
    for occ, delta in zip(first, deltas):
        out += encode_uleb(occ.symbol)
        for value in occ.args:
            out += enc_signed(value)
        for value in delta:
            out += enc_signed(value)
    return bytes(out)


def pattern_endpoints(seq: list[Occ], start: int, period: int):
    if start + 3 * period > len(seq):
        return []
    first = seq[start:start + period]
    second = seq[start + period:start + 2 * period]
    deltas = []
    for a, b in zip(first, second):
        if a.symbol != b.symbol or len(a.args) != len(b.args):
            return []
        deltas.append(tuple(y - x for x, y in zip(a.args, b.args)))

    def block_matches(block_index: int) -> bool:
        base = start + block_index * period
        prev = base - period
        for t in range(period):
            a = seq[prev + t]
            b = seq[base + t]
            if a.symbol != b.symbol or len(a.args) != len(b.args):
                return False
            if tuple(y - x for x, y in zip(a.args, b.args)) != deltas[t]:
                return False
        return True

    if not block_matches(2):
        return []
    repeats = 3
    out = [(start + repeats * period, repeats, first, deltas)]
    while start + (repeats + 1) * period <= len(seq) and block_matches(repeats):
        repeats += 1
        out.append((start + repeats * period, repeats, first, deltas))
    return out


def encode_start_optimal(seq: list[Occ], escape_run: int, escape_pattern: int, max_period: int = 8):
    n = len(seq)
    best = [10**30] * (n + 1)
    choice = [None] * n
    best[n] = 0
    for i in range(n - 1, -1, -1):
        lit = literal_bytes(seq[i])
        best[i] = len(lit) + best[i + 1]
        choice[i] = ("lit", i + 1, lit, 1)

        for end, delta in affine_endpoints(seq, i):
            rb = run_bytes(escape_run, seq[i].symbol, end - i, seq[i].args, delta)
            cost = len(rb) + best[end]
            if cost < best[i]:
                best[i] = cost
                choice[i] = ("run", end, rb, end - i)

        for period in range(2, max_period + 1):
            for end, repeats, first, deltas in pattern_endpoints(seq, i, period):
                pb = pattern_bytes(escape_pattern, period, repeats, first, deltas)
                cost = len(pb) + best[end]
                if cost < best[i]:
                    best[i] = cost
                    choice[i] = ("pattern", end, pb, end - i)

    out = bytearray()
    run_records = 0
    pattern_records = 0
    covered = 0
    i = 0
    while i < n:
        kind, end, payload, span = choice[i]
        out += payload
        if kind == "run":
            run_records += 1
            covered += span
        elif kind == "pattern":
            pattern_records += 1
            covered += span
        i = end
    return bytes(out), run_records, pattern_records, covered


def serialize_with_patterns(terminals, rules: list[RuleDef], seq: list[Occ], max_period: int = 8):
    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for sk in terminals:
        d = skeleton_definition(sk)
        out += encode_uleb(len(d))
        out += d
    for rule in rules:
        out += encode_uleb(rule.left)
        out += encode_uleb(rule.right)
        out += encode_uleb(rule.input_arity)
        kinds = pack_kinds(rule.specs)
        out += encode_uleb(len(kinds))
        out += kinds
        for j, spec in enumerate(rule.specs):
            if spec.kind == CONST:
                out += enc_signed(spec.value)
            elif spec.kind == ADD:
                assert 0 <= spec.ref < j
                out += encode_uleb(j - spec.ref - 1)
                out += enc_signed(spec.value)
    total_symbols = len(terminals) + len(rules)
    start, runs, patterns, covered = encode_start_optimal(seq, total_symbols, total_symbols + 1, max_period)
    out += start
    return bytes(out), runs, patterns, covered


def profile_tokens(tokens, max_rules: int, max_period: int = 8):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    payload, runs, patterns, covered = serialize_with_patterns(terminals, rules, seq, max_period)
    ext = tiny_lzss_ext_encode(payload)
    assert tiny_lzss_ext_decode(ext) == payload
    channels = {
        "direct_byte": direct_byte_loader_chars(payload),
        "prefix16_bit": len(loader_source_for_bytes(payload)[0]),
        "ext_lzss_prefix16": len(loader_source_for_bytes(ext)[0]),
        "ext_lzss_direct_byte": direct_byte_loader_chars(ext),
    }
    best_channel = min(channels, key=channels.get)
    return {
        "rules": len(rules),
        "start_symbols": len(seq),
        "affine_run_records": runs,
        "pattern_run_records": patterns,
        "run_covered_calls": covered,
        "payload_bytes": len(payload),
        "ext_lzss_bytes": len(ext),
        "best_loader_channel": best_channel,
        "best_loader_chars": channels[best_channel],
    }


def profile_text(text: str, max_period: int = 8):
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    sweep = []
    for limit in (0, 16, 32, 64, 128):
        row = profile_tokens(tokens, limit, max_period)
        row["max_rules"] = limit
        sweep.append(row)
    best = min(sweep, key=lambda r: int(r["best_loader_chars"]))
    return {"bf_bytes": len(raw), "semantic_tokens": len(tokens), "sweep": sweep, "best": best}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-period", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        p = Path(name)
        rows.append({"name": str(p), **profile_text(p.read_text(encoding="ascii", errors="ignore"), args.max_period)})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            b = row["best"]
            print(f"{row['name']}: loader={b['best_loader_chars']:,} runs={b['affine_run_records']:,} patterns={b['pattern_run_records']:,} covered={b['run_covered_calls']:,} R={b['max_rules']}")


if __name__ == "__main__":
    main()
