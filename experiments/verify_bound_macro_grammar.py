from __future__ import annotations

"""Verify exact reconstruction of constant-binding macro grammars."""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_bound_macro_grammar import Occ, build_grammar
from profile_parametric_vm import split_token
from profile_semantic_vm import semantic_tokens
from region_zero_opt import canonicalize, parse, precanonicalize, strip_bf


def expand_occ(occ, terminals, arities, rules):
    terminal_count = len(terminals)
    if occ.symbol < terminal_count:
        assert len(occ.args) == arities[occ.symbol]
        return [(terminals[occ.symbol], occ.args)]

    rid = occ.symbol - terminal_count
    assert 0 <= rid < len(rules)
    rule = rules[rid]
    assert len(occ.args) == rule.arity
    const_iter = iter(rule.constants)
    arg_iter = iter(occ.args)
    vector = []
    for fixed in rule.constant_mask:
        vector.append(next(const_iter) if fixed else next(arg_iter))
    try:
        next(const_iter)
        raise AssertionError("unused rule constant")
    except StopIteration:
        pass
    try:
        next(arg_iter)
        raise AssertionError("unused call argument")
    except StopIteration:
        pass
    assert len(vector) == rule.input_arity

    left_arity = arities[rule.left]
    right_arity = arities[rule.right]
    assert left_arity + right_arity == rule.input_arity
    left = Occ(rule.left, tuple(vector[:left_arity]))
    right = Occ(rule.right, tuple(vector[left_arity:]))
    return (
        expand_occ(left, terminals, arities, rules)
        + expand_occ(right, terminals, arities, rules)
    )


def verify_tokens(tokens, max_rules=512):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    expected = [split_token(t) for t in tokens]
    recovered = []
    for occ in seq:
        recovered.extend(expand_occ(occ, terminals, arities, rules))
    assert recovered == expected, (
        len(expected), len(recovered), rules[:3], seq[:3]
    )
    for rid, rule in enumerate(rules):
        symbol = len(terminals) + rid
        assert arities[symbol] == rule.arity
        assert rule.left < symbol and rule.right < symbol
    return len(rules), len(seq)


def tokens_from_text(text: str):
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    synthetic = [
        # repeated exact template
        ">>>>+<<<<" * 40,
        # same opcode skeleton with varying MOVE parameters and invariant ADD
        "".join(">" * d + "+" + "<" * d for d in range(1, 32)) * 5,
        # nested/affine terminal mixture
        ("+++[->+<]>>--[->++<]<<." * 20),
    ]
    for text in synthetic:
        verify_tokens(tokens_from_text(text), max_rules=128)

    for name in args.files:
        tokens = tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore"))
        rules, start = verify_tokens(tokens, max_rules=512)
        print(f"{name}: round-trip ok tokens={len(tokens):,} rules={rules} start={start:,}")

    print("bound macro grammar reconstruction: ok")


if __name__ == "__main__":
    main()
