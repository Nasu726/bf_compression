from __future__ import annotations

"""Re-Pair semantic macro grammar with exact relative-parameter binding.

This extends constant-binding macros with one cheap relation:

    slot[j] = slot[r] + delta,  r < j

whenever that equality holds for every occurrence of a candidate macro.  Such
relations are common when compiler templates are translated across the tape:
absolute offsets change, while relative offsets inside the template stay fixed.

Every rule slot is encoded as exactly one of:

* PARAM: supplied by the call site;
* CONST: stored once in the rule definition;
* ADD: reconstructed from an earlier slot plus a stored signed delta.

ADD references only earlier slots, so rule decoding is acyclic by construction.
All payload-size decisions use exact serialization size.  The resulting byte
stream is also measured through the verified BF-native prefix channel, with and
without the tiny extended LZSS layer.
"""

from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import argparse
import json
import sys
from typing import Hashable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import direct_byte_loader_chars, loader_source_for_bytes
from profile_parametric_vm import split_token, skeleton_definition
from profile_semantic_vm import encode_uleb, semantic_tokens, zigzag
from profile_tiny_lzss import tiny_lzss_ext_decode, tiny_lzss_ext_encode
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


PARAM = 0
CONST = 1
ADD = 2


@dataclass(frozen=True)
class Occ:
    symbol: int
    args: tuple[int, ...]


@dataclass(frozen=True)
class SlotSpec:
    kind: int
    ref: int = -1
    value: int = 0


@dataclass(frozen=True)
class RuleDef:
    left: int
    right: int
    input_arity: int
    specs: tuple[SlotSpec, ...]
    arity: int


def enc_signed(value: int) -> bytes:
    return encode_uleb(zigzag(value))


def build_initial(tokens):
    terminal_ids: dict[tuple[Hashable, ...], int] = {}
    terminals: list[tuple[Hashable, ...]] = []
    arities: list[int] = []
    seq: list[Occ] = []
    for token in tokens:
        sk, args = split_token(token)
        sid = terminal_ids.get(sk)
        if sid is None:
            sid = len(terminals)
            terminal_ids[sk] = sid
            terminals.append(sk)
            arities.append(len(args))
        else:
            assert arities[sid] == len(args)
        seq.append(Occ(sid, args))
    return terminals, arities, seq


def nonoverlap_positions(seq: list[Occ], pair: tuple[int, int]) -> list[int]:
    out: list[int] = []
    i = 0
    while i + 1 < len(seq):
        if (seq[i].symbol, seq[i + 1].symbol) == pair:
            out.append(i)
            i += 2
        else:
            i += 1
    return out


def infer_specs(vectors: list[tuple[int, ...]]) -> tuple[tuple[SlotSpec, ...], tuple[int, ...]]:
    """Infer constants and exact translation relations.

    We deliberately restrict relations to coefficient +1.  This captures
    translated compiler templates, keeps the decoder tiny, and avoids paying
    for a general multiplication primitive merely to improve compression.
    """
    width = len(vectors[0])
    specs: list[SlotSpec] = []
    free_slots: list[int] = []

    for j in range(width):
        col = [v[j] for v in vectors]
        if all(x == col[0] for x in col):
            specs.append(SlotSpec(CONST, value=col[0]))
            continue

        best: SlotSpec | None = None
        # Prefer the nearest previous slot: reference distance serializes more
        # cheaply and tends to follow local compiler-layout structure.
        for r in range(j - 1, -1, -1):
            delta = vectors[0][j] - vectors[0][r]
            if all(v[j] - v[r] == delta for v in vectors):
                best = SlotSpec(ADD, ref=r, value=delta)
                break
        if best is not None:
            specs.append(best)
        else:
            specs.append(SlotSpec(PARAM))
            free_slots.append(j)

    return tuple(specs), tuple(free_slots)


def factor_once(
    seq: list[Occ],
    pair: tuple[int, int],
    arities: list[int],
    new_symbol: int,
) -> tuple[list[Occ], RuleDef] | None:
    positions = nonoverlap_positions(seq, pair)
    if len(positions) <= 2:
        return None
    vectors = [seq[i].args + seq[i + 1].args for i in positions]
    input_arity = len(vectors[0])
    assert input_arity == arities[pair[0]] + arities[pair[1]]
    assert all(len(v) == input_arity for v in vectors)

    specs, free_slots = infer_specs(vectors)
    pos_set = set(positions)
    out: list[Occ] = []
    i = 0
    while i < len(seq):
        if i in pos_set:
            vector = seq[i].args + seq[i + 1].args
            out.append(Occ(new_symbol, tuple(vector[j] for j in free_slots)))
            i += 2
        else:
            out.append(seq[i])
            i += 1

    return out, RuleDef(
        left=pair[0],
        right=pair[1],
        input_arity=input_arity,
        specs=specs,
        arity=len(free_slots),
    )


def pack_kinds(specs: tuple[SlotSpec, ...]) -> bytes:
    out = bytearray((2 * len(specs) + 7) // 8)
    for i, spec in enumerate(specs):
        assert spec.kind in (PARAM, CONST, ADD)
        bit = 2 * i
        out[bit // 8] |= spec.kind << (bit % 8)
    return bytes(out)


def serialize(terminals, rules: list[RuleDef], seq: list[Occ]) -> bytes:
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

    for occ in seq:
        out += encode_uleb(occ.symbol)
        for value in occ.args:
            out += enc_signed(value)
    return bytes(out)


def build_grammar(tokens, max_rules: int):
    terminals, arities, seq = build_initial(tokens)
    rules: list[RuleDef] = []
    initial_params = sum(len(o.args) for o in seq)

    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter((seq[i].symbol, seq[i + 1].symbol) for i in range(len(seq) - 1))
        candidates = []
        for pair, _freq in counts.most_common(64):
            if len(nonoverlap_positions(seq, pair)) > 2:
                candidates.append(pair)
        if not candidates:
            break

        new_symbol = len(terminals) + len(rules)
        before = serialize(terminals, rules, seq)

        # Fast path: Re-Pair's most frequent non-overlapping pair.  We still
        # accept it only when exact serialized payload shrinks.
        chosen = candidates[0]
        factored = factor_once(seq, chosen, arities, new_symbol)
        if factored is None:
            break
        seq2, rule = factored
        gain = len(before) - len(serialize(terminals, rules + [rule], seq2))

        # Frequency is only a heuristic.  If the first pair is not profitable
        # after relation-definition overhead, inspect a bounded fallback set.
        if gain <= 0:
            best = None
            for pair in candidates[1:16]:
                f2 = factor_once(seq, pair, arities, new_symbol)
                if f2 is None:
                    continue
                s2, r2 = f2
                g2 = len(before) - len(serialize(terminals, rules + [r2], s2))
                if best is None or g2 > best[0]:
                    best = (g2, s2, r2)
            if best is None or best[0] <= 0:
                break
            gain, seq2, rule = best

        seq = seq2
        rules.append(rule)
        arities.append(rule.arity)

    return terminals, arities, rules, seq, initial_params


def profile_tokens(tokens, max_rules: int) -> dict[str, int | str]:
    terminals, arities, rules, seq, initial_params = build_grammar(tokens, max_rules)
    payload = serialize(terminals, rules, seq)
    ext = tiny_lzss_ext_encode(payload)
    assert tiny_lzss_ext_decode(ext) == payload

    call_params = sum(len(o.args) for o in seq)
    const_defs = sum(1 for r in rules for s in r.specs if s.kind == CONST)
    add_defs = sum(1 for r in rules for s in r.specs if s.kind == ADD)

    bit_loader = len(loader_source_for_bytes(payload)[0])
    byte_loader = direct_byte_loader_chars(payload)
    ext_bit_loader = len(loader_source_for_bytes(ext)[0])
    ext_byte_loader = direct_byte_loader_chars(ext)
    choices = {
        "direct_byte": byte_loader,
        "prefix16_bit": bit_loader,
        "ext_lzss_prefix16": ext_bit_loader,
        "ext_lzss_direct_byte": ext_byte_loader,
    }
    best_channel = min(choices, key=choices.get)
    return {
        "terminals": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
        "initial_parameter_occurrences": initial_params,
        "call_parameter_values": call_params,
        "constant_definitions": const_defs,
        "add_relation_definitions": add_defs,
        "payload_bytes": len(payload),
        "direct_byte_loader_chars": byte_loader,
        "bf_native_loader_chars": bit_loader,
        "ext_lzss_bytes": len(ext),
        "ext_lzss_bit_loader_chars": ext_bit_loader,
        "ext_lzss_direct_byte_loader_chars": ext_byte_loader,
        "best_loader_channel": best_channel,
        "best_loader_chars": choices[best_channel],
    }


def profile_text(text: str) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    tokens = semantic_tokens(nodes, Counter())
    sweep = []
    for limit in (0, 16, 32, 64, 128):
        row = profile_tokens(tokens, limit)
        row["max_rules"] = limit
        sweep.append(row)
    best = min(sweep, key=lambda r: int(r["best_loader_chars"]))
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "sweep": sweep,
        "best": best,
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
            b = r["best"]
            print(
                f"{r['name']}: payload={b['payload_bytes']:,} best_loader={b['best_loader_chars']:,} "
                f"via={b['best_loader_channel']} call_params={b['call_parameter_values']:,} "
                f"relations={b['add_relation_definitions']:,} rules={b['rules']}"
            )


if __name__ == "__main__":
    main()
