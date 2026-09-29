from __future__ import annotations

"""Decoder-aware grammar serialization for the fixed semantic VM ISA.

The older research format is intentionally self-describing: every program stores
its terminal definitions, every rule stores input arity, and every rule stores
the byte length of its packed slot-kind vector.  A real fixed VM already knows
all of that information.

This format removes those fields and assigns canonical terminal codes:

  M, A, OUT, IN, CLEAR, SCAN, LOOP_BEGIN, LOOP_END
  AFFINE(n), LINEAR_LOOP(n)

Rule child references use one ULEB with parity tagging:

  even: canonical terminal code
  odd:  backward rule distance

Start-stream values 0 and 1 are reserved for RUN and PATTERN_RUN.  Literal
symbol references are shifted by two; rule references are encoded backward from
the final rule, while terminals use their canonical code.  Therefore terminal
dictionaries never appear in the payload.

Rule input arity is derived from the two children.  Packed-kind byte length is
then derived from that arity.  Rule output arity is the number of PARAM slots.
All omitted information is decoder-derivable, not an oracle.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_parametric_vm import split_token
from profile_semantic_vm import encode_uleb, semantic_tokens
from profile_signed_relational_macro_grammar import (
    ADD, CONST, NEGADD, PARAM, Occ, RuleDef, build_grammar, enc_signed, pack_kinds,
)
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf
from self_extracting_balanced_octal_channel import total_channel_chars as octal_total_chars


_SIMPLE_CODES = {
    "M": 0,
    "A": 1,
    "OUT": 2,
    "IN": 3,
    "CLEAR": 4,
    "SCAN": 5,
    "LOOP_BEGIN": 6,
    "LOOP_END": 7,
}


def terminal_code(sk: tuple) -> int:
    kind = str(sk[0])
    if kind in _SIMPLE_CODES:
        assert len(sk) == 1
        return _SIMPLE_CODES[kind]
    assert len(sk) == 2
    arity = int(sk[1])
    assert arity >= 1
    if kind == "AFFINE":
        return 8 + 2 * (arity - 1)
    if kind == "LINEAR_LOOP":
        return 9 + 2 * (arity - 1)
    raise AssertionError(sk)


def terminal_skeleton(code: int) -> tuple:
    reverse = {v: k for k, v in _SIMPLE_CODES.items()}
    if code in reverse:
        return (reverse[code],)
    assert code >= 8
    if code % 2 == 0:
        return ("AFFINE", 1 + (code - 8) // 2)
    return ("LINEAR_LOOP", 1 + (code - 9) // 2)


def skeleton_arity(sk: tuple) -> int:
    kind = str(sk[0])
    if kind in ("M", "A", "SCAN"):
        return 1
    if kind in ("AFFINE", "LINEAR_LOOP"):
        return 2 * int(sk[1])
    return 0


def terminal_arity(code: int) -> int:
    return skeleton_arity(terminal_skeleton(code))


def child_ref_bytes(symbol: int, terminal_count: int, current_rule: int, terminals: list[tuple]) -> bytes:
    if symbol < terminal_count:
        return encode_uleb(2 * terminal_code(terminals[symbol]))
    child_rule = symbol - terminal_count
    assert 0 <= child_rule < current_rule
    backward = current_rule - 1 - child_rule
    return encode_uleb(2 * backward + 1)


def start_ref_value(symbol: int, terminal_count: int, rule_count: int, terminals: list[tuple]) -> int:
    if symbol < terminal_count:
        # 0/1 are RUN/PATTERN escapes; terminal refs are even >=2.
        return 2 + 2 * terminal_code(terminals[symbol])
    rid = symbol - terminal_count
    assert 0 <= rid < rule_count
    backward = rule_count - 1 - rid
    return 3 + 2 * backward


def literal_bytes(occ: Occ, terminal_count: int, rule_count: int, terminals: list[tuple]) -> bytes:
    out = bytearray(encode_uleb(start_ref_value(occ.symbol, terminal_count, rule_count, terminals)))
    for value in occ.args:
        out += enc_signed(value)
    return bytes(out)


def run_bytes(occ: Occ, count: int, delta: tuple[int, ...], terminal_count: int, rule_count: int, terminals: list[tuple]) -> bytes:
    out = bytearray([0])
    out += encode_uleb(start_ref_value(occ.symbol, terminal_count, rule_count, terminals))
    out += encode_uleb(count)
    for value in occ.args:
        out += enc_signed(value)
    for value in delta:
        out += enc_signed(value)
    return bytes(out)


def pattern_bytes(first: list[Occ], deltas: list[tuple[int, ...]], repeats: int, terminal_count: int, rule_count: int, terminals: list[tuple]) -> bytes:
    out = bytearray([1])
    out += encode_uleb(len(first))
    out += encode_uleb(repeats)
    for occ, delta in zip(first, deltas):
        out += encode_uleb(start_ref_value(occ.symbol, terminal_count, rule_count, terminals))
        for value in occ.args:
            out += enc_signed(value)
        for value in delta:
            out += enc_signed(value)
    return bytes(out)


def affine_endpoints(seq: list[Occ], start: int):
    if start + 2 >= len(seq):
        return []
    a = seq[start]
    b = seq[start + 1]
    if a.symbol != b.symbol or len(a.args) != len(b.args):
        return []
    delta = tuple(y - x for x, y in zip(a.args, b.args))
    prev = b.args
    out = []
    end = start + 2
    while end < len(seq):
        cur = seq[end]
        if cur.symbol != a.symbol or len(cur.args) != len(a.args):
            break
        if tuple(y - x for x, y in zip(prev, cur.args)) != delta:
            break
        end += 1
        out.append((end, delta))
        prev = cur.args
    return out


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

    def block_matches(k: int) -> bool:
        base = start + k * period
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


def encode_start_optimal(seq: list[Occ], terminals: list[tuple], rule_count: int, max_period: int = 8):
    terminal_count = len(terminals)
    n = len(seq)
    best = [10**30] * (n + 1)
    choice = [None] * n
    best[n] = 0

    for i in range(n - 1, -1, -1):
        lit = literal_bytes(seq[i], terminal_count, rule_count, terminals)
        best[i] = len(lit) + best[i + 1]
        choice[i] = ("lit", i + 1, lit, 1)

        for end, delta in affine_endpoints(seq, i):
            rb = run_bytes(seq[i], end - i, delta, terminal_count, rule_count, terminals)
            cost = len(rb) + best[end]
            if cost < best[i]:
                best[i] = cost
                choice[i] = ("run", end, rb, end - i)

        for period in range(2, max_period + 1):
            for end, repeats, first, deltas in pattern_endpoints(seq, i, period):
                pb = pattern_bytes(first, deltas, repeats, terminal_count, rule_count, terminals)
                cost = len(pb) + best[end]
                if cost < best[i]:
                    best[i] = cost
                    choice[i] = ("pattern", end, pb, end - i)

    out = bytearray()
    runs = patterns = covered = 0
    i = 0
    while i < n:
        kind, end, blob, span = choice[i]
        out += blob
        if kind == "run":
            runs += 1
            covered += span
        elif kind == "pattern":
            patterns += 1
            covered += span
        i = end
    return bytes(out), runs, patterns, covered


def serialize_native(terminals: list[tuple], rules: list[RuleDef], seq: list[Occ], max_period: int = 8):
    out = bytearray()
    # terminal_count and terminal definitions are part of the fixed VM, not data.
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    terminal_count = len(terminals)

    for rid, rule in enumerate(rules):
        out += child_ref_bytes(rule.left, terminal_count, rid, terminals)
        out += child_ref_bytes(rule.right, terminal_count, rid, terminals)
        # input_arity is derived from child arities; kinds length is derived from it.
        out += pack_kinds(rule.specs)
        for j, spec in enumerate(rule.specs):
            if spec.kind == CONST:
                out += enc_signed(spec.value)
            elif spec.kind in (ADD, NEGADD):
                assert 0 <= spec.ref < j
                out += encode_uleb(j - spec.ref - 1)
                out += enc_signed(spec.value)

    start, runs, patterns, covered = encode_start_optimal(seq, terminals, len(rules), max_period)
    out += start
    return bytes(out), runs, patterns, covered


def profile_tokens(tokens, max_rules: int, max_period: int = 8):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    payload, runs, patterns, covered = serialize_native(terminals, rules, seq, max_period)
    ext = tiny_lzss_ext_encode(payload)
    assert tiny_lzss_ext_decode(ext) == payload
    return {
        "terminals": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
        "payload_bytes": len(payload),
        "balanced_octal_realized_chars": octal_total_chars(payload),
        "prefix16_constructor_chars": len(loader_source_for_bytes(payload)[0]),
        "ext_lzss_bytes": len(ext),
        "ext_lzss_octal_channel_chars": octal_total_chars(ext),
        "ext_lzss_prefix16_constructor_chars": len(loader_source_for_bytes(ext)[0]),
        "direct_byte_chars": direct_byte_loader_chars(payload),
        "runs": runs,
        "patterns": patterns,
        "covered_calls": covered,
        "plus_relations": sum(1 for r in rules for s in r.specs if s.kind == ADD),
        "neg_relations": sum(1 for r in rules for s in r.specs if s.kind == NEGADD),
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
    best_octal = min(sweep, key=lambda r: int(r["balanced_octal_realized_chars"]))
    best_ext_octal = min(sweep, key=lambda r: int(r["ext_lzss_octal_channel_chars"]))
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "sweep": sweep,
        "best_octal": best_octal,
        "best_ext_octal": best_ext_octal,
    }


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
        return

    total = sum(int(r["bf_bytes"]) for r in rows)
    target = total // 10
    octal = sum(int(r["best_octal"]["balanced_octal_realized_chars"]) for r in rows)
    ext_octal = sum(int(r["best_ext_octal"]["ext_lzss_octal_channel_chars"]) for r in rows)
    payload = sum(int(r["best_octal"]["payload_bytes"]) for r in rows)
    print(f"original={total:,} target10x={target:,}")
    print(f"native_isa_payload={payload:,}B")
    print(f"native_isa_balanced_octal={octal:,} budget={target-octal:,}")
    print(f"native_isa_ext_lzss_octal={ext_octal:,} unresolved=lzss_decoder")
    for row in rows:
        b = row["best_octal"]
        print(
            f"{row['name']}: payload={b['payload_bytes']:,} octal={b['balanced_octal_realized_chars']:,} "
            f"R={b['max_rules']} terminals={b['terminals']} runs={b['runs']}+{b['patterns']}"
        )


if __name__ == "__main__":
    main()
