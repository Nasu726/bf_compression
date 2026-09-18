from __future__ import annotations

"""Build and measure a straight-line grammar over semantic BF tokens.

Pointer/arithmetic runs become semantic terminals, then global byte-pair
replacement creates binary nonterminals usable by a recursive VM.  In addition
to the grammar size, this profiler serializes the grammar exactly and measures
how much residual information remains after ordinary byte compression.

The compressed sizes are NOT achieved BF source sizes.  They are information
headroom proxies.  A standalone BF program still needs a payload constructor,
decoder/grammar expander, semantic-token interpreter, and its own work tape.
"""

import argparse
import bz2
from collections import Counter
import json
import lzma
import math
from pathlib import Path
import zlib

BF = frozenset("><+-.,[]")
Token = tuple[str, int] | tuple[str]


def strip_bf(text: str) -> str:
    return "".join(ch for ch in text if ch in BF)


def semantic_tokens(code: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch in "><":
            delta = 0
            while i < n and code[i] in "><":
                delta += 1 if code[i] == ">" else -1
                i += 1
            if delta:
                out.append(("M", delta))
            continue
        if ch in "+-":
            delta = 0
            while i < n and code[i] in "+-":
                delta += 1 if code[i] == "+" else -1
                i += 1
            z = delta & 255
            if z:
                signed = z if z <= 128 else z - 256
                out.append(("A", signed))
            continue
        out.append((ch,))
        i += 1
    return out


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


def terminal_definition(tok: Token) -> bytes:
    # Opcodes 0..7 are local to this serialized grammar format.
    kind = tok[0]
    if kind == "M":
        value = int(tok[1])
        return bytes([0 if value >= 0 else 1]) + encode_uleb(abs(value))
    if kind == "A":
        value = int(tok[1])
        return bytes([2 if value >= 0 else 3]) + encode_uleb(abs(value))
    opcode = {".": 4, ",": 5, "[": 6, "]": 7}[kind]
    return bytes([opcode])


def serialize_grammar(
    terminals: list[Token], rules: list[tuple[int, int]], seq: list[int]
) -> bytes:
    out = bytearray()
    out += encode_uleb(len(terminals))
    out += encode_uleb(len(rules))
    out += encode_uleb(len(seq))
    for tok in terminals:
        out += terminal_definition(tok)
    for a, b in rules:
        out += encode_uleb(a)
        out += encode_uleb(b)
    for symbol in seq:
        out += encode_uleb(symbol)
    return bytes(out)


def three_bit_capacity_chars(blob_bytes: int) -> int:
    """Chars needed if an 8-symbol source carried all payload bits perfectly.

    This is only a coding-capacity floor for this exact blob, not a lower bound
    on the shortest equivalent BF program: a better semantic representation may
    contain fewer bits, and executable BF syntax cannot generally devote all
    three bits per character to literal payload data.
    """
    return math.ceil(blob_bytes * 8 / 3)


def bpe_grammar(tokens: list[Token], max_rules: int) -> dict[str, object]:
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
    replacement_counts: list[int] = []
    for _ in range(max_rules):
        if len(seq) < 2:
            break
        counts = Counter(zip(seq, seq[1:]))
        if not counts:
            break
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
        replacement_counts.append(replaced)
        seq = new_seq

    payload = serialize_grammar(terminals, rules, seq)
    compressed = {
        "zlib9": len(zlib.compress(payload, 9)),
        "bz2_9": len(bz2.compress(payload, compresslevel=9)),
        "lzma9": len(lzma.compress(payload, preset=9)),
    }
    return {
        "input_tokens": len(tokens),
        "terminal_kinds": len(terminals),
        "rules": len(rules),
        "start_symbols": len(seq),
        "abstract_grammar_symbols": len(seq) + 2 * len(rules),
        "serialized_payload_bytes": len(payload),
        "payload_compressed_bytes": compressed,
        "payload_three_bit_capacity_chars": {
            key: three_bit_capacity_chars(size) for key, size in compressed.items()
        },
        "replacement_counts": replacement_counts,
    }


def profile_text(text: str, max_rules: int) -> dict[str, object]:
    code = strip_bf(text)
    return {
        "bf_bytes": len(code),
        "grammar": bpe_grammar(semantic_tokens(code), max_rules=max_rules),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-rules", type=int, default=256)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.files:
        path = Path(name)
        rows.append({
            "name": str(path),
            **profile_text(path.read_text(encoding="ascii", errors="ignore"), args.max_rules),
        })
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            g = row["grammar"]
            print(
                f"{row['name']}: bf={row['bf_bytes']:,} tokens={g['input_tokens']:,} "
                f"rules={g['rules']} payload={g['serialized_payload_bytes']:,} "
                f"payload_lzma={g['payload_compressed_bytes']['lzma9']:,}"
            )


if __name__ == "__main__":
    main()
