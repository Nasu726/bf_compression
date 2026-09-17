from __future__ import annotations

"""Build a simple straight-line grammar over semantic BF tokens.

This is closer to an executable macro dictionary than gzip/LZMA.  Pointer and
arithmetic runs become semantic terminals, then global byte-pair replacement
creates binary nonterminals usable as recursively expandable VM macros.

The reported serialized payload is still NOT a complete BF program: a BF
payload builder, grammar expander, and bytecode interpreter must be added before
it counts as achieved source compression.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Hashable

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


def uleb_size(value: int) -> int:
    assert value >= 0
    out = 1
    while value >= 128:
        value >>= 7
        out += 1
    return out


def token_definition_size(tok: Token) -> int:
    # One terminal opcode byte. M/A use separate sign opcodes, then magnitude.
    if tok[0] in ("M", "A"):
        return 1 + uleb_size(abs(int(tok[1])))
    return 1


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
        # A binary rule costs two RHS symbol references in abstract grammar
        # size. Replacing <=2 occurrences cannot reduce symbol count.
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

    # Serializable grammar format:
    #   terminal_count, rule_count, start_length (ULEB each)
    #   implicit terminal IDs 0..T-1, each terminal definition
    #   implicit rule IDs T..T+R-1, each two ULEB symbol refs
    #   start sequence as ULEB symbol refs
    t = len(terminals)
    r = len(rules)
    payload = uleb_size(t) + uleb_size(r) + uleb_size(len(seq))
    payload += sum(token_definition_size(tok) for tok in terminals)
    payload += sum(uleb_size(a) + uleb_size(b) for a, b in rules)
    payload += sum(uleb_size(s) for s in seq)

    abstract_symbols = len(seq) + 2 * len(rules)
    return {
        "input_tokens": len(tokens),
        "terminal_kinds": t,
        "rules": r,
        "start_symbols": len(seq),
        "abstract_grammar_symbols": abstract_symbols,
        "serialized_payload_bytes": payload,
        "replacement_counts": replacement_counts,
    }


def profile_text(text: str, max_rules: int) -> dict[str, object]:
    code = strip_bf(text)
    tokens = semantic_tokens(code)
    grammar = bpe_grammar(tokens, max_rules=max_rules)
    return {
        "bf_bytes": len(code),
        "grammar": grammar,
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
                f"rules={g['rules']} grammar_symbols={g['abstract_grammar_symbols']:,} "
                f"payload={g['serialized_payload_bytes']:,}"
            )


if __name__ == "__main__":
    main()
