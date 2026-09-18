from __future__ import annotations

"""Verify exact reconstruction of relational semantic macro grammars."""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_signed_relational_macro_grammar import ADD, CONST, NEGADD, PARAM, Occ, build_grammar
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

    arg_iter = iter(occ.args)
    vector: list[int] = []
    for j, spec in enumerate(rule.specs):
        if spec.kind == PARAM:
            vector.append(next(arg_iter))
        elif spec.kind == CONST:
            vector.append(spec.value)
        elif spec.kind == ADD:
            assert 0 <= spec.ref < j
            vector.append(vector[spec.ref] + spec.value)
        elif spec.kind == NEGADD:
            assert 0 <= spec.ref < j
            vector.append(-vector[spec.ref] + spec.value)
        else:
            raise AssertionError(spec)
    try:
        next(arg_iter)
        raise AssertionError("unused call argument")
    except StopIteration:
        pass

    assert len(vector) == rule.input_arity
    left_arity = arities[rule.left]
    right_arity = arities[rule.right]
    assert left_arity + right_arity == len(vector)

    left = Occ(rule.left, tuple(vector[:left_arity]))
    right = Occ(rule.right, tuple(vector[left_arity:]))
    return expand_occ(left, terminals, arities, rules) + expand_occ(right, terminals, arities, rules)


def verify_tokens(tokens, max_rules=512):
    terminals, arities, rules, seq, _ = build_grammar(tokens, max_rules)
    expected = [split_token(t) for t in tokens]
    recovered = []
    for occ in seq:
        recovered.extend(expand_occ(occ, terminals, arities, rules))
    assert recovered == expected, (len(expected), len(recovered), rules[:3], seq[:3])

    relation_count = 0
    for rid, rule in enumerate(rules):
        symbol = len(terminals) + rid
        assert arities[symbol] == rule.arity
        assert rule.left < symbol and rule.right < symbol
        for j, spec in enumerate(rule.specs):
            if spec.kind in (ADD, NEGADD):
                assert 0 <= spec.ref < j
                relation_count += 1
    return len(rules), len(seq), relation_count


def tokens_from_text(text: str):
    nodes = canonicalize(parse(precanonicalize(strip_bf(text))))
    return semantic_tokens(nodes, Counter())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--max-rules", type=int, default=128)
    args = ap.parse_args()

    synthetic_tokens = []
    for base in range(-80, 81, 4):
        # Same two-MOVE template translated by base.  The second slot is always
        # first+3, so a correct relational rule can keep one call parameter.
        synthetic_tokens.extend([("M", base), ("M", base + 3)])
    rules, start, rels = verify_tokens(synthetic_tokens, max_rules=64)
    assert rels > 0, (rules, start, rels)

    synthetic_texts = [
        ">>>>+<<<<" * 40,
        "".join(">" * d + "+" + "<" * d for d in range(1, 32)) * 5,
        ("+++[->+<]>>--[->++<]<<." * 20),
    ]
    for text in synthetic_texts:
        verify_tokens(tokens_from_text(text), max_rules=128)

    for name in args.files:
        tokens = tokens_from_text(Path(name).read_text(encoding="ascii", errors="ignore"))
        rules, start, rels = verify_tokens(tokens, max_rules=args.max_rules)
        print(
            f"{name}: relational round-trip ok tokens={len(tokens):,} "
            f"rules={rules} start={start:,} add_relations={rels:,}"
        )

    print("relational macro grammar reconstruction: ok")


if __name__ == "__main__":
    main()
