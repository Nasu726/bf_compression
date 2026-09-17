from __future__ import annotations

"""Parameterized Re-Pair with constants bound into macro definitions.

Naively sharing only opcode skeletons was a negative result: every numeric slot
became a call parameter, leaving ~93k parameter occurrences on the current
suite.  Compiler templates should instead bind values that are invariant across
all occurrences of a macro and expose only the genuinely varying slots.

This experiment starts from exact semantic-VM terminals.  Each terminal kind is
a symbol whose occurrence carries its numeric arguments.  Repeated adjacent
symbol pairs are factored recursively.  For a new rule R=(A,B):

* concatenate A/B call arguments at every non-overlapping occurrence;
* any argument slot identical in every occurrence is stored once in R;
* only non-constant slots remain parameters of each R call.

This is exactly reconstructible by induction over rule creation order.  It is a
strictly more expressive executable grammar than ordinary BPE while avoiding
"free parameters".  The serialization includes symbol IDs, binding masks,
constant values, and all remaining call arguments; reported BF-native loader
length is therefore a realizable payload-construction cost before adding the
small grammar-threaded semantic VM.
"""

from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import argparse
import json
import sys
from typing import Hashable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import loader_source_for_bytes
from profile_parametric_vm import split_token, skeleton_definition
from profile_semantic_vm import encode_uleb, semantic_tokens, zigzag
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


def profile_tokens(tokens, max_rules: int) -> dict[str, int]:
    terminals, arities, seq = build_initial(tokens)
    rules: list[RuleDef] = []
    initial_params = sum(len(o.args) for o in seq)

    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter((seq[i].symbol, seq[i + 1].symbol) for i in range(len(seq) - 1))
        # Try high-frequency candidates until one has >2 non-overlapping uses.
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
        # Keep a rule only if exact serialized payload does not grow.  This
        # enforces the project's best-so-far monotonicity at the representation
        # level rather than trusting pair frequency alone.
        before = serialize(terminals, rules, seq)
        trial_rules = rules + [rule]
        after = serialize(terminals, trial_rules, new_seq)
        if len(after) > len(before):
            # A frequent pair may be bad because it binds few constants.  Try
            # several alternatives and choose the best exact payload delta.
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

    payload = serialize(terminals, rules, seq)
    final_params = sum(len(o.args) for o in seq) + sum(len(r.constants) for r in rules)
    bound_constants = sum(sum(r.constant_mask) * max(0, 1) for r in rules)
    return {
        "terminals": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
        "initial_parameter_occurrences": initial_params,
        "stored_parameter_values": final_params,
        "rule_constant_bindings": bound_constants,
        "payload_bytes": len(payload),
        "bf_native_loader_chars": len(loader_source_for_bytes(payload)[0]),
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
    best = min(sweep, key=lambda r: r["bf_native_loader_chars"])
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
            print(f"{r['name']}: payload={b['payload_bytes']:,} loader={b['bf_native_loader_chars']:,} params={b['stored_parameter_values']:,} rules={b['rules']}")


if __name__ == "__main__":
    main()
