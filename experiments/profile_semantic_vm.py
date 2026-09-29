from __future__ import annotations

"""Profile a semantics-first VM representation for whole-program BF compression.

The key distinction from ordinary grammar compression is that a long BF region
need not repeat textually to become short.  Recognized semantic classes become
single parameterized VM instructions:

* MOVE(delta) and ADD(delta) collapse arbitrary straight runs;
* CLEAR represents the standard 8-bit clear loop;
* AFFINE represents any flat pointer-balanced arithmetic loop whose control
  delta is odd, canonicalized by its *net transfer semantics*;
* LINEAR_LOOP represents every other flat pointer-balanced arithmetic loop
  exactly, including nontermination cases;
* SCAN represents a pure-moving leaf loop with nonzero net stride;
* unrecognized loops remain structured LOOP_BEGIN/body/LOOP_END tokens.

The resulting instruction sequence is then optionally factored by a binary
straight-line grammar.  The serialized payload is a compact bytecode data model,
NOT yet a complete BF program.  A standalone result must still construct the
payload on tape and include a BF VM/grammar expander.  We therefore also report
literal BF-native payload-loader costs using the verified 16-symbol unequal-cost
channel from ``profile_bf_native_channel.py``.
"""

import argparse
import bz2
from collections import Counter
import json
import lzma
from pathlib import Path
import sys
import zlib
from typing import Hashable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bf_native_channel import loader_source_for_bytes
from profile_dead_affine_targets import flat_balanced_coeff
from region_zero_opt import Loop, canonicalize, parse, precanonicalize, stringify, strip_bf

Token = tuple[Hashable, ...]


def encode_uleb(value: int) -> bytes:
    assert value >= 0
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(value: int) -> int:
    return 2 * value if value >= 0 else -2 * value - 1


def pure_move_delta(body: tuple[object, ...]) -> int | None:
    delta = 0
    for node in body:
        if node == ">":
            delta += 1
        elif node == "<":
            delta -= 1
        else:
            return None
    return delta


def signed_mod_byte(value: int) -> int:
    value &= 255
    return value if value <= 128 else value - 256


def semantic_loop_token(body: tuple[object, ...]) -> Token | None:
    body = canonicalize(body)
    if body == ("-",) or body == ("+",):
        return ("CLEAR",)

    coeff = flat_balanced_coeff(body)
    if coeff is not None:
        control = coeff.get(0, 0)
        if control & 1:
            inv = pow(control, -1, 256)
            transfer = tuple(
                sorted(
                    (off, (-amount * inv) & 255)
                    for off, amount in coeff.items()
                    if off != 0 and amount
                )
            )
            if not transfer:
                return ("CLEAR",)
            return ("AFFINE", transfer)
        # Exact one-iteration sparse vector.  The VM repeats it while the
        # current control cell is nonzero, so even-control divergence behavior
        # is retained rather than silently assuming termination.
        vector = tuple(sorted((off, amount & 255) for off, amount in coeff.items() if amount))
        return ("LINEAR_LOOP", vector)

    stride = pure_move_delta(body)
    if stride is not None and stride != 0:
        return ("SCAN", stride)
    return None


def append_run(tokens: list[Token], kind: str | None, amount: int) -> None:
    if kind is None:
        return
    if kind == "M":
        if amount:
            tokens.append(("M", amount))
        return
    if kind == "A":
        z = amount & 255
        if z:
            tokens.append(("A", signed_mod_byte(z)))
        return
    raise AssertionError(kind)


def semantic_tokens(nodes: tuple[object, ...], stats: Counter[str]) -> list[Token]:
    out: list[Token] = []
    run_kind: str | None = None
    run_amount = 0

    def flush() -> None:
        nonlocal run_kind, run_amount
        append_run(out, run_kind, run_amount)
        run_kind = None
        run_amount = 0

    for node in nodes:
        if node in (">", "<"):
            if run_kind != "M":
                flush()
                run_kind = "M"
            run_amount += 1 if node == ">" else -1
            continue
        if node in ("+", "-"):
            if run_kind != "A":
                flush()
                run_kind = "A"
            run_amount += 1 if node == "+" else -1
            continue

        flush()
        if node == ".":
            out.append(("OUT",))
            continue
        if node == ",":
            out.append(("IN",))
            continue
        if not isinstance(node, Loop):
            raise AssertionError(node)

        body = canonicalize(node.body)
        token = semantic_loop_token(body)
        literal_bytes = 2 + len(stringify(body))
        if token is not None:
            kind = str(token[0])
            stats[f"{kind}_loops"] += 1
            stats[f"{kind}_literal_bytes"] += literal_bytes
            out.append(token)
        else:
            stats["generic_loops"] += 1
            out.append(("LOOP_BEGIN",))
            out.extend(semantic_tokens(body, stats))
            out.append(("LOOP_END",))
    flush()
    return out


def token_definition(token: Token) -> bytes:
    kind = token[0]
    if kind == "M":
        return bytes([0]) + encode_uleb(zigzag(int(token[1])))
    if kind == "A":
        return bytes([1, int(token[1]) & 255])
    if kind == "OUT":
        return bytes([2])
    if kind == "IN":
        return bytes([3])
    if kind == "CLEAR":
        return bytes([4])
    if kind == "SCAN":
        return bytes([5]) + encode_uleb(zigzag(int(token[1])))
    if kind in ("AFFINE", "LINEAR_LOOP"):
        opcode = 6 if kind == "AFFINE" else 7
        pairs = token[1]
        assert isinstance(pairs, tuple)
        out = bytearray([opcode])
        out += encode_uleb(len(pairs))
        for off, coeff in pairs:
            out += encode_uleb(zigzag(int(off)))
            out.append(int(coeff) & 255)
        return bytes(out)
    if kind == "LOOP_BEGIN":
        return bytes([8])
    if kind == "LOOP_END":
        return bytes([9])
    raise AssertionError(token)


def raw_vm_payload(tokens: list[Token]) -> bytes:
    """Self-delimiting terminal stream, useful before grammar factoring."""
    out = bytearray()
    for tok in tokens:
        definition = token_definition(tok)
        out += encode_uleb(len(definition))
        out += definition
    return bytes(out)


def bpe_payload(tokens: list[Token], max_rules: int) -> tuple[bytes, dict[str, int]]:
    terminal_ids: dict[Token, int] = {}
    terminals: list[Token] = []
    seq: list[int] = []
    for tok in tokens:
        sid = terminal_ids.get(tok)
        if sid is None:
            sid = len(terminals)
            terminal_ids[tok] = sid
            terminals.append(tok)
        seq.append(sid)

    rules: list[tuple[int, int]] = []
    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter(zip(seq, seq[1:]))
        pair, freq = counts.most_common(1)[0]
        if freq <= 2:
            break
        new_id = len(terminals) + len(rules)
        a, b = pair
        new_seq: list[int] = []
        i = 0
        replaced = 0
        while i < len(seq):
            if i + 1 < len(seq) and seq[i] == a and seq[i + 1] == b:
                new_seq.append(new_id)
                replaced += 1
                i += 2
            else:
                new_seq.append(seq[i])
                i += 1
        if replaced <= 2:
            break
        rules.append((a, b))
        seq = new_seq

    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for tok in terminals:
        definition = token_definition(tok)
        out += encode_uleb(len(definition))
        out += definition
    for a, b in rules:
        out += encode_uleb(a)
        out += encode_uleb(b)
    for sym in seq:
        out += encode_uleb(sym)
    return bytes(out), {
        "terminals": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
    }


def compressed_sizes(blob: bytes) -> dict[str, int]:
    return {
        "zlib9": len(zlib.compress(blob, 9)),
        "bz2_9": len(bz2.compress(blob, compresslevel=9)),
        "lzma9": len(lzma.compress(blob, preset=9)),
    }


def bf_native_loader_chars(blob: bytes) -> int:
    return len(loader_source_for_bytes(blob)[0])


def profile_text(text: str) -> dict[str, object]:
    raw = strip_bf(text)
    nodes = canonicalize(parse(precanonicalize(raw)))
    stats: Counter[str] = Counter()
    tokens = semantic_tokens(nodes, stats)
    raw_payload = raw_vm_payload(tokens)

    grammar_rows = []
    for limit in (0, 16, 32, 64, 128, 256, 512):
        payload, meta = bpe_payload(tokens, limit)
        comps = compressed_sizes(payload)
        grammar_rows.append({
            "max_rules": limit,
            "payload_bytes": len(payload),
            "bf_native_loader_chars": bf_native_loader_chars(payload),
            "compressed_bytes": comps,
            "compressed_bf_native_loader_chars": {
                name: bf_native_loader_chars(
                    zlib.compress(payload, 9)
                    if name == "zlib9"
                    else bz2.compress(payload, compresslevel=9)
                    if name == "bz2_9"
                    else lzma.compress(payload, preset=9)
                )
                for name in comps
            },
            **meta,
        })

    best = min(grammar_rows, key=lambda row: int(row["payload_bytes"]))
    return {
        "bf_bytes": len(raw),
        "semantic_tokens": len(tokens),
        "raw_vm_payload_bytes": len(raw_payload),
        "raw_vm_bf_native_loader_chars": bf_native_loader_chars(raw_payload),
        "raw_vm_compressed_bytes": compressed_sizes(raw_payload),
        "loop_stats": dict(stats),
        "grammar_sweep": grammar_rows,
        "best_payload_rule_limit": best["max_rules"],
        "best_payload_bytes": best["payload_bytes"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        path = Path(name)
        rows.append({"name": str(path), **profile_text(path.read_text(encoding="ascii", errors="ignore"))})
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(
                f"{row['name']}: bf={row['bf_bytes']:,} tokens={row['semantic_tokens']:,} "
                f"raw_vm={row['raw_vm_payload_bytes']:,} "
                f"best_grammar={row['best_payload_bytes']:,}"
            )


if __name__ == "__main__":
    main()
