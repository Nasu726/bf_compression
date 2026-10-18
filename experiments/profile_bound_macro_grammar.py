from __future__ import annotations

"""Parameterized Re-Pair with constants bound into macro definitions.

Naively sharing only opcode skeletons is poor because every numeric slot becomes
a call parameter.  This grammar recursively factors repeated adjacent semantic
VM symbols, but for every rule it binds argument slots that are identical over
all rule occurrences and passes only genuinely varying slots.

The representation is exactly reconstructible by induction over rule creation
order.  Serialization includes all symbol IDs, masks, constants and remaining
call arguments.  We report several *actual BF payload-constructor* costs:

* direct-byte: serialized byte v is initialized directly into one zero cell;
* prefix16-bit: arbitrary serialized bits use the verified near-capacity
  16-symbol unequal-cost channel;
* ext-LZSS + prefix16: a tiny fixed-window codec followed by the same channel.

Decoder / grammar-threaded semantic-VM source is still extra.
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


@dataclass(frozen=True)
class Occ:
    symbol: int
    args: tuple[int, ...]


@dataclass(frozen=True)
class RuleDef:
    left: int
    right: int
    input_arity: int
    constant_mask: tuple[bool, ...]
    constants: tuple[int, ...]
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
    mask = tuple(all(v[j] == vectors[0][j] for v in vectors) for j in range(input_arity))
    constants = tuple(vectors[0][j] for j, fixed in enumerate(mask) if fixed)
    variable_indices = [j for j, fixed in enumerate(mask) if not fixed]

    pos_set = set(positions)
    out: list[Occ] = []
    i = 0
    while i < len(seq):
        if i in pos_set:
            vector = seq[i].args + seq[i + 1].args
            args = tuple(vector[j] for j in variable_indices)
            out.append(Occ(new_symbol, args))
            i += 2
        else:
            out.append(seq[i])
            i += 1
    rule = RuleDef(
        left=pair[0],
        right=pair[1],
        input_arity=input_arity,
        constant_mask=mask,
        constants=constants,
        arity=len(variable_indices),
    )
    return out, rule


def pack_mask(mask: tuple[bool, ...]) -> bytes:
    out = bytearray((len(mask) + 7) // 8)
    for i, fixed in enumerate(mask):
        if fixed:
            out[i // 8] |= 1 << (i % 8)
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
        mask = pack_mask(rule.constant_mask)
        out += encode_uleb(len(mask))
        out += mask
        for value in rule.constants:
            out += enc_signed(value)
    for occ in seq:
        out += encode_uleb(occ.symbol)
        for value in occ.args:
            out += enc_signed(value)
    return bytes(out)


def build_grammar(tokens, max_rules: int):
    """Return exact (terminals, arities, rules, start sequence, initial params)."""
    terminals, arities, seq = build_initial(tokens)
    rules: list[RuleDef] = []
    initial_params = sum(len(o.args) for o in seq)

    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter((seq[i].symbol, seq[i + 1].symbol) for i in range(len(seq) - 1))
        chosen = None
        for pair, _freq in counts.most_common(64):
            if len(nonoverlap_positions(seq, pair)) > 2:
                chosen = pair
                break
        if chosen is None:
            break
        new_symbol = len(terminals) + len(rules)
        factored = factor_once(seq, chosen, arities, new_symbol)
        if factored is None:
            break
        new_seq, rule = factored
        before = serialize(terminals, rules, seq)
        after = serialize(terminals, rules + [rule], new_seq)
        if len(after) > len(before):
            best = None
            for pair, _freq in counts.most_common(32):
                f = factor_once(seq, pair, arities, new_symbol)
                if f is None:
                    continue
                s2, r2 = f
                p2 = serialize(terminals, rules + [r2], s2)
                gain = len(before) - len(p2)
                if best is None or gain > best[0]:
                    best = (gain, s2, r2)
            if best is None or best[0] <= 0:
                break
            _, new_seq, rule = best
        rules.append(rule)
        arities.append(rule.arity)
        seq = new_seq

    return terminals, arities, rules, seq, initial_params


def profile_tokens(tokens, max_rules: int) -> dict[str, int | str]:
    terminals, arities, rules, seq, initial_params = build_grammar(tokens, max_rules)
    payload = serialize(terminals, rules, seq)
    ext = tiny_lzss_ext_encode(payload)
    assert tiny_lzss_ext_decode(ext) == payload
    final_params = sum(len(o.args) for o in seq) + sum(len(r.constants) for r in rules)
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
        "stored_parameter_values": final_params,
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
    for limit in (0, 16, 32, 64, 128, 256, 512):
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
    rows=[]
    for name in args.files:
        p=Path(name)
        rows.append({"name":str(p), **profile_text(p.read_text(encoding="ascii",errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for r in rows:
            b=r['best']
            print(
                f"{r['name']}: payload={b['payload_bytes']:,} best_loader={b['best_loader_chars']:,} "
                f"via={b['best_loader_channel']} params={b['stored_parameter_values']:,} rules={b['rules']}"
            )


if __name__ == "__main__":
    main()
