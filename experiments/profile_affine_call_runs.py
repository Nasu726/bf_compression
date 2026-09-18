from __future__ import annotations

"""Exact source-cost profiling for affine runs of relational macro calls.

After relational macro construction, the start sequence contains occurrences
Occ(symbol, args).  If consecutive calls to the same symbol satisfy

    args_i = base + i * delta,

we may encode the whole run as one RUN record.  Ordinary calls keep their old
encoding and therefore pay no new tag byte: the first unused symbol id is the
RUN escape code.  A dynamic program chooses literals versus RUN records by
exact serialized byte length before the BF-native payload channel is applied.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_parametric_vm import skeleton_definition
from profile_relational_macro_grammar import ADD, CONST, Occ, RuleDef, build_grammar, enc_signed, pack_kinds
from profile_semantic_vm import encode_uleb, semantic_tokens
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def literal_bytes(occ: Occ) -> bytes:
    out = bytearray(encode_uleb(occ.symbol))
    for value in occ.args:
        out += enc_signed(value)
    return bytes(out)


def run_bytes(escape: int, symbol: int, count: int, base: tuple[int, ...], delta: tuple[int, ...]) -> bytes:
    out = bytearray()
    out += encode_uleb(escape)
    out += encode_uleb(symbol)
    out += encode_uleb(count)
    for value in base:
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
    out = []
    prev = b.args
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


def encode_start_optimal(seq: list[Occ], escape: int):
    n = len(seq)
    best = [10**30] * (n + 1)
    choice = [None] * n
    best[n] = 0
    for i in range(n - 1, -1, -1):
        lit = literal_bytes(seq[i])
        best[i] = len(lit) + best[i + 1]
        choice[i] = ("lit", i + 1, lit)
        for end, delta in affine_endpoints(seq, i):
            rb = run_bytes(escape, seq[i].symbol, end - i, seq[i].args, delta)
            cost = len(rb) + best[end]
            if cost < best[i]:
                best[i] = cost
                choice[i] = ("run", end, rb)

    out = bytearray()
    runs = 0
    covered = 0
    i = 0
    while i < n:
        kind, end, payload = choice[i]
        out += payload
        if kind == "run":
            runs += 1
            covered += end - i
        i = end
    return bytes(out), runs, covered


def serialize_with_runs(terminals, rules: list[RuleDef], seq: list[Occ]):
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
    escape = len(terminals) + len(rules)
    start, runs, covered = encode_start_optimal(seq, escape)
    out += start
    return bytes(out), runs, covered


def profile_tokens(tokens, max_rules: int):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    payload, runs, covered = serialize_with_runs(terminals, rules, seq)
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
        "terminals": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
        "affine_runs": runs,
        "run_covered_calls": covered,
        "payload_bytes": len(payload),
        "ext_lzss_bytes": len(ext),
        "best_loader_channel": best_channel,
        "best_loader_chars": channels[best_channel],
    }


def profile_text(text: str):
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
        for row in rows:
            b = row["best"]
            print(f"{row['name']}: loader={b['best_loader_chars']:,} payload={b['payload_bytes']:,} runs={b['affine_runs']:,} covered={b['run_covered_calls']:,} R={b['max_rules']}")


if __name__ == "__main__":
    main()
