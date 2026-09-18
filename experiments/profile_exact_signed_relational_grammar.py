from __future__ import annotations

"""Exact-gain Re-Pair search with signed relational parameter binding.

Unlike the frequency-first prototype, every distinct adjacent symbol pair is
scored by its exact change in serialized payload length.  Candidate positions
are collected in one pass, so scoring one grammar round is linear in the start
sequence up to parameter-vector width.  Only the winning pair is materialized.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_signed_relational_macro_grammar import (
    ADD, CONST, NEGADD, Occ, RuleDef, build_initial, enc_signed, infer_specs,
    pack_kinds,
)
from profile_parametric_vm import skeleton_definition
from profile_semantic_vm import encode_uleb, semantic_tokens
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def occ_bytes(occ: Occ) -> int:
    n = len(encode_uleb(occ.symbol))
    for value in occ.args:
        n += len(enc_signed(value))
    return n


def rule_bytes(rule: RuleDef) -> int:
    n = len(encode_uleb(rule.left)) + len(encode_uleb(rule.right)) + len(encode_uleb(rule.input_arity))
    kinds = pack_kinds(rule.specs)
    n += len(encode_uleb(len(kinds))) + len(kinds)
    for j, spec in enumerate(rule.specs):
        if spec.kind == CONST:
            n += len(enc_signed(spec.value))
        elif spec.kind in (ADD, NEGADD):
            n += len(encode_uleb(j - spec.ref - 1)) + len(enc_signed(spec.value))
    return n


def pair_positions(seq: list[Occ]):
    raw = defaultdict(list)
    for i in range(len(seq) - 1):
        raw[(seq[i].symbol, seq[i + 1].symbol)].append(i)
    out = {}
    for pair, positions in raw.items():
        selected = []
        last = -2
        for i in positions:
            if i >= last + 2:
                selected.append(i)
                last = i
        if len(selected) > 2:
            out[pair] = selected
    return out


def candidate(seq, pair, positions, arities, new_symbol, rule_count):
    vectors = [seq[i].args + seq[i + 1].args for i in positions]
    input_arity = arities[pair[0]] + arities[pair[1]]
    assert all(len(v) == input_arity for v in vectors)
    specs, free_slots = infer_specs(vectors)
    rule = RuleDef(pair[0], pair[1], input_arity, specs, len(free_slots))

    before = 0
    after = 0
    for i, vector in zip(positions, vectors):
        before += occ_bytes(seq[i]) + occ_bytes(seq[i + 1])
        after += occ_bytes(Occ(new_symbol, tuple(vector[j] for j in free_slots)))
    new_len = len(seq) - len(positions)
    header_delta = (
        len(encode_uleb(new_len)) - len(encode_uleb(len(seq)))
        + len(encode_uleb(rule_count + 1)) - len(encode_uleb(rule_count))
    )
    gain = before - after - rule_bytes(rule) - header_delta
    return gain, rule, free_slots


def apply_pair(seq, positions, new_symbol, free_slots):
    pos_set = set(positions)
    out = []
    i = 0
    while i < len(seq):
        if i in pos_set:
            vector = seq[i].args + seq[i + 1].args
            out.append(Occ(new_symbol, tuple(vector[j] for j in free_slots)))
            i += 2
        else:
            out.append(seq[i])
            i += 1
    return out


def serialize(terminals, rules, seq):
    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for sk in terminals:
        d = skeleton_definition(sk)
        out += encode_uleb(len(d)) + d
    for rule in rules:
        out += encode_uleb(rule.left) + encode_uleb(rule.right) + encode_uleb(rule.input_arity)
        kinds = pack_kinds(rule.specs)
        out += encode_uleb(len(kinds)) + kinds
        for j, spec in enumerate(rule.specs):
            if spec.kind == CONST:
                out += enc_signed(spec.value)
            elif spec.kind in (ADD, NEGADD):
                out += encode_uleb(j - spec.ref - 1) + enc_signed(spec.value)
    for occ in seq:
        out += encode_uleb(occ.symbol)
        for value in occ.args:
            out += enc_signed(value)
    return bytes(out)


def build_grammar(tokens, max_rules):
    terminals, arities, seq = build_initial(tokens)
    rules = []
    for _ in range(max_rules):
        positions_by_pair = pair_positions(seq)
        if not positions_by_pair:
            break
        new_symbol = len(terminals) + len(rules)
        best = None
        for pair, positions in positions_by_pair.items():
            gain, rule, free_slots = candidate(seq, pair, positions, arities, new_symbol, len(rules))
            if best is None or gain > best[0]:
                best = (gain, pair, positions, rule, free_slots)
        if best is None or best[0] <= 0:
            break
        gain, pair, positions, rule, free_slots = best
        seq = apply_pair(seq, positions, new_symbol, free_slots)
        rules.append(rule)
        arities.append(rule.arity)
    return terminals, arities, rules, seq


def profile_tokens(tokens, max_rules):
    terminals, arities, rules, seq = build_grammar(tokens, max_rules)
    payload = serialize(terminals, rules, seq)
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
        "payload_bytes": len(payload),
        "ext_lzss_bytes": len(ext),
        "call_parameter_values": sum(len(o.args) for o in seq),
        "plus_relations": sum(1 for r in rules for s in r.specs if s.kind == ADD),
        "neg_relations": sum(1 for r in rules for s in r.specs if s.kind == NEGADD),
        "best_loader_channel": best_channel,
        "best_loader_chars": channels[best_channel],
    }


def profile_text(text):
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    sweep = []
    for limit in (0, 16, 32, 64, 128):
        row = profile_tokens(tokens, limit)
        row["max_rules"] = limit
        sweep.append(row)
    best = min(sweep, key=lambda r: int(r["best_loader_chars"]))
    return {"bf_bytes": len(raw), "semantic_tokens": len(tokens), "sweep": sweep, "best": best}


def main():
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
            b=r["best"]
            print(f"{r['name']}: loader={b['best_loader_chars']:,} payload={b['payload_bytes']:,} params={b['call_parameter_values']:,} +/-rel={b['plus_relations']:,}/{b['neg_relations']:,} R={b['max_rules']}")


if __name__ == "__main__":
    main()
