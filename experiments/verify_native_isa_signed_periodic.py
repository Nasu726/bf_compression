from __future__ import annotations

"""Exact decoder/semantic round trip for VM-native signed-periodic grammar."""

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_native_isa_signed_periodic import (
    skeleton_arity,
    serialize_native,
    terminal_skeleton,
)
from profile_parametric_vm import split_token
from profile_semantic_vm import semantic_tokens
from profile_signed_relational_macro_grammar import (
    ADD, CONST, NEGADD, PARAM, Occ, RuleDef, SlotSpec, build_grammar,
)
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


@dataclass(frozen=True)
class Ref:
    terminal: bool
    index: int


@dataclass(frozen=True)
class NativeRule:
    left: Ref
    right: Ref
    specs: tuple[SlotSpec, ...]
    arity: int


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
    raw, pos = read_uleb(data, pos)
    return (raw >> 1) ^ -(raw & 1), pos


def ref_arity(ref: Ref, rules: list[NativeRule]) -> int:
    if ref.terminal:
        return skeleton_arity(terminal_skeleton(ref.index))
    return rules[ref.index].arity


def decode_child(raw: int, current_rule: int) -> Ref:
    if raw % 2 == 0:
        return Ref(True, raw // 2)
    back = (raw - 1) // 2
    rid = current_rule - 1 - back
    assert 0 <= rid < current_rule
    return Ref(False, rid)


def unpack_kinds(blob: bytes, count: int):
    return tuple((blob[(2*j)//8] >> ((2*j)%8)) & 3 for j in range(count))


def decode_start_ref(raw: int, rule_count: int) -> Ref:
    assert raw >= 2
    if raw % 2 == 0:
        return Ref(True, (raw - 2) // 2)
    back = (raw - 3) // 2
    rid = rule_count - 1 - back
    assert 0 <= rid < rule_count
    return Ref(False, rid)


def decode_args(data: bytes, pos: int, arity: int):
    args = []
    for _ in range(arity):
        v, pos = read_signed(data, pos)
        args.append(v)
    return tuple(args), pos


def decode_payload(data: bytes):
    pos = 0
    rule_count, pos = read_uleb(data, pos)
    start_count, pos = read_uleb(data, pos)
    rules: list[NativeRule] = []

    for rid in range(rule_count):
        left_raw, pos = read_uleb(data, pos)
        right_raw, pos = read_uleb(data, pos)
        left = decode_child(left_raw, rid)
        right = decode_child(right_raw, rid)
        input_arity = ref_arity(left, rules) + ref_arity(right, rules)
        kinds_len = (2 * input_arity + 7) // 8
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
                v, pos = read_signed(data, pos)
                specs.append(SlotSpec(CONST, value=v))
            elif kind in (ADD, NEGADD):
                back, pos = read_uleb(data, pos)
                ref = j - 1 - back
                assert 0 <= ref < j
                delta, pos = read_signed(data, pos)
                specs.append(SlotSpec(kind, ref=ref, value=delta))
            else:
                raise AssertionError(kind)
        rules.append(NativeRule(left, right, tuple(specs), output_arity))

    start: list[tuple[Ref, tuple[int, ...]]] = []
    while len(start) < start_count:
        tag, pos = read_uleb(data, pos)
        if tag >= 2:
            ref = decode_start_ref(tag, rule_count)
            args, pos = decode_args(data, pos, ref_arity(ref, rules))
            start.append((ref, args))
            continue
        if tag == 0:
            raw, pos = read_uleb(data, pos)
            ref = decode_start_ref(raw, rule_count)
            count, pos = read_uleb(data, pos)
            arity = ref_arity(ref, rules)
            base, pos = decode_args(data, pos, arity)
            delta, pos = decode_args(data, pos, arity)
            cur = base
            for _ in range(count):
                start.append((ref, cur))
                cur = tuple(x+d for x, d in zip(cur, delta))
            continue

        period, pos = read_uleb(data, pos)
        repeats, pos = read_uleb(data, pos)
        slots = []
        for _ in range(period):
            raw, pos = read_uleb(data, pos)
            ref = decode_start_ref(raw, rule_count)
            arity = ref_arity(ref, rules)
            base, pos = decode_args(data, pos, arity)
            delta, pos = decode_args(data, pos, arity)
            slots.append((ref, base, delta))
        for k in range(repeats):
            for ref, base, delta in slots:
                start.append((ref, tuple(x+k*d for x, d in zip(base, delta))))
        assert len(start) <= start_count

    assert len(start) == start_count
    assert pos == len(data), (pos, len(data))
    return rules, start


def expand(ref: Ref, args: tuple[int, ...], rules: list[NativeRule]):
    if ref.terminal:
        sk = terminal_skeleton(ref.index)
        assert len(args) == skeleton_arity(sk)
        return [(sk, args)]

    rule = rules[ref.index]
    assert len(args) == rule.arity
    it = iter(args)
    vector = []
    for spec in rule.specs:
        if spec.kind == PARAM:
            vector.append(next(it))
        elif spec.kind == CONST:
            vector.append(spec.value)
        elif spec.kind == ADD:
            vector.append(vector[spec.ref] + spec.value)
        elif spec.kind == NEGADD:
            vector.append(-vector[spec.ref] + spec.value)
        else:
            raise AssertionError(spec)
    try:
        next(it)
        raise AssertionError("unused arg")
    except StopIteration:
        pass

    left_n = ref_arity(rule.left, rules)
    return expand(rule.left, tuple(vector[:left_n]), rules) + expand(rule.right, tuple(vector[left_n:]), rules)


def verify_tokens(tokens, max_rules=128, max_period=8):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    payload, runs, patterns, covered = serialize_native(terminals, rules, seq, max_period)
    native_rules, start = decode_payload(payload)
    recovered = []
    for ref, args in start:
        recovered.extend(expand(ref, args, native_rules))
    expected = [split_token(t) for t in tokens]
    assert recovered == expected, (len(recovered), len(expected))
    return len(payload), len(rules), len(seq), runs, patterns, covered


def tokens_from_text(text: str):
    return semantic_tokens(canonicalize(parse(precanonicalize(strip_bf(text)))), Counter())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--max-rules", type=int, default=128)
    ap.add_argument("--max-period", type=int, default=8)
    args = ap.parse_args()

    synthetic = []
    for k in range(20):
        base = 10 + 7*k
        synthetic += [("M", base), ("M", 5-base), ("A", 3+2*k)]
    verify_tokens(synthetic, max_rules=64, max_period=8)

    synthetic_affine = []
    # Exercise canonical arity-bearing terminal codes without relying on parser output.
    for k in range(12):
        synthetic_affine += [("AFFINE", ((1, 2+k), (-1, 5-k)))]
    verify_tokens(synthetic_affine, max_rules=16, max_period=8)

    for name in args.files:
        stats = verify_tokens(tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore")), args.max_rules, args.max_period)
        print(
            f"{name}: native-ISA round-trip ok payload={stats[0]:,} rules={stats[1]} "
            f"start={stats[2]:,} runs={stats[3]} patterns={stats[4]} covered={stats[5]:,}"
        )
    print("native-ISA signed-periodic reconstruction: ok")


if __name__ == "__main__":
    main()
