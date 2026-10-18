from __future__ import annotations

"""Structure-aware coding for relational semantic macro grammars.

The grammar itself is unchanged.  This experiment only changes its reversible
serialization, exploiting information known to the decoder:

* rule children are older symbols, so encode backward distance from the rule id;
* call arguments may be encoded as deltas from the previous value of the same
  (symbol, argument-slot) context;
* start symbols may optionally be signed deltas from the previous symbol.

All combinations are measured and the smallest actual BF-native payload loader
is reported.  Tiny extended LZSS remains an optional second layer.
"""

import argparse
from collections import Counter, defaultdict
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


def serialize_variant(terminals, rules: list[RuleDef], seq: list[Occ], *, backward_rules: bool, context_args: bool, delta_symbols: bool) -> bytes:
    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for sk in terminals:
        d = skeleton_definition(sk)
        out += encode_uleb(len(d))
        out += d

    for rid, rule in enumerate(rules):
        current = len(terminals) + rid
        if backward_rules:
            assert rule.left < current and rule.right < current
            out += encode_uleb(current - 1 - rule.left)
            out += encode_uleb(current - 1 - rule.right)
        else:
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
                out += encode_uleb(j - spec.ref - 1)
                out += enc_signed(spec.value)

    prev_args = defaultdict(int)
    prev_symbol = 0
    for occ in seq:
        if delta_symbols:
            out += enc_signed(occ.symbol - prev_symbol)
            prev_symbol = occ.symbol
        else:
            out += encode_uleb(occ.symbol)
        for slot, value in enumerate(occ.args):
            if context_args:
                key = (occ.symbol, slot)
                out += enc_signed(value - prev_args[key])
                prev_args[key] = value
            else:
                out += enc_signed(value)
    return bytes(out)


def profile_tokens(tokens, max_rules: int):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    rows = []
    for backward in (False, True):
        for context in (False, True):
            for sym_delta in (False, True):
                payload = serialize_variant(terminals, rules, seq, backward_rules=backward, context_args=context, delta_symbols=sym_delta)
                ext = tiny_lzss_ext_encode(payload)
                assert tiny_lzss_ext_decode(ext) == payload
                channels = {
                    "direct_byte": direct_byte_loader_chars(payload),
                    "prefix16_bit": len(loader_source_for_bytes(payload)[0]),
                    "ext_lzss_prefix16": len(loader_source_for_bytes(ext)[0]),
                    "ext_lzss_direct_byte": direct_byte_loader_chars(ext),
                }
                best_channel = min(channels, key=channels.get)
                rows.append({
                    "backward_rules": backward,
                    "context_args": context,
                    "delta_symbols": sym_delta,
                    "payload_bytes": len(payload),
                    "ext_lzss_bytes": len(ext),
                    "best_loader_channel": best_channel,
                    "best_loader_chars": channels[best_channel],
                })
    best = min(rows, key=lambda r: int(r["best_loader_chars"]))
    return {"rules": len(rules), "start_symbols": len(seq), "variants": rows, "best": best}


def profile_text(text: str):
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    sweep = []
    for limit in (0, 16, 32, 64, 128):
        row = profile_tokens(tokens, limit)
        row["max_rules"] = limit
        sweep.append(row)
    best_entry = min(sweep, key=lambda r: int(r["best"]["best_loader_chars"]))
    return {"bf_bytes": len(raw), "semantic_tokens": len(tokens), "sweep": sweep, "best_entry": best_entry, "best": best_entry["best"]}


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
            b = r["best"]
            e = r["best_entry"]
            print(f"{r['name']}: loader={b['best_loader_chars']:,} payload={b['payload_bytes']:,} R={e['max_rules']} back={b['backward_rules']} ctx={b['context_args']} symdelta={b['delta_symbols']}")


if __name__ == "__main__":
    main()
