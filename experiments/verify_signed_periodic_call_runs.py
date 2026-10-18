from __future__ import annotations

"""Verify full serialized signed-relational + periodic grammar round trips.

This checks substantially more than the start-stream RUN codec:

* terminal definition bytes;
* every rule child/input arity;
* packed PARAM/CONST/ADD/NEGADD slot kinds;
* CONST values and relation ref/delta payloads;
* literal, affine RUN, and PATTERN_RUN start records;
* recursive expansion back to the exact semantic-token stream.

The verifier exists specifically to catch serializer omissions such as forgetting
NEGADD payload bytes while the in-memory grammar itself remains correct.
"""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_parametric_vm import skeleton_definition, split_token
from profile_signed_periodic_call_runs import serialize_with_patterns
from profile_signed_relational_macro_grammar import (
    ADD,
    CONST,
    NEGADD,
    PARAM,
    Occ,
    RuleDef,
    SlotSpec,
    build_grammar,
)
from profile_semantic_vm import semantic_tokens
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def read_uleb(data: bytes, pos: int):
    value = 0
    shift = 0
    while True:
        assert pos < len(data)
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


def unpack_kinds(blob: bytes, count: int) -> tuple[int, ...]:
    kinds = []
    for j in range(count):
        bit = 2 * j
        kinds.append((blob[bit // 8] >> (bit % 8)) & 3)
    return tuple(kinds)


def decode_start(data: bytes, pos: int, expected: int, escape_run: int, escape_pattern: int, arities: list[int]):
    out = []
    run_records = pattern_records = 0
    while len(out) < expected:
        symbol, pos = read_uleb(data, pos)
        if symbol < escape_run:
            args, pos = read_args(data, pos, arities[symbol])
            out.append(Occ(symbol, args))
            continue
        if symbol == escape_run:
            target, pos = read_uleb(data, pos)
            count, pos = read_uleb(data, pos)
            assert 0 <= target < escape_run
            base, pos = read_args(data, pos, arities[target])
            delta, pos = read_args(data, pos, arities[target])
            cur = base
            for _ in range(count):
                out.append(Occ(target, cur))
                cur = tuple(x + d for x, d in zip(cur, delta))
            run_records += 1
            continue

        assert symbol == escape_pattern
        period, pos = read_uleb(data, pos)
        repeats, pos = read_uleb(data, pos)
        assert period >= 2 and repeats >= 3
        slots = []
        for _ in range(period):
            target, pos = read_uleb(data, pos)
            assert 0 <= target < escape_run
            base, pos = read_args(data, pos, arities[target])
            delta, pos = read_args(data, pos, arities[target])
            slots.append((target, base, delta))
        for k in range(repeats):
            for target, base, delta in slots:
                args = tuple(x + k * d for x, d in zip(base, delta))
                out.append(Occ(target, args))
        pattern_records += 1

        assert len(out) <= expected

    assert len(out) == expected
    return out, pos, run_records, pattern_records


def decode_serialized(data: bytes, expected_terminal_arities: list[int]):
    pos = 0
    terminal_count, pos = read_uleb(data, pos)
    rule_count, pos = read_uleb(data, pos)
    start_count, pos = read_uleb(data, pos)
    assert terminal_count == len(expected_terminal_arities)

    terminal_defs = []
    for _ in range(terminal_count):
        length, pos = read_uleb(data, pos)
        assert pos + length <= len(data)
        terminal_defs.append(data[pos:pos + length])
        pos += length

    arities = list(expected_terminal_arities)
    rules: list[RuleDef] = []
    for rid in range(rule_count):
        left, pos = read_uleb(data, pos)
        right, pos = read_uleb(data, pos)
        input_arity, pos = read_uleb(data, pos)
        kinds_len, pos = read_uleb(data, pos)
        assert kinds_len == (2 * input_arity + 7) // 8
        kinds_blob = data[pos:pos + kinds_len]
        assert len(kinds_blob) == kinds_len
        pos += kinds_len
        kinds = unpack_kinds(kinds_blob, input_arity)

        specs = []
        output_arity = 0
        for j, kind in enumerate(kinds):
            if kind == PARAM:
                specs.append(SlotSpec(PARAM))
                output_arity += 1
            elif kind == CONST:
                value, pos = read_signed(data, pos)
                specs.append(SlotSpec(CONST, value=value))
            elif kind in (ADD, NEGADD):
                ref_back, pos = read_uleb(data, pos)
                ref = j - ref_back - 1
                assert 0 <= ref < j
                delta, pos = read_signed(data, pos)
                specs.append(SlotSpec(kind, ref=ref, value=delta))
            else:
                raise AssertionError(kind)

        current = terminal_count + rid
        assert left < current and right < current
        assert arities[left] + arities[right] == input_arity
        rule = RuleDef(
            left=left,
            right=right,
            input_arity=input_arity,
            specs=tuple(specs),
            arity=output_arity,
        )
        rules.append(rule)
        arities.append(output_arity)

    escape_run = terminal_count + rule_count
    seq, pos, runs, patterns = decode_start(
        data, pos, start_count, escape_run, escape_run + 1, arities
    )
    assert pos == len(data), (pos, len(data))
    return terminal_defs, rules, seq, arities, runs, patterns


def expand_occ(occ: Occ, terminals, arities, rules):
    terminal_count = len(terminals)
    if occ.symbol < terminal_count:
        assert len(occ.args) == arities[occ.symbol]
        return [(terminals[occ.symbol], occ.args)]

    rule = rules[occ.symbol - terminal_count]
    assert len(occ.args) == rule.arity
    arg_iter = iter(occ.args)
    vector: list[int] = []
    for j, spec in enumerate(rule.specs):
        if spec.kind == PARAM:
            vector.append(next(arg_iter))
        elif spec.kind == CONST:
            vector.append(spec.value)
        elif spec.kind == ADD:
            vector.append(vector[spec.ref] + spec.value)
        elif spec.kind == NEGADD:
            vector.append(-vector[spec.ref] + spec.value)
        else:
            raise AssertionError(spec)
    try:
        next(arg_iter)
        raise AssertionError("unused call argument")
    except StopIteration:
        pass

    left_arity = arities[rule.left]
    left = Occ(rule.left, tuple(vector[:left_arity]))
    right = Occ(rule.right, tuple(vector[left_arity:]))
    return expand_occ(left, terminals, arities, rules) + expand_occ(right, terminals, arities, rules)


def verify_tokens(tokens, max_rules=128, max_period=8):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    payload, expected_runs, expected_patterns, expected_covered = serialize_with_patterns(
        terminals, rules, seq, max_period
    )
    terminal_defs, decoded_rules, decoded_seq, decoded_arities, runs, patterns = decode_serialized(
        payload, arities[:len(terminals)]
    )

    assert terminal_defs == [skeleton_definition(t) for t in terminals]
    assert decoded_rules == rules
    assert decoded_seq == seq
    assert runs == expected_runs
    assert patterns == expected_patterns

    recovered = []
    for occ in decoded_seq:
        recovered.extend(expand_occ(occ, terminals, decoded_arities, decoded_rules))
    expected = [split_token(t) for t in tokens]
    assert recovered == expected, (len(recovered), len(expected))

    return {
        "tokens": len(tokens),
        "rules": len(rules),
        "start": len(seq),
        "runs": runs,
        "patterns": patterns,
        "covered": expected_covered,
        "neg_relations": sum(1 for r in rules for s in r.specs if s.kind == NEGADD),
        "payload_bytes": len(payload),
    }


def tokens_from_text(text: str):
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--max-rules", type=int, default=128)
    ap.add_argument("--max-period", type=int, default=8)
    args = ap.parse_args()

    synthetic = []
    for k in range(20):
        base = 10 + 7 * k
        synthetic += [("M", base), ("M", 5 - base)]
    stats = verify_tokens(synthetic, max_rules=64, max_period=8)
    assert stats["neg_relations"] > 0, stats

    periodic = []
    for k in range(20):
        periodic += [("M", 10 + 7 * k), ("A", 3 + 2 * k)]
    stats = verify_tokens(periodic, max_rules=0, max_period=8)
    assert stats["patterns"] >= 1 and stats["covered"] == stats["start"], stats

    for name in args.files:
        stats = verify_tokens(
            tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore")),
            max_rules=args.max_rules,
            max_period=args.max_period,
        )
        print(
            f"{name}: full signed-periodic serialization round-trip ok "
            f"tokens={stats['tokens']:,} rules={stats['rules']:,} start={stats['start']:,} "
            f"runs={stats['runs']:,} patterns={stats['patterns']:,} "
            f"neg_relations={stats['neg_relations']:,} payload={stats['payload_bytes']:,}"
        )

    print("signed-periodic full serialization reconstruction: ok")


if __name__ == "__main__":
    main()
